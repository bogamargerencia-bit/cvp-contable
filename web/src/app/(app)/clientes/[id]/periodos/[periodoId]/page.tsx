import Link from "next/link";
import { notFound } from "next/navigation";
import { Mensajes } from "@/components/mensajes";
import { Barra } from "@/components/barra";
import { BotonEnviar } from "@/components/boton-enviar";
import { Refresco } from "@/components/refresco";
import { Subida } from "@/components/subida";
import { perfilActual } from "@/lib/sesion";
import { crearClienteServidor } from "@/lib/supabase/server";
import { formatoVE } from "@/lib/montos";
import { MESES, MINUTOS_EN_COLA, ahoraMs, modoDe, nombreBanco, type Cuenta } from "@/lib/tipos";
import { cambiarEstadoPeriodo, guardarSaldos, procesar } from "./actions";

// «Procesar» espera hasta 60 s a que el servicio de Railway despierte (plan serverless).
export const maxDuration = 90;

type Archivo = {
  id: string;
  cuenta_id: string | null;
  tipo: string;
  nombre_original: string;
  tamano: number;
  subido_en: string;
  autor: { nombre: string | null; email: string } | null;
};
type CuentaConvertida = {
  cuenta: string; banco: string; movimientos: number; saldo_anterior: string; debitos: string; creditos: string;
  saldo_final: string; cuadre: string; cuadra: boolean; mensajes: string[];
};
type CuadreCuentas = {
  banco: string; moneda: string; movimientos: number; excluidas: number; creditos: string; debitos: string;
  saldo_inicial: string | null; saldo_calculado: string | null; saldo_final: string | null; diferencia: string | null;
  dias_negativo: number;
};
type ResumenCuentas = {
  archivo: string;
  conteo: { filas: number; regla: number; cliente: number; asignadas: number; sugeridas: number; pendientes: number; excluidas: number };
  cuentas: { cuenta: string; clasificacion: string; grupo: string; movimientos: number; bs: string; usd: string }[];
  cuadres: CuadreCuentas[];
  control: Record<string, [string, string]>;
  hallazgos: { banco: string; filas: string; tipo: string; detalle: string; accion: string }[];
  pendientes_total: number;
};
type Resumen = Partial<ResumenCuentas> & {
  modo?: "conversion" | "cuentas";
  cuentas?: CuentaConvertida[] | ResumenCuentas["cuentas"];
  ok_general: boolean;
  abiertas: number;
  resueltas: number;
  corrida_revision: number;
  bancos: { banco: string; cuadre: string; cuadra: boolean; conciliacion: Record<string, { banco: number; libro: number }> }[];
  situaciones: Record<string, number>;
  alertas: string[];
  advertencias: string[];
  divisas: { cuenta: string; ventas_ok: boolean; nota: string }[];
  uso: { bancos: string[]; divisas: string[]; cierre_caja: boolean; kardex: boolean; revision: boolean };
};
type Corrida = {
  id: string;
  numero: number;
  estado: "pendiente" | "procesando" | "lista" | "error";
  ok_general: boolean | null;
  resumen: Resumen | null;
  excel_path: string | null;
  error: string | null;
  etapa: string | null;
  avance: number;
  creada_en: string;
  terminada_en: string | null;
  autor: { nombre: string | null; email: string } | null;
};

const fecha = (s: string) =>
  new Intl.DateTimeFormat("es-VE", { dateStyle: "short", timeStyle: "short", timeZone: "America/Caracas" }).format(new Date(s));
const tamano = (b: number) => (b < 1024 * 1024 ? `${Math.ceil(b / 1024)} KB` : `${(b / 1024 / 1024).toFixed(1)} MB`);

const ESTADO_CORRIDA: Record<Corrida["estado"], [string, string]> = {
  pendiente: ["en cola", "bg-aviso-suave text-aviso"],
  procesando: ["procesando…", "bg-aviso-suave text-aviso"],
  lista: ["lista", "bg-acento-suave text-acento"],
  error: ["error", "bg-alerta-suave text-alerta"],
};

