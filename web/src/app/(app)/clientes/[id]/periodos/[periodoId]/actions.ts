"use server";

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";
import { perfilActual } from "@/lib/sesion";
import { montoEscrito } from "@/lib/montos";
import { MINUTOS_EN_COLA } from "@/lib/tipos";
import { crearClienteAdmin } from "@/lib/supabase/admin";
import { crearClienteServidor } from "@/lib/supabase/server";

// Con el plan Free de Railway (serverless) el servicio se duerme sin uso y tarda en despertar.
const SEGUNDOS_ESPERA_SERVICIO = 60;

const MENSAJE_ATASCADA =
  `El servicio no tomó la corrida en ${MINUTOS_EN_COLA} minutos (¿variables de Railway o servicio detenido?). Vuelve a procesar.`;

function ruta(clienteId: string, periodoId: string) {
  return `/clientes/${clienteId}/periodos/${periodoId}`;
}
function volver(r: string, k: "error" | "ok", m: string): never {
  redirect(`${r}?${k}=${encodeURIComponent(m)}`);
}

/** Crea la corrida (RLS: el usuario debe tener acceso al cliente) y avisa al servicio de Railway. */
export async function procesar(f: FormData) {
  const perfil = await perfilActual();
  const clienteId = String(f.get("cliente_id"));
  const periodoId = String(f.get("periodo_id"));
  const r = ruta(clienteId, periodoId);
  const supabase = await crearClienteServidor();

  const { data: periodo } = await supabase.from("periodos").select("id, estado").eq("id", periodoId).maybeSingle();
  if (!periodo) volver(r, "error", "Período no encontrado");
  if (periodo.estado === "cerrado") volver(r, "error", "El período está cerrado");

  // Una corrida que lleva más de MINUTOS_EN_COLA sin que el servicio la tome se da por fallida.
  const limite = new Date(Date.now() - MINUTOS_EN_COLA * 60_000).toISOString();
  await crearClienteAdmin().from("corridas")
    .update({ estado: "error", error: MENSAJE_ATASCADA, terminada_en: new Date().toISOString() })
    .eq("periodo_id", periodoId).eq("estado", "pendiente").lt("creada_en", limite);

  const { data: enCurso } = await supabase.from("corridas").select("id")
    .eq("periodo_id", periodoId).in("estado", ["pendiente", "procesando"]).limit(1);
  if (enCurso?.length) volver(r, "error", "Ya hay una corrida en proceso para este período");

  const { data: ultima } = await supabase.from("corridas").select("numero")
    .eq("periodo_id", periodoId).order("numero", { ascending: false }).limit(1);
  const numero = (ultima?.[0]?.numero ?? 0) + 1;
  const { data: corrida, error } = await supabase.from("corridas")
    .insert({ periodo_id: periodoId, numero, creada_por: perfil.id }).select("id").single();
  if (error || !corrida) volver(r, "error", "No se pudo crear la corrida (¿otra persona procesó al mismo tiempo?)");

  const url = process.env.SERVICIO_URL;
  const token = process.env.SERVICIO_TOKEN;
  let fallo = "";
  if (!url || !token) {
    fallo = "El servicio de procesamiento no está configurado (SERVICIO_URL / SERVICIO_TOKEN en Vercel).";
  } else {
    try {
      const resp = await fetch(`${url.replace(/\/$/, "")}/procesar`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
        body: JSON.stringify({ corrida_id: corrida.id }),
        signal: AbortSignal.timeout(SEGUNDOS_ESPERA_SERVICIO * 1000),
        cache: "no-store",
      });
      if (resp.status !== 202) {
        const cuerpo = await resp.json().catch(() => null);
        fallo = typeof cuerpo?.detail === "string" ? cuerpo.detail
          : resp.status === 404
            ? "El servicio respondió 404: Railway no tiene la aplicación activa (revisa el plan o si el servicio está detenido)."
            : `El servicio respondió ${resp.status}.`;
      }
    } catch (e) {
      fallo = e instanceof Error && e.name === "TimeoutError"
        ? `El servicio no respondió en ${SEGUNDOS_ESPERA_SERVICIO} segundos (puede estar despertando en Railway). Vuelve a procesar.`
        : "No se pudo contactar al servicio de procesamiento (¿está encendido en Railway?).";
    }
  }
  if (fallo) {
    // El usuario no puede escribir en corridas (solo el servicio): se marca el error con la clave del servidor.
    await crearClienteAdmin().from("corridas")
      .update({ estado: "error", error: fallo, terminada_en: new Date().toISOString() })
      .eq("id", corrida.id).eq("estado", "pendiente");
    volver(r, "error", fallo);
  }
  revalidatePath(r);
  volver(r, "ok", `Corrida ${numero} en proceso`);
}

