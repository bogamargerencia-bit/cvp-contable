import Link from "next/link";
import { notFound } from "next/navigation";
import { Mensajes } from "@/components/mensajes";
import { Refresco } from "@/components/refresco";
import { Subida } from "@/components/subida";
import { perfilActual } from "@/lib/sesion";
import { crearClienteServidor } from "@/lib/supabase/server";
import { MESES, nombreBanco, type Cuenta } from "@/lib/tipos";
import { cambiarEstadoPeriodo, procesar } from "./actions";

type Archivo = {
  id: string;
  cuenta_id: string | null;
  tipo: string;
  nombre_original: string;
  tamano: number;
  subido_en: string;
  autor: { nombre: string | null; email: string } | null;
};
type Resumen = {
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
    supabase.from("clientes").select("id, nombre, nombre_comercial").eq("id", id).maybeSingle(),
    supabase.from("periodos").select("*").eq("id", periodoId).eq("cliente_id", id).maybeSingle(),
    supabase.from("cuentas").select("*").eq("cliente_id", id).eq("activo", true).order("tipo").order("nombre"),
    supabase.from("archivos")
      .select("id, cuenta_id, tipo, nombre_original, tamano, subido_en, autor:perfiles!archivos_subido_por_fkey(nombre, email)")
      .eq("periodo_id", periodoId).eq("vigente", true),
    supabase.from("corridas")
      .select("id, numero, estado, ok_general, resumen, excel_path, error, creada_en, terminada_en, autor:perfiles!corridas_creada_por_fkey(nombre, email)")
      .eq("periodo_id", periodoId).order("numero", { ascending: false }),
  ]);
  if (!cliente || !periodo) notFound();

  const cuentas = (cuentasD ?? []) as Cuenta[];
  const archivos = (archivosD ?? []) as unknown as Archivo[];
  const corridas = (corridasD ?? []) as unknown as Corrida[];
  const cerrado = periodo.estado === "cerrado";
  const enCurso = corridas.some((c) => c.estado === "pendiente" || c.estado === "procesando");
  const archivo = (tipo: string, cuentaId: string | null) =>
    archivos.filter((a) => a.tipo === tipo && a.cuenta_id === cuentaId).sort((a, b) => b.subido_en.localeCompare(a.subido_en))[0];

  const bancos = cuentas.filter((c) => c.tipo === "banco");
  const divisas = cuentas.filter((c) => c.tipo === "divisa");
  const bancosListos = bancos.filter((c) => archivo("estado_cuenta", c.id) && archivo("libro_sistema", c.id));
  const bancosIncompletos = bancos.filter(
    (c) => (archivo("estado_cuenta", c.id) || archivo("libro_sistema", c.id)) && !bancosListos.includes(c),
  );
  const puedeProcesar = !cerrado && !enCurso && bancosListos.length > 0 && bancosIncompletos.length === 0;

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
      <Refresco activo={enCurso} />
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
          {cuentas.length === 0 && (
            <p className="tarjeta p-4 text-sm text-tenue">
              El cliente no tiene cuentas. Un administrador debe agregarlas en la ficha del cliente.
            </p>
          )}
          {bancos.map((c) => (
            <div key={c.id} className="tarjeta px-4 py-2">
              <p className="pt-1 text-xs font-medium uppercase tracking-wide text-tenue">
                {c.nombre} · {nombreBanco(c.banco)}
              </p>
              <div className="divide-y divide-linea/70">
                {fila("Estado de cuenta", "estado_cuenta", c.id)}
                {fila("Libro del sistema", "libro_sistema", c.id, "Mayor analítico o export del banco")}
              </div>
            </div>
          ))}
          {divisas.length > 0 && (
            <div className="tarjeta px-4 py-2">
              <p className="pt-1 text-xs font-medium uppercase tracking-wide text-tenue">Cuentas en divisas (libro en US$)</p>
              <div className="divide-y divide-linea/70">
                {divisas.map((c) => fila(c.nombre, "libro_sistema", c.id))}
              </div>
            </div>
          )}
          <div className="tarjeta px-4 py-2">
            <p className="pt-1 text-xs font-medium uppercase tracking-wide text-tenue">Del período (opcionales)</p>
            <div className="divide-y divide-linea/70">
              {fila("Cierre de caja (ventas diarias)", "cierre_caja", null)}
              {fila("Kardex de tesorería", "kardex", null, "Solo si hay cuentas en divisas")}
              {fila("Excel de revisión con decisiones", "revision", null, "El Excel de la corrida anterior, corregido por el analista")}
            </div>
          </div>
        </section>

        {/* ------------------------------------------------ procesar y corridas */}
        <section className="space-y-4 lg:col-span-3">
          <h2 className="subtitulo">Procesar</h2>
          <div className="tarjeta p-4">
            <ul className="mb-4 space-y-1 text-sm">
              {bancos.map((c) => {
                const listo = bancosListos.includes(c);
                const parcial = bancosIncompletos.includes(c);
                return (
                  <li key={c.id} className={listo ? "" : parcial ? "text-alerta" : "text-tenue"}>
                    {listo ? "✓" : parcial ? "✗" : "–"} {c.nombre}
                    {parcial && " — falta " + (archivo("estado_cuenta", c.id) ? "el libro del sistema" : "el estado de cuenta")}
                    {!listo && !parcial && " — sin archivos (no se procesa)"}
                  </li>
                );
              })}
            </ul>
            <form action={procesar} className="flex flex-wrap items-center gap-3">
              <input type="hidden" name="cliente_id" value={id} />
              <input type="hidden" name="periodo_id" value={periodoId} />
              <button className="boton" disabled={!puedeProcesar}>Procesar</button>
              <span className="text-xs text-tenue">
                {cerrado ? "Período cerrado." : enCurso ? "Hay una corrida en proceso…"
                  : bancosIncompletos.length ? "Completa o quita los archivos marcados con ✗."
                  : bancosListos.length === 0 ? "Sube al menos un estado de cuenta con su libro." : "Usa los archivos vigentes de la izquierda."}
              </span>
            </form>
          </div>

          <h2 className="subtitulo pt-2">Corridas</h2>
          {corridas.length === 0 ? (
            <p className="tarjeta p-4 text-sm text-tenue">Todavía no se ha procesado este período.</p>
          ) : (
            corridas.map((c) => <TarjetaCorrida key={c.id} c={c} />)
          )}
        </section>
      </div>
    </>
  );
}

function TarjetaCorrida({ c }: { c: Corrida }) {
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
      {c.error && <p className="msg-error mt-3">{c.error}</p>}
      {r && (
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
