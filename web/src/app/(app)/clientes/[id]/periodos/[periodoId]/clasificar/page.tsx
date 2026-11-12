import Link from "next/link";
import { notFound } from "next/navigation";
import { BotonEnviar } from "@/components/boton-enviar";
import { Mensajes } from "@/components/mensajes";
import { crearClienteServidor } from "@/lib/supabase/server";
import { formatoVE } from "@/lib/montos";
import { MESES, type CuentaCatalogo } from "@/lib/tipos";
import { procesar } from "../actions";
import { asignar, quitarAsignacion } from "./actions";

type Pendiente = {
  clave: string;
  fila: number;
  fecha: string | null;
  banco: string;
  descripcion: string;
  patron: string;
  monto: string;          // texto exacto (Decimal del parser), nunca number
  moneda: string;
  estado: string;         // "Por clasificar" o "Sugerido (parecido)"
  sugerida: string | null;
  criterio: string;
};
type Asignacion = {
  clave: string;
  cuenta: string | null;
  excluir: boolean;
  regla_id: string | null;
  asignada_en: string;
  autor: { nombre: string | null; email: string } | null;
};

const fechaCorta = (s: string | null) => (s ? `${s.slice(8, 10)}/${s.slice(5, 7)}` : "—");
const uno = (v: string | string[] | undefined) => (Array.isArray(v) ? v[0] : v);

