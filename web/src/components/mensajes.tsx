/** Muestra ?error= y ?ok= de la URL (las Server Actions redirigen con estos parámetros). */
export function Mensajes({ error, ok }: { error?: string | string[]; ok?: string | string[] }) {
  const e = Array.isArray(error) ? error[0] : error;
  const o = Array.isArray(ok) ? ok[0] : ok;
  if (!e && !o) return null;
  return (
    <div className="mb-6 space-y-2">
      {e && <p className="msg-error" role="alert">{e}</p>}
      {o && <p className="msg-ok" role="status">{o}</p>}
    </div>
  );
}
