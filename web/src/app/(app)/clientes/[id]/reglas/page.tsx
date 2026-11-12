import Link from "next/link";
import { notFound } from "next/navigation";
import { BotonEnviar } from "@/components/boton-enviar";
import { Mensajes } from "@/components/mensajes";
import { crearClienteServidor } from "@/lib/supabase/server";
import type { CuentaCatalogo, ReglaClasificacion } from "@/lib/tipos";
import { cambiarRegla, crearRegla } from "./actions";

const TIPO: Record<string, string> = {
  exacta: "Es igual a", empieza: "Empieza por", contiene: "Contiene", regex: "Expresión",
};
const ORIGEN: Record<string, string> = { manual: "manual", carga_inicial: "carga inicial", decision: "al clasificar" };
const uno = (v: string | string[] | undefined) => (Array.isArray(v) ? v[0] : v);

function SelectorCuenta({ catalogo, valor, nombre = "cuenta" }: { catalogo: CuentaCatalogo[]; valor?: string | null; nombre?: string }) {
  const grupos = Array.from(new Set(catalogo.map((c) => c.grupo ?? "")));
  return (
    <select name={nombre} defaultValue={valor ?? "__MANO__"} className="campo w-auto">
      <option value="__MANO__">— Revisar siempre a mano —</option>
      {grupos.map((g) => (
        <optgroup key={g} label={g || "Cuentas"}>
          {catalogo.filter((c) => (c.grupo ?? "") === g).map((c) => <option key={c.cuenta} value={c.cuenta}>{c.cuenta}</option>)}
        </optgroup>
      ))}
    </select>
  );
}

