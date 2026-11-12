"use server";

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";
import { perfilActual } from "@/lib/sesion";
import { crearClienteServidor } from "@/lib/supabase/server";
import type { CuentaCatalogo } from "@/lib/tipos";

function volver(r: string, k: "error" | "ok", m: string, ancla = ""): never {
  redirect(`${r}?${k}=${encodeURIComponent(m)}${ancla}`);
}

/**
 * Cuenta elegida a mano para un movimiento pendiente (o «Excluir»). Se guarda en asignaciones_cuenta (RLS: el
 * analista debe ver al cliente; el período no puede estar cerrado) y se aplica al volver a procesar.
 * «Recordar»: además crea (o corrige) la regla «descripción exacta → cuenta» para los próximos meses.
 */
export async function asignar(f: FormData) {
  const perfil = await perfilActual();
  const clienteId = String(f.get("cliente_id"));
  const periodoId = String(f.get("periodo_id"));
  const r = `/clientes/${clienteId}/periodos/${periodoId}/clasificar`;
  const clave = String(f.get("clave") ?? "");
  const patron = String(f.get("patron") ?? "").trim();
  const excluir = f.get("accion") === "excluir";
  const cuenta = String(f.get("cuenta") ?? "").trim();
  const recordar = f.get("recordar") === "on" && !excluir;
  const ancla = `#f${String(f.get("fila") ?? "")}`;
  if (!clave) volver(r, "error", "Movimiento no identificado");

  const supabase = await crearClienteServidor();
  const { data: cliente } = await supabase.from("clientes").select("config").eq("id", clienteId).maybeSingle();
  const catalogo = ((cliente?.config as { catalogo?: CuentaCatalogo[] } | null)?.catalogo ?? []);
  const cat = catalogo.find((c) => c.cuenta === cuenta);
  if (!excluir && !cat) volver(r, "error", "Elige una cuenta del catálogo", ancla);

  let reglaId: string | null = null;
  if (recordar && cat && patron) {
    const { data: existente } = await supabase.from("reglas_clasificacion").select("id, cuenta")
      .eq("cliente_id", clienteId).eq("tipo", "exacta").eq("activa", true).is("banco", null).is("sentido", null)
      .ilike("patron", patron.replace(/[%_\\]/g, "\\$&")).limit(1);
    if (existente?.[0]) {
      reglaId = existente[0].id;
      if (existente[0].cuenta !== cat.cuenta) {
        const { error } = await supabase.from("reglas_clasificacion")
          .update({ cuenta: cat.cuenta, clasificacion: cat.clasificacion, nota: `Corregida por ${perfil.nombre ?? perfil.email}` })
          .eq("id", reglaId);
        if (error) volver(r, "error", "No se pudo corregir la regla", ancla);
      }
    } else {
      const { data, error } = await supabase.from("reglas_clasificacion").insert({
        cliente_id: clienteId, tipo: "exacta", patron, cuenta: cat.cuenta, clasificacion: cat.clasificacion,
        origen: "decision", nota: "Recordada al clasificar", creada_por: perfil.id,
      }).select("id").single();
      if (error || !data) volver(r, "error", "No se pudo guardar la regla", ancla);
      reglaId = data.id;
    }
  }

  const { error } = await supabase.from("asignaciones_cuenta").upsert({
    periodo_id: periodoId, clave, excluir,
    cuenta: excluir ? null : cat!.cuenta, clasificacion: excluir ? null : cat!.clasificacion,
    regla_id: reglaId, asignada_por: perfil.id, asignada_en: new Date().toISOString(),
  }, { onConflict: "periodo_id,clave" });
  if (error) {
    volver(r, "error", error.message.includes("cerrado") ? "El período está cerrado" : "No se pudo guardar", ancla);
  }
  revalidatePath(r);
  volver(r, "ok", excluir ? "Marcado para excluir" : `Asignado a ${cat!.cuenta}${reglaId ? " (y recordado)" : ""}`, ancla);
}

/** Quita una asignación (vuelve a decidir la regla en la próxima corrida). La regla recordada no se borra. */
export async function quitarAsignacion(f: FormData) {
  await perfilActual();
  const clienteId = String(f.get("cliente_id"));
  const periodoId = String(f.get("periodo_id"));
  const r = `/clientes/${clienteId}/periodos/${periodoId}/clasificar`;
  const supabase = await crearClienteServidor();
  const { error } = await supabase.from("asignaciones_cuenta").delete()
    .eq("periodo_id", periodoId).eq("clave", String(f.get("clave")));
  if (error) volver(r, "error", "No se pudo quitar (¿período cerrado?)");
  revalidatePath(r);
  volver(r, "ok", "Asignación quitada");
}
