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