export default async function Reglas({ params, searchParams }: PageProps<"/clientes/[id]/reglas">) {
  const { id } = await params;
  const sp = await searchParams;
  const q = (uno(sp.q) ?? "").trim();
  const inactivas = uno(sp.inactivas) === "1";
  const supabase = await crearClienteServidor();
  const [{ data: cliente }, { data: reglasD }] = await Promise.all([
    supabase.from("clientes").select("id, nombre, nombre_comercial, config").eq("id", id).maybeSingle(),
    supabase.from("reglas_clasificacion").select("*").eq("cliente_id", id)
      .order("tipo").order("prioridad").order("patron").limit(5000),
  ]);
  if (!cliente) notFound();
  const catalogo = ((cliente.config as { catalogo?: CuentaCatalogo[] } | null)?.catalogo ?? []);
  const todas = (reglasD ?? []) as ReglaClasificacion[];
  const Q = q.toUpperCase();
  const reglas = todas.filter((r) => (inactivas || r.activa)
    && (!Q || r.patron.toUpperCase().includes(Q) || (r.cuenta ?? "").toUpperCase().includes(Q)));
  // Orden en que se aplican: primero las «es igual a», luego el resto por prioridad.
  reglas.sort((a, b) => Number(a.tipo !== "exacta") - Number(b.tipo !== "exacta") || a.prioridad - b.prioridad
    || a.patron.localeCompare(b.patron));
  const mostrar = reglas.slice(0, 400);
  const nombre = cliente.nombre_comercial ?? cliente.nombre;

  return (
    <>
      <Link href={`/clientes/${id}`} className="text-sm text-tenue hover:text-acento">← {nombre}</Link>
      <div className="mt-2 mb-4">
        <h1 className="titulo">Reglas de clasificación</h1>
        <p className="mt-1 text-sm text-tenue">
          {todas.filter((r) => r.activa).length} activas · Se aplican en este orden: primero «Es igual a» (lo aprendido de
          meses anteriores), luego las demás de menor a mayor prioridad. La primera que coincide decide la cuenta.
        </p>
      </div>
      <Mensajes error={uno(sp.error)} ok={uno(sp.ok)} />

      <details className="tarjeta mb-6">
        <summary className="cursor-pointer px-4 py-3 text-sm font-medium">Nueva regla</summary>
        <form action={crearRegla} className="grid gap-3 border-t border-linea p-4 sm:grid-cols-2 lg:grid-cols-3">
          <input type="hidden" name="cliente_id" value={id} />
          <div>
            <label className="etiqueta" htmlFor="n_tipo">Si la descripción…</label>
            <select id="n_tipo" name="tipo" className="campo" defaultValue="exacta">
              {Object.entries(TIPO).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </select>
          </div>
          <div className="lg:col-span-2">
            <label className="etiqueta" htmlFor="n_patron">Texto</label>
            <input id="n_patron" name="patron" required className="campo" placeholder="p. ej. DISTRIBUIDORA GUADI" />
          </div>
          <div>
            <label className="etiqueta">→ Cuenta</label>
            <SelectorCuenta catalogo={catalogo} valor={catalogo[0]?.cuenta} />
          </div>
          <div>
            <label className="etiqueta" htmlFor="n_sentido">Solo para</label>
            <select id="n_sentido" name="sentido" className="campo" defaultValue="">
              <option value="">Ingresos y egresos</option>
              <option value="ingreso">Solo ingresos</option>
              <option value="egreso">Solo egresos</option>
            </select>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="etiqueta" htmlFor="n_banco">Banco (opcional)</label>
              <input id="n_banco" name="banco" className="campo" placeholder="Todos" />
            </div>
            <div>
              <label className="etiqueta" htmlFor="n_prio">Prioridad</label>
              <input id="n_prio" name="prioridad" type="number" min={0} max={10000} defaultValue={100} className="campo" />
            </div>
          </div>
          <div className="sm:col-span-2 lg:col-span-3">
            <label className="etiqueta" htmlFor="n_nota">Nota (por qué)</label>
            <input id="n_nota" name="nota" className="campo" placeholder="p. ej. criterio acordado con el cliente en noviembre" />
          </div>
          <div><BotonEnviar texto="Crear regla" enviando="Guardando…" /></div>
        </form>
      </details>

      <form className="mb-4 flex flex-wrap items-center gap-3 text-sm">
        <input name="q" defaultValue={q} placeholder="Buscar texto o cuenta" className="campo w-72" />
        <label className="flex items-center gap-1"><input type="checkbox" name="inactivas" value="1" defaultChecked={inactivas} /> Ver inactivas</label>
        <button className="boton-sec">Buscar</button>
        <span className="text-tenue">{reglas.length} regla(s){reglas.length > mostrar.length && ` (se muestran ${mostrar.length}; afina la búsqueda)`}</span>
      </form>

      <div className="overflow-x-auto">
        <table className="tabla">
          <thead>
            <tr><th>Si la descripción…</th><th>Texto</th><th>Cuenta</th><th>Condición</th><th className="text-right">Prior.</th><th>Origen</th><th></th></tr>
          </thead>
          <tbody>
            {mostrar.map((r) => (
              <tr key={r.id} className={r.activa ? "" : "opacity-50"}>
                <td className="whitespace-nowrap text-xs">{TIPO[r.tipo]}</td>
                <td className="font-mono text-xs" title={r.nota ?? ""}>{r.patron}</td>
                <td>
                  <form action={cambiarRegla} className="flex items-center gap-1">
                    <input type="hidden" name="cliente_id" value={id} />
                    <input type="hidden" name="id" value={r.id} />
                    <input type="hidden" name="q" value={q} />
                    <SelectorCuenta catalogo={catalogo} valor={r.cuenta} />
                    <button className="text-xs text-tenue underline hover:text-acento">Guardar</button>
                  </form>
                </td>
                <td className="text-xs text-tenue">
                  {[r.sentido && `solo ${r.sentido}s`, r.banco && `solo ${r.banco}`].filter(Boolean).join(" · ") || "—"}
                </td>
                <td className="text-right text-xs">{r.tipo === "exacta" ? "—" : r.prioridad}</td>
                <td className="text-xs text-tenue">{ORIGEN[r.origen]}</td>
                <td>
                  <form action={cambiarRegla}>
                    <input type="hidden" name="cliente_id" value={id} />
                    <input type="hidden" name="id" value={r.id} />
                    <input type="hidden" name="q" value={q} />
                    <input type="hidden" name="activa" value={String(!r.activa)} />
                    <button className="text-xs text-tenue underline hover:text-alerta">{r.activa ? "Desactivar" : "Activar"}</button>
                  </form>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}
