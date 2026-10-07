"use client";

import { useFormStatus } from "react-dom";

/** Botón de envío que se desactiva mientras la acción está en curso (evita dobles clics). */
export function BotonEnviar({ texto, enviando, deshabilitado }: { texto: string; enviando: string; deshabilitado?: boolean }) {
  const { pending } = useFormStatus();
  return (
    <button className="boton" disabled={deshabilitado || pending}>
      {pending ? enviando : texto}
    </button>
  );
}