export default async function Clasificar({ params, searchParams }: PageProps<"/clientes/[id]/periodos/[periodoId]/clasificar">) {
  const { id, periodoId } = await params;
  const sp = await searchParams;
  const error = uno(sp.error);
  const ok = uno(sp.ok);
  const vista = uno(sp.vista) === "todas" ? "todas" : "pendientes";
  const supabase = await crearClienteServidor();

  const [{ data: cliente }, { data: periodo }, { data: corridas }, { data: asignD }] = await Promise.all([
    supabase.from("clientes").select("id, nombre, nombre_comercial, config").eq("id", id).maybeSingle(),
    supabase.from("periodos").select("id, anio, mes, estado").eq("id", periodoId).eq("cliente_id", id).maybeSingle(),
    supabase.from("corridas").select("id, numero, resumen, estado").eq("periodo_id", periodoId).eq("estado", "lista")
      .order("numero", { ascending: false }).limit(1),
    supabase.from("asignaciones_cuenta")
      .select("clave, cuenta, excluir, regla_id, asignada_en, autor:perfiles!asignaciones_cuenta_asignada_por_fkey(nombre, email)")
      .eq("periodo_id", periodoId),
  ]);
  if (!cliente || !periodo) notFound();
  const catalogo = ((cliente.config as { catalogo?: CuentaCatalogo[] } | null)?.catalogo ?? []);
  const corrida = corridas?.[0];
  const resumen = corrida?.resumen as { modo?: string; pendientes?: Pendiente[]; pendientes_total?: number } | null;
  const pendientes = resumen?.modo === "cuentas" ? resumen.pendientes ?? [] : [];
  const asignadas = new Map(((asignD ?? []) as unknown as Asignacion[]).map((a) => [a.clave, a]));
  const cerrado = periodo.estado === "cerrado";
  const sinDecidir = pendientes.filter((p) => !asignadas.has(p.clave));
  const lista = vista === "todas" ? pendientes : sinDecidir;
  const grupos = Array.from(new Set(catalogo.map((c) => c.grupo ?? "")));
  const base = `/clientes/${id}/periodos/${periodoId}/clasificar`;
  const nombre = cliente.nombre_comercial ?? cliente.nombre;

  return (
    <>
      <Link href={`/clientes/${id}/periodos/${periodoId}`} className="text-sm text-tenue hover:text-acento">
        ← {nombre} · {MESES[periodo.mes - 1]} {periodo.anio}
      </Link>
      <div className="mt-2 mb-4 flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="titulo">Clasificar</h1>
          <p className="mt-1 text-sm text-tenue">
            {corrida ? `Corrida ${corrida.numero}: ${resumen?.pendientes_total ?? 0} movimientos por clasificar o confirmar · `
              + `${pendientes.length - sinDecidir.length} ya decididos (se aplican al volver a procesar).`
              : "Todavía no hay una corrida terminada."}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Link href={`/clientes/${id}/reglas`} className="boton-sec">Reglas del cliente</Link>
          {!cerrado && corrida && (
            <form action={procesar}>
              <input type="hidden" name="cliente_id" value={id} />
              <input type="hidden" name="periodo_id" value={periodoId} />
              <BotonEnviar texto="Procesar de nuevo" enviando="Enviando…" />
            </form>
          )}
        </div>
      </div>
      <Mensajes error={error} ok={ok} />
      {catalogo.length === 0 && (
        <p className="msg-error mb-4">El cliente no tiene catálogo de cuentas: un administrador debe cargarlo.</p>
      )}

      <div className="mb-3 flex gap-2 text-sm">
        {(["pendientes", "todas"] as const).map((v) => (
          <Link key={v} href={`${base}?vista=${v}`}
            className={`insignia ${vista === v ? "bg-acento text-white" : "bg-acento-suave text-acento"}`}>
            {v === "pendientes" ? `Sin decidir (${sinDecidir.length})` : `Todos (${pendientes.length})`}
          </Link>
        ))}
      </div>
      <p className="mb-4 text-xs text-tenue">
        Amarillo: ninguna regla la reconoce. Naranja: se parece a una descripción conocida (confirmar). «Recordar» crea la
        regla para los próximos meses: los movimientos con la misma descripción se clasifican solos al volver a procesar.
      </p>

      {lista.length === 0 ? (
        <p className="tarjeta p-4 text-sm">
          {pendientes.length === 0 ? "No hay nada por clasificar en la última corrida." : "Todo decidido: vuelve a procesar para aplicarlo."}
        </p>
      ) : (
        <div className="space-y-2">
          {lista.map((p) => {
            const a = asignadas.get(p.clave);
            const sugerido = p.estado.startsWith("Sugerido");
            const aMano = p.criterio.toLowerCase().includes("a mano") || p.criterio.startsWith("Revisar");
            return (
              <div key={p.clave} id={`f${p.fila}`}
                className={`tarjeta p-3 ${a ? "" : sugerido ? "border-l-4 border-l-alerta-suave" : "border-l-4 border-l-aviso"}`}>
                <div className="flex flex-wrap items-baseline justify-between gap-2 text-sm">
                  <span className="font-medium">{p.descripcion || <em className="text-tenue">(sin descripción)</em>}</span>
                  <span className={`whitespace-nowrap font-medium ${p.monto.startsWith("-") ? "text-alerta" : "text-acento"}`}>
                    {p.moneda} {formatoVE(p.monto)}
                  </span>
                </div>
                <p className="text-xs text-tenue">
                  {p.banco} · {fechaCorta(p.fecha)} · fila {p.fila} · {p.criterio}
                </p>
                {a ? (
                  <form action={quitarAsignacion} className="mt-2 flex flex-wrap items-center gap-3 text-sm">
                    <input type="hidden" name="cliente_id" value={id} />
                    <input type="hidden" name="periodo_id" value={periodoId} />
                    <input type="hidden" name="clave" value={p.clave} />
                    <span className="insignia bg-acento-suave text-acento">
                      {a.excluir ? "Excluir" : a.cuenta}{a.regla_id && " · recordada"}
                    </span>
                    <span className="text-xs text-tenue">{a.autor?.nombre ?? a.autor?.email}</span>
                    {!cerrado && <button className="text-xs text-tenue underline hover:text-alerta">Quitar</button>}
                  </form>
                ) : !cerrado && (
                  <form action={asignar} className="mt-2 flex flex-wrap items-center gap-2 text-sm">
                    <input type="hidden" name="cliente_id" value={id} />
                    <input type="hidden" name="periodo_id" value={periodoId} />
                    <input type="hidden" name="clave" value={p.clave} />
                    <input type="hidden" name="patron" value={p.patron} />
                    <input type="hidden" name="fila" value={p.fila} />
                    <select name="cuenta" defaultValue={p.sugerida ?? ""} className="campo w-auto min-w-64">
                      <option value="">— Cuenta —</option>
                      {grupos.map((g) => (
                        <optgroup key={g} label={g || "Cuentas"}>
                          {catalogo.filter((c) => (c.grupo ?? "") === g).map((c) => (
                            <option key={c.cuenta} value={c.cuenta}>{c.cuenta}</option>
                          ))}
                        </optgroup>
                      ))}
                    </select>
                    <label className="flex items-center gap-1 text-xs" title="Crea la regla «descripción exacta → cuenta»">
                      <input type="checkbox" name="recordar" defaultChecked={!aMano && !!p.patron} disabled={!p.patron} />
                      Recordar
                    </label>
                    <button name="accion" value="asignar" className="boton">{sugerido ? "Confirmar" : "Asignar"}</button>
                    <button name="accion" value="excluir" className="boton-sec"
                      title="Fila repetida o que no corresponde: no suma en el resumen ni en el cuadre">Excluir</button>
                  </form>
                )}
              </div>
            );
          })}
        </div>
      )}
    </>
  );
}
