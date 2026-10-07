"use client";

import { useActionState, useState } from "react";
import { decidir } from "@/app/(app)/clientes/[id]/periodos/[periodoId]/revision/actions";
import { DECISIONES, type EstadoDecision } from "@/lib/revision";

const INICIAL: EstadoDecision = { ok: false, mensaje: "" };

/** Formulario de decisión de una partida. «Revisado por» es el usuario con sesión (lo pone la base). */
export function Decision(props: {
  corridaId: string;
  codigo: string;
  sugerida: string | null;
  decision: string | null;
  comentario: string | null;
  deshabilitado?: boolean;
}) {
  const [estado, accion, enviando] = useActionState(decidir, INICIAL);
  const [eleccion, setEleccion] = useState(props.decision ?? "");
  // La sugerencia puede traer alternativas («Aceptar / Corregido en el sistema»): solo se ofrece si es una.
  const sugerida = props.sugerida && DECISIONES.includes(props.sugerida) ? props.sugerida : null;
  const id = `dec-${props.codigo}`;

  return (
    <form action={accion} className="space-y-2">
      <input type="hidden" name="corrida_id" value={props.corridaId} />
      <input type="hidden" name="codigo" value={props.codigo} />
      <label htmlFor={id} className="etiqueta">Decisión</label>
      <select
        id={id}
        name="decision"
        className="campo"
        value={eleccion}
        onChange={(e) => setEleccion(e.target.value)}
        disabled={props.deshabilitado || enviando}
        required
      >
        <option value="">— elegir —</option>
        {DECISIONES.map((d) => (
          <option key={d} value={d}>{d}{d === sugerida ? " (sugerida)" : ""}</option>
        ))}
      </select>
      {!eleccion && sugerida && !props.deshabilitado && (
        <button type="button" className="text-xs text-acento underline" onClick={() => setEleccion(sugerida)}>
          Usar la sugerida: {sugerida}
        </button>
      )}
      <textarea
        name="comentario"
        className="campo min-h-16"
        placeholder={eleccion === "Justificado" ? "Comentario (obligatorio): por qué está bien así" : "Comentario (opcional)"}
        defaultValue={props.comentario ?? ""}
        maxLength={2000}
        disabled={props.deshabilitado || enviando}
        required={eleccion === "Justificado"}
      />
      <div className="flex items-center gap-3">
        <button className="boton" disabled={props.deshabilitado || enviando || !eleccion}>
          {enviando ? "Guardando…" : props.decision ? "Cambiar" : "Guardar"}
        </button>
        {estado.mensaje && (
          <span className={`text-xs ${estado.ok ? "text-acento" : "text-alerta"}`} role="status">{estado.mensaje}</span>
        )}
      </div>
    </form>
  );
}
