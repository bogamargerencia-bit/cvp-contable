/** Barra de avance. Sin `valor` se muestra indeterminada (animada). */
export function Barra({ valor, etiqueta }: { valor?: number; etiqueta: string }) {
  const v = valor === undefined ? undefined : Math.max(2, Math.min(100, valor));
  return (
    <div className="space-y-1.5" role="progressbar" aria-label={etiqueta} aria-valuemin={0} aria-valuemax={100} aria-valuenow={v}>
      <div className="flex items-baseline justify-between gap-3 text-xs">
        <span className="text-tinta">{etiqueta}</span>
        {v !== undefined && <span className="tabular-nums text-tenue">{v}%</span>}
      </div>
      <div className="h-2 overflow-hidden rounded-full bg-linea">
        {v === undefined ? (
          <div className="barra-indeterminada h-full w-1/3 rounded-full bg-acento" />
        ) : (
          <div className="h-full rounded-full bg-acento transition-[width] duration-700 ease-out" style={{ width: `${v}%` }} />
        )}
      </div>
    </div>
  );
}