/**
 * Cerrar el período o reabrirlo (solo admin: lo valida el trigger).
 * Un analista solo cierra con OK general en la última corrida; el admin puede cerrar sin él
 * (p. ej. cuando el propio estado de cuenta del banco no cuadra y está justificado).
 */
export async function cambiarEstadoPeriodo(f: FormData) {
  const perfil = await perfilActual();
  const clienteId = String(f.get("cliente_id"));
  const periodoId = String(f.get("periodo_id"));
  const estado = f.get("estado") === "cerrado" ? "cerrado" : "abierto";
  const r = ruta(clienteId, periodoId);
  const supabase = await crearClienteServidor();
  if (estado === "cerrado") {
    const { data: ultima } = await supabase.from("corridas").select("numero, estado, ok_general")
      .eq("periodo_id", periodoId).order("numero", { ascending: false }).limit(1);
    const c = ultima?.[0];
    if (!c || c.estado !== "lista") volver(r, "error", "Para cerrar, la última corrida debe estar terminada");
    if (!c.ok_general && perfil.rol !== "admin") {
      volver(r, "error", `La corrida ${c.numero} no tiene OK general: decide las partidas abiertas y vuelve a procesar. `
        + "Si hay que cerrar igual, debe hacerlo un administrador.");
    }
  }
  const { error } = await supabase.from("periodos").update({ estado }).eq("id", periodoId);
  if (error) volver(r, "error", estado === "abierto" ? "Solo un administrador puede reabrir el período" : "No se pudo cerrar");
  revalidatePath(r);
  volver(r, "ok", estado === "cerrado" ? "Período cerrado" : "Período reabierto");
}

/**
 * Saldos que informa el cliente por banco/caja (modo «Clasificación por cuenta»). Se guardan como texto exacto en
 * periodos.saldos; los usa la próxima corrida para el cuadre. Campos: inicial__<BANCO> y final__<BANCO>.
 */
export async function guardarSaldos(f: FormData) {
  await perfilActual();
  const clienteId = String(f.get("cliente_id"));
  const periodoId = String(f.get("periodo_id"));
  const r = ruta(clienteId, periodoId);
  const saldos: Record<string, { inicial: string | null; final: string | null }> = {};
  try {
    for (const [k, v] of f.entries()) {
      const m = /^(inicial|final)__(.+)$/.exec(k);
      if (!m) continue;
      const banco = m[2].toUpperCase();
      saldos[banco] ??= { inicial: null, final: null };
      saldos[banco][m[1] as "inicial" | "final"] = montoEscrito(String(v));
    }
  } catch (e) {
    volver(r, "error", e instanceof Error ? e.message : "Monto no válido");
  }
  const supabase = await crearClienteServidor();
  const { error } = await supabase.from("periodos").update({ saldos }).eq("id", periodoId);
  if (error) volver(r, "error", "No se pudieron guardar los saldos (¿período cerrado?)");
  revalidatePath(r);
  volver(r, "ok", "Saldos guardados: se usan en la próxima corrida");
}
