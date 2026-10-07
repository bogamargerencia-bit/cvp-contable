// Revisión en línea: constantes compartidas entre la página (servidor) y el formulario (cliente).
// Deben coincidir con parser/cvp_parser/revision.py (Decision, Situacion, ABIERTAS).

export const DECISIONES = ["Aceptar", "Justificado", "Corregido en el sistema"];

export const ABIERTAS = ["Marcado como corregido, pero sigue igual", "Decisión incompleta", "Nuevo", "Sin decisión"];

/** Situación que se muestra cuando hay una decisión registrada después de la corrida (aún no aplicada). */
export const DECIDIDA = "Decidida (se aplica al procesar)";

export type EstadoDecision = { ok: boolean; mensaje: string };