export default async function Periodo({ params, searchParams }: PageProps<"/clientes/[id]/periodos/[periodoId]">) {
  const { id, periodoId } = await params;
  const { error, ok } = await searchParams;
  const perfil = await perfilActual();
  const supabase = await crearClienteServidor();

  const [{ data: cliente }, { data: periodo }, { data: cuentasD }, { data: archivosD }, { data: corridasD }] = await Promise.all([
    supabase.from("clientes").select("id, nombre, nombre_comercial, config").eq("id", id).maybeSingle(),
    supabase.from("periodos").select("*").eq("id", periodoId).eq("cliente_id", id).maybeSingle(),
    supabase.from("cuentas").select("*").eq("cliente_id", id).eq("activo", true).order("tipo").order("nombre"),
    supabase.from("archivos")
      .select("id, cuenta_id, tipo, nombre_original, tamano, subido_en, autor:perfiles!archivos_subido_por_fkey(nombre, email)")
      .eq("periodo_id", periodoId).eq("vigente", true),
    supabase.from("corridas")
      .select("id, numero, estado, ok_general, resumen, excel_path, error, etapa, avance, creada_en, terminada_en, autor:perfiles!corridas_creada_por_fkey(nombre, email)")
      .eq("periodo_id", periodoId).order("numero", { ascending: false }),
  ]);
  if (!cliente || !periodo) notFound();

  const cuentas = (cuentasD ?? []) as Cuenta[];
  const archivos = (archivosD ?? []) as unknown as Archivo[];
  const corridas = (corridasD ?? []) as unknown as Corrida[];
  const cerrado = periodo.estado === "cerrado";
  const ahora = ahoraMs();
  const atascada = (c: Corrida) =>
    c.estado === "pendiente" && ahora - new Date(c.creada_en).getTime() > MINUTOS_EN_COLA * 60_000;
  const enCurso = corridas.some((c) => (c.estado === "pendiente" && !atascada(c)) || c.estado === "procesando");
  const archivo = (tipo: string, cuentaId: string | null) =>
    archivos.filter((a) => a.tipo === tipo && a.cuenta_id === cuentaId).sort((a, b) => b.subido_en.localeCompare(a.subido_en))[0];

  const ultimaLista = corridas.find((c) => c.estado === "lista");
  const bancos = cuentas.filter((c) => c.tipo === "banco");
  const divisas = cuentas.filter((c) => c.tipo === "divisa");
  // «Solo conversión»: basta el estado de cuenta; no hay libro, caja ni divisas.
  const conversion = modoDe(cliente) === "conversion";
  // «Clasificación por cuenta»: un Excel de movimientos del cliente; sin estados de cuenta ni libro.
  const porCuenta = modoDe(cliente) === "cuentas";
  const movCliente = archivo("movimientos_cliente", null);
  const saldos = (periodo.saldos ?? {}) as Record<string, { inicial: string | null; final: string | null }>;
  const bancosSaldos = Array.from(new Set([
    ...Object.keys(saldos),
    ...((ultimaListaDe(corridas)?.resumen?.cuadres ?? []).map((c) => c.banco)),
  ])).sort();
  const bancosListos = bancos.filter((c) => archivo("estado_cuenta", c.id) && (conversion || archivo("libro_sistema", c.id)));
  const bancosIncompletos = conversion ? [] : bancos.filter(
    (c) => (archivo("estado_cuenta", c.id) || archivo("libro_sistema", c.id)) && !bancosListos.includes(c),
  );
  const puedeProcesar = porCuenta ? !cerrado && !enCurso && !!movCliente
    : !cerrado && !enCurso && bancosListos.length > 0 && bancosIncompletos.length === 0;

  const base = { clienteId: id, periodoId, usuarioId: perfil.id, deshabilitado: cerrado };
  const fila = (etiqueta: string, tipo: string, cuentaId: string | null, ayuda?: string) => {
    const a = archivo(tipo, cuentaId);
    return (
      <div key={`${tipo}-${cuentaId}`} className="flex flex-wrap items-center justify-between gap-2 py-2">
        <div className="min-w-0">
          <span className="text-sm">{etiqueta}</span>
          {a ? (
            <span className="block truncate text-xs text-tenue" title={a.nombre_original}>
              ✓ {a.nombre_original} · {tamano(a.tamano)} · {fecha(a.subido_en)} · {a.autor?.nombre ?? a.autor?.email}
            </span>
          ) : (
            <span className="block text-xs text-tenue">{ayuda ?? "Sin archivo"}</span>
          )}
        </div>
        <Subida {...base} cuentaId={cuentaId} tipo={tipo} reemplaza={!!a} />
      </div>
    );
  };

  return (
    <>
      <Refresco activo={enCurso} cadaMs={2000} />
      <Link href={`/clientes/${id}`} className="text-sm text-tenue hover:text-acento">
        ← {cliente.nombre_comercial ?? cliente.nombre}
      </Link>
      <div className="mt-2 mb-6 flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="titulo">{MESES[periodo.mes - 1]} {periodo.anio}</h1>
          <p className="mt-1 text-sm text-tenue">
            {cliente.nombre_comercial ?? cliente.nombre} ·{" "}
            <span className={`insignia ${cerrado ? "bg-acento-suave text-acento" : "bg-aviso-suave text-aviso"}`}>{periodo.estado}</span>
          </p>
        </div>
        {(!cerrado || perfil.rol === "admin") && (
          <form action={cambiarEstadoPeriodo}>
            <input type="hidden" name="cliente_id" value={id} />
            <input type="hidden" name="periodo_id" value={periodoId} />
            <input type="hidden" name="estado" value={cerrado ? "abierto" : "cerrado"} />
            <button className="boton-sec">{cerrado ? "Reabrir período" : "Cerrar período"}</button>
          </form>
        )}
      </div>
      <Mensajes error={error} ok={ok} />

      <div className="grid gap-8 lg:grid-cols-5">
        {/* ------------------------------------------------ archivos */}
        <section className="space-y-4 lg:col-span-2">
          <h2 className="subtitulo">Archivos del período</h2>
          {porCuenta && (
            <>
              <div className="tarjeta px-4 py-2">
                <p className="pt-1 text-xs font-medium uppercase tracking-wide text-tenue">Del cliente</p>
                <div className="divide-y divide-linea/70">
                  {fila("Excel de movimientos (hoja MOV BANCOS)", "movimientos_cliente", null,
                    "El Excel que envía el cliente con los movimientos de todos sus bancos y cajas")}
                </div>
              </div>
              <form action={guardarSaldos} className="tarjeta space-y-3 p-4">
                <input type="hidden" name="cliente_id" value={id} />
                <input type="hidden" name="periodo_id" value={periodoId} />
                <p className="text-xs font-medium uppercase tracking-wide text-tenue">Saldos según el cliente</p>
                {bancosSaldos.length === 0 ? (
                  <p className="text-sm text-tenue">Procesa una vez para ver los bancos y cajas del archivo; luego carga aquí sus saldos.</p>
                ) : (
                  <table className="tabla">
                    <thead><tr><th>Banco / caja</th><th>Inicial</th><th>Final</th></tr></thead>
                    <tbody>
                      {bancosSaldos.map((b) => (
                        <tr key={b}>
                          <td className="text-sm">{b}</td>
                          <td><input name={`inicial__${b}`} defaultValue={saldos[b]?.inicial ? formatoVE(saldos[b].inicial) : ""}
                            className="campo text-right" inputMode="decimal" placeholder="0,00" disabled={cerrado} /></td>
                          <td><input name={`final__${b}`} defaultValue={saldos[b]?.final ? formatoVE(saldos[b].final) : ""}
                            className="campo text-right" inputMode="decimal" placeholder="0,00" disabled={cerrado} /></td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
                {bancosSaldos.length > 0 && !cerrado && (
                  <div className="flex items-center gap-3">
                    <BotonEnviar texto="Guardar saldos" enviando="Guardando…" />
                    <span className="text-xs text-tenue">Se usan en la próxima corrida para el cuadre de cada banco.</span>
                  </div>
                )}
              </form>
            </>
          )}
          {!porCuenta && cuentas.length === 0 && (
            <p className="tarjeta p-4 text-sm text-tenue">
              El cliente no tiene cuentas. Un administrador debe agregarlas en la ficha del cliente.
            </p>
          )}
          {!porCuenta && bancos.map((c) => (
            <div key={c.id} className="tarjeta px-4 py-2">
              <p className="pt-1 text-xs font-medium uppercase tracking-wide text-tenue">
                {c.nombre} · {nombreBanco(c.banco)}
              </p>
              <div className="divide-y divide-linea/70">
                {fila("Estado de cuenta", "estado_cuenta", c.id, conversion ? "PDF o Excel del banco" : undefined)}
                {!conversion && fila("Libro del sistema", "libro_sistema", c.id, "Mayor analítico o export del banco")}
              </div>
            </div>
          ))}
          {!conversion && !porCuenta && divisas.length > 0 && (
            <div className="tarjeta px-4 py-2">
              <p className="pt-1 text-xs font-medium uppercase tracking-wide text-tenue">Cuentas en divisas (libro en US$)</p>
              <div className="divide-y divide-linea/70">
                {divisas.map((c) => fila(c.nombre, "libro_sistema", c.id))}
              </div>
            </div>
          )}
          {porCuenta ? null : conversion ? (
            <p className="text-xs text-tenue">
              Cliente de <span className="font-medium">solo conversión</span>: se convierten los estados de cuenta a Excel
              con un resumen por ítem, sin libro ni conciliación.
            </p>
          ) : (
          <div className="tarjeta px-4 py-2">
            <p className="pt-1 text-xs font-medium uppercase tracking-wide text-tenue">Del período (opcionales)</p>
            <div className="divide-y divide-linea/70">
              {fila("Cierre de caja (ventas diarias)", "cierre_caja", null)}
              {fila("Kardex de tesorería", "kardex", null, "Solo si hay cuentas en divisas")}
              {fila("Excel de revisión con decisiones", "revision", null, "El Excel de la corrida anterior, corregido por el analista")}
            </div>
          </div>
          )}
        </section>

        {/* ------------------------------------------------ procesar y corridas */}
        <section className="space-y-4 lg:col-span-3">
          <h2 className="subtitulo">Procesar</h2>
          <div className="tarjeta p-4">
            <ul className="mb-4 space-y-1 text-sm">
              {porCuenta && (
                <li className={movCliente ? "" : "text-tenue"}>
                  {movCliente ? "✓ Excel de movimientos del cliente" : "– Falta el Excel de movimientos del cliente"}
                </li>
              )}
              {!porCuenta && bancos.map((c) => {
                const listo = bancosListos.includes(c);
                const parcial = bancosIncompletos.includes(c);
                return (
                  <li key={c.id} className={listo ? "" : parcial ? "text-alerta" : "text-tenue"}>
                    {listo ? "✓" : parcial ? "✗" : "–"} {c.nombre}
                    {parcial && " — falta " + (archivo("estado_cuenta", c.id) ? "el libro del sistema" : "el estado de cuenta")}
                    {!listo && !parcial && (conversion ? " — sin estado de cuenta (no se procesa)" : " — sin archivos (no se procesa)")}
                  </li>
                );
              })}
            </ul>
            <form action={procesar} className="flex flex-wrap items-center gap-3">
              <input type="hidden" name="cliente_id" value={id} />
              <input type="hidden" name="periodo_id" value={periodoId} />
              <BotonEnviar texto="Procesar" enviando="Enviando…" deshabilitado={!puedeProcesar} />
              <span className="text-xs text-tenue">
                {cerrado ? "Período cerrado." : enCurso ? "Hay una corrida en proceso…"
                  : porCuenta ? (movCliente ? "Clasifica con las reglas del cliente y lo decidido en «Clasificar»." : "Sube el Excel del cliente.")
                  : bancosIncompletos.length ? "Completa o quita los archivos marcados con ✗."
                  : bancosListos.length === 0 ? (conversion ? "Sube al menos un estado de cuenta." : "Sube al menos un estado de cuenta con su libro.")
                  : "Usa los archivos vigentes de la izquierda."}
              </span>
            </form>
          </div>

          {ultimaLista && porCuenta && (
            <div className="tarjeta flex flex-wrap items-center justify-between gap-3 p-4">
              <div className="text-sm">
                <p className="font-medium">Clasificación de la corrida {ultimaLista.numero}</p>
                <p className="text-tenue">
                  {ultimaLista.ok_general ? "OK general: todo clasificado y los saldos cuadran."
                    : `${ultimaLista.resumen?.pendientes_total ?? 0} movimientos por clasificar o confirmar.`}
                </p>
              </div>
              <Link href={`/clientes/${id}/periodos/${periodoId}/clasificar`} className="boton">Clasificar</Link>
            </div>
          )}

          {ultimaLista && !conversion && !porCuenta && (
            <div className="tarjeta flex flex-wrap items-center justify-between gap-3 p-4">
              <div className="text-sm">
                <p className="font-medium">Revisión de la corrida {ultimaLista.numero}</p>
                <p className="text-tenue">
                  {ultimaLista.ok_general ? "OK general: no quedan partidas abiertas."
                    : `${ultimaLista.resumen?.abiertas ?? 0} partidas abiertas. Decide cada una en línea (o con el Excel).`}
                </p>
              </div>
              <Link href={`/clientes/${id}/periodos/${periodoId}/revision`} className="boton">Revisar en línea</Link>
            </div>
          )}

          <h2 className="subtitulo pt-2">Corridas</h2>
          {corridas.length === 0 ? (
            <p className="tarjeta p-4 text-sm text-tenue">Todavía no se ha procesado este período.</p>
          ) : (
            corridas.map((c) => <TarjetaCorrida key={c.id} c={c} atascada={atascada(c)} />)
          )}
        </section>
      </div>
    </>
  );
}

function TarjetaCorrida({ c, atascada }: { c: Corrida; atascada: boolean }) {
  const [txt, cls] = ESTADO_CORRIDA[c.estado];
  const r = c.resumen;
  return (
    <div className="tarjeta p-4">
      <div className="flex flex-wrap items-center gap-3">
        <span className="font-serif text-lg font-semibold">Corrida {c.numero}</span>
        <span className={`insignia ${cls}`}>{txt}</span>
        {c.estado === "lista" && (
          <span className={`insignia ${c.ok_general ? "bg-acento text-white" : "bg-aviso-suave text-aviso"}`}>
            {c.ok_general ? "OK general" : `${r?.abiertas ?? 0} pendientes`}
          </span>
        )}
        <span className="text-xs text-tenue">{fecha(c.creada_en)} · {c.autor?.nombre ?? c.autor?.email}</span>
        {c.excel_path && (
          <a href={`/descargar/${c.id}`} className="boton-sec ml-auto">Descargar Excel</a>
        )}
      </div>
      {(c.estado === "pendiente" && !atascada) && (
        <div className="mt-3 space-y-2">
          <Barra etiqueta="En cola: esperando al servicio de procesamiento…" />
        </div>
      )}
      {c.estado === "procesando" && (
        <div className="mt-3 space-y-2">
          <Barra valor={c.avance} etiqueta={c.etapa ?? "Procesando…"} />
          <p className="text-xs text-tenue">
            El proceso corre en el servidor: puedes cerrar esta página y volver luego; no se interrumpe.
          </p>
        </div>
      )}
      {c.error && <p className="msg-error mt-3">{c.error}</p>}
      {atascada && (
        <p className="msg-error mt-3">
          Lleva más de {MINUTOS_EN_COLA} minutos en cola: el servicio no la tomó. Pulsa «Procesar» para intentarlo de nuevo.
        </p>
      )}
      {r?.modo === "conversion" && <ResumenConversion r={r} />}
      {r?.modo === "cuentas" && <ResumenPorCuenta r={r as unknown as ResumenCuentas} />}
      {r && r.modo !== "conversion" && r.modo !== "cuentas" && (
        <div className="mt-3 space-y-3 text-sm">
          <table className="tabla">
            <thead>
              <tr><th>Banco</th><th>Estado de cuenta</th><th className="text-right">Conciliados (banco / libro)</th><th className="text-right">Sin pareja</th></tr>
            </thead>
            <tbody>
              {r.bancos.map((b) => {
                const conc = Object.entries(b.conciliacion);
                const ok = conc.filter(([k]) => k.startsWith("Conciliado"));
                const sumar = (l: [string, { banco: number; libro: number }][], k: "banco" | "libro") => l.reduce((s, [, v]) => s + v[k], 0);
                const resto = conc.filter(([k]) => !k.startsWith("Conciliado"));
                return (
                  <tr key={b.banco}>
                    <td>{nombreBanco(b.banco)}</td>
                    <td className={b.cuadra ? "text-acento" : "font-medium text-alerta"}>{b.cuadre}</td>
                    <td className="text-right">{sumar(ok, "banco")} / {sumar(ok, "libro")}</td>
                    <td className="text-right" title={resto.map(([k, v]) => `${k}: ${v.banco} banco, ${v.libro} libro`).join("\n")}>
                      {sumar(resto, "banco") + sumar(resto, "libro")}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          {r.divisas.length > 0 && (
            <p className="text-tenue">
              Divisas: {r.divisas.map((d) => `${d.cuenta} ${d.ventas_ok ? "✓" : "✗"}`).join(" · ")}
            </p>
          )}
          {Object.keys(r.situaciones).length > 0 && (
            <p className="text-tenue">
              Revisión: {Object.entries(r.situaciones).map(([k, v]) => `${k}: ${v}`).join(" · ")}
              {r.resueltas > 0 && ` · resueltas desde la corrida anterior: ${r.resueltas}`}
            </p>
          )}
          {(r.alertas.length > 0 || r.advertencias.length > 0) && (
            <details>
              <summary className="cursor-pointer text-sm font-medium">
                Alertas ({r.alertas.length + r.advertencias.length})
              </summary>
              <ul className="mt-2 list-disc space-y-1 pl-5 text-xs">
                {[...r.advertencias, ...r.alertas].map((a, i) => <li key={i}>{a}</li>)}
              </ul>
            </details>
          )}
        </div>
      )}
    </div>
  );
}

/** Resultado de una corrida de «Solo conversión»: cuadre de cada estado de cuenta (montos como texto exacto). */
function ResumenConversion({ r }: { r: Resumen }) {
  const cuentas = (r.cuentas ?? []) as unknown as CuentaConvertida[];
  return (
    <div className="mt-3 space-y-3 text-sm">
      <div className="overflow-x-auto">
        <table className="tabla">
          <thead>
            <tr><th>Cuenta</th><th className="text-right">Mov.</th><th className="text-right">Débitos (Bs.)</th>
              <th className="text-right">Créditos (Bs.)</th><th className="text-right">Saldo final (Bs.)</th><th>Cuadre</th></tr>
          </thead>
          <tbody>
            {cuentas.map((c) => (
              <tr key={c.cuenta}>
                <td>{c.cuenta}<span className="block text-xs text-tenue">{nombreBanco(c.banco)}</span></td>
                <td className="text-right">{c.movimientos}</td>
                <td className="text-right whitespace-nowrap">{formatoVE(c.debitos)}</td>
                <td className="text-right whitespace-nowrap">{formatoVE(c.creditos)}</td>
                <td className="text-right whitespace-nowrap">{formatoVE(c.saldo_final)}</td>
                <td className={c.cuadra ? "text-acento" : "font-medium text-alerta"}>
                  {c.cuadre === "cuadra" ? "Cuadra" : c.cuadre === "requiere_revision" ? "Cuadra (revisar avisos)" : "NO CUADRA"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {cuentas.some((c) => c.mensajes.length > 0) || r.advertencias.length > 0 ? (
        <details>
          <summary className="cursor-pointer text-sm font-medium">Diferencias y avisos</summary>
          <ul className="mt-2 list-disc space-y-1 pl-5 text-xs">
            {r.advertencias.map((a, i) => <li key={`a${i}`}>{a}</li>)}
            {cuentas.flatMap((c) => c.mensajes.map((m, i) => <li key={`${c.cuenta}${i}`}>{c.cuenta}: {m}</li>))}
          </ul>
        </details>
      ) : null}
      <p className="text-xs text-tenue">El Excel trae una hoja por cuenta y el «Resumen por ítem» (naturaleza y concepto).</p>
    </div>
  );
}

function ultimaListaDe(corridas: Corrida[]) {
  return corridas.find((c) => c.estado === "lista" && c.resumen?.modo === "cuentas");
}

/** Resultado de una corrida de «Clasificación por cuenta»: conteos, cuadre por banco y controles. */
function ResumenPorCuenta({ r }: { r: ResumenCuentas }) {
  const n = r.conteo;
  const diferencia = (c: CuadreCuentas) =>
    c.saldo_inicial == null ? "Falta saldo inicial" : c.saldo_final == null ? "Falta saldo final"
      : c.diferencia && !/^-?0(\.0+)?$/.test(c.diferencia) ? `Diferencia ${formatoVE(c.diferencia)}` : "Cuadra";
  const avisos = r.hallazgos.filter((h) => h.tipo !== "CUENTA 2 (del cliente)");
  return (
    <div className="mt-3 space-y-3 text-sm">
      <p className="text-tenue">
        {r.archivo}: {n.filas} movimientos · {n.regla + n.cliente + n.asignadas} clasificados
        {n.sugeridas > 0 && ` · ${n.sugeridas} sugeridos (confirmar)`}
        {n.pendientes > 0 && <span className="font-medium text-alerta"> · {n.pendientes} por clasificar</span>}
        {n.excluidas > 0 && ` · ${n.excluidas} excluidos`}
      </p>
      <div className="overflow-x-auto">
        <table className="tabla">
          <thead>
            <tr><th>Banco / caja</th><th className="text-right">Mov.</th><th className="text-right">Saldo inicial</th>
              <th className="text-right">Saldo calculado</th><th className="text-right">Saldo del cliente</th><th>Cuadre</th></tr>
          </thead>
          <tbody>
            {r.cuadres.map((c) => {
              const d = diferencia(c);
              return (
                <tr key={c.banco}>
                  <td>{c.banco}<span className="block text-xs text-tenue">{c.moneda}{c.excluidas ? ` · ${c.excluidas} excluidos` : ""}</span></td>
                  <td className="text-right">{c.movimientos}</td>
                  <td className="text-right whitespace-nowrap">{formatoVE(c.saldo_inicial)}</td>
                  <td className="text-right whitespace-nowrap">{formatoVE(c.saldo_calculado)}</td>
                  <td className="text-right whitespace-nowrap">{formatoVE(c.saldo_final)}</td>
                  <td className={d === "Cuadra" ? "text-acento" : d.startsWith("Diferencia") ? "font-medium text-alerta" : "text-tenue"}>
                    {d}{c.dias_negativo > 0 && <span className="block text-xs text-alerta">{c.dias_negativo} día(s) en negativo</span>}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {Object.entries(r.control).some(([, [a, b]]) => a !== b) && (
        <p className="msg-error">Control: lo clasificado no suma lo mismo que el archivo. Revisa el Excel.</p>
      )}
      {avisos.length > 0 && (
        <details>
          <summary className="cursor-pointer text-sm font-medium">Hallazgos ({avisos.length})</summary>
          <ul className="mt-2 list-disc space-y-1 pl-5 text-xs">
            {avisos.map((h, i) => <li key={i}><span className="font-medium">{h.banco} · filas {h.filas}:</span> {h.detalle} {h.accion}</li>)}
          </ul>
        </details>
      )}
      <p className="text-xs text-tenue">El Excel trae el resumen por cuenta, los hallazgos, el cuadre de cada banco y una hoja por cuenta.</p>
    </div>
  );
}
