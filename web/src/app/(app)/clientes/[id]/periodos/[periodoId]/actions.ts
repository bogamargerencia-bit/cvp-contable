"use server";

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";
import { perfilActual } from "@/lib/sesion";
import { crearClienteAdmin } from "@/lib/supabase/admin";
import { crearClienteServidor } from "@/lib/supabase/server";

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
        signal: AbortSignal.timeout(15000),
        cache: "no-store",
      });
      if (resp.status !== 202) fallo = `El servicio respondió ${resp.status}.`;
    } catch {
      fallo = "No se pudo contactar al servicio de procesamiento (¿está encendido en Railway?).";
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

/** Cerrar el período (cualquier usuario con acceso) o reabrirlo (solo admin: lo valida el trigger). */
export async function cambiarEstadoPeriodo(f: FormData) {
  await perfilActual();
  const clienteId = String(f.get("cliente_id"));
  const periodoId = String(f.get("periodo_id"));
  const estado = f.get("estado") === "cerrado" ? "cerrado" : "abierto";
  const r = ruta(clienteId, periodoId);
  const supabase = await crearClienteServidor();
  const { error } = await supabase.from("periodos").update({ estado }).eq("id", periodoId);
  if (error) volver(r, "error", estado === "abierto" ? "Solo un administrador puede reabrir el período" : "No se pudo cerrar");
  revalidatePath(r);
  volver(r, "ok", estado === "cerrado" ? "Período cerrado" : "Período reabierto");
}
