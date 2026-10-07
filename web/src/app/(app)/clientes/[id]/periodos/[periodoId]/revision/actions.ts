"use server";

import { refresh } from "next/cache";
import { perfilActual } from "@/lib/sesion";
import { crearClienteServidor } from "@/lib/supabase/server";
import { DECISIONES, type EstadoDecision } from "@/lib/revision";

/**
 * Registra la decisión de una partida (función registrar_decision en Supabase: corre con los permisos
 * del usuario, deja la anterior como no vigente y firma con su id). Se aplica en la próxima corrida.
 */
export async function decidir(_prev: EstadoDecision, f: FormData): Promise<EstadoDecision> {
  await perfilActual();
  const corrida = String(f.get("corrida_id") ?? "");
  const codigo = String(f.get("codigo") ?? "");
  const decision = String(f.get("decision") ?? "");
  const comentario = String(f.get("comentario") ?? "").trim();

  if (!DECISIONES.includes(decision)) return { ok: false, mensaje: "Elige una decisión." };
  if (decision === "Justificado" && !comentario) {
    return { ok: false, mensaje: "«Justificado» requiere un comentario que explique por qué." };
  }
  if (comentario.length > 2000) return { ok: false, mensaje: "El comentario es demasiado largo (máx. 2000)." };

  const supabase = await crearClienteServidor();
  const { error } = await supabase.rpc("registrar_decision", {
    p_corrida: corrida,
    p_codigo: codigo,
    p_decision: decision,
    p_comentario: comentario,
  });
  if (error) {
    const m = error.message ?? "";
    return {
      ok: false,
      mensaje: m.includes("cerrado") ? "El período está cerrado: ya no se pueden registrar decisiones."
        : m.includes("no existe") ? "Esa partida ya no está en la corrida (¿se procesó de nuevo?). Recarga la página."
        : "No se pudo guardar la decisión.",
    };
  }
  refresh();
  return { ok: true, mensaje: "Guardada. Se aplica al volver a procesar." };
}
