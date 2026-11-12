// Montos en formato venezolano SIN pasar por number: el valor llega como texto exacto de Postgres
// (numeric(18,2)::text, p. ej. "-1234567.80") y solo se reagrupan los dígitos.

/** "-1234567.80" → "-1.234.567,80". Vacío o null → "—". No redondea ni recorta decimales. */
export function formatoVE(v: string | null | undefined): string {
  if (v == null || v === "") return "—";
  const negativo = v.startsWith("-");
  const s = negativo ? v.slice(1) : v;
  if (!/^\d+(\.\d+)?$/.test(s)) return v; // no es un número: se muestra tal cual, sin adivinar
  const [entero, decimales = ""] = s.split(".");
  const miles = entero.replace(/\B(?=(\d{3})+(?!\d))/g, ".");
  return `${negativo ? "-" : ""}${miles},${decimales.padEnd(2, "0")}`;
}

/**
 * Monto escrito por el analista → texto exacto con 2 decimales ("635.917,59", "635917.59", "-1.200" → "635917.59",
 * "635917.59", "-1200.00"). Devuelve null si está vacío y lanza un error si no es un monto válido o tiene más
 * de 2 decimales (no se redondea). No pasa por number.
 */
export function montoEscrito(entrada: string): string | null {
  const t = entrada.trim().replace(/\s/g, "");
  if (!t) return null;
  let s = t;
  if (/^-?\d{1,3}(\.\d{3})+(,\d{1,2})?$/.test(s) || /^-?\d+,\d{1,2}$/.test(s)) {
    s = s.replace(/\./g, "").replace(",", ".");          // formato venezolano: 1.234.567,89
  } else if (/^-?\d{1,3}(,\d{3})+(\.\d{1,2})?$/.test(s)) {
    s = s.replace(/,/g, "");                             // 1,234,567.89
  }
  if (!/^-?\d+(\.\d{1,2})?$/.test(s)) throw new Error(`«${entrada}» no es un monto válido (máximo 2 decimales)`);
  const [ent, dec = ""] = s.split(".");
  const negativo = ent.startsWith("-");
  const e = ent.replace("-", "").replace(/^0+(?=\d)/, "");
  return `${negativo ? "-" : ""}${e}.${dec.padEnd(2, "0")}`;
}
