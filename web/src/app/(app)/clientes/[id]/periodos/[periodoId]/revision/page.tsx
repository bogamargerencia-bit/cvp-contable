import Link from "next/link";
import { notFound } from "next/navigation";
import { Decision } from "@/components/decision";
import { perfilActual } from "@/lib/sesion";
import { crearClienteServidor } from "@/lib/supabase/server";
import { formatoVE } from "@/lib/montos";
import { ABIERTAS, DECIDIDA } from "@/lib/revision";
import { MESES, nombreBanco } from "@/lib/tipos";

type Partida = {
  codigo: string;
  banco: string | null;
  origen: string;
  tipo: string;
  fecha: string | null;
  descripcion: string | null;
  monto_bs: string | null;      // numeric::text — nunca number
  monto_usd: string | null;
  detalle: string | null;
  sugerencia: string | null;
  explicacion: string | null;
  que_hacer: string | null;
  situacion: string;
  aviso: string | null;
  propuesta: { fila: number; fecha: string } | null;
};
type Decidida = {
  codigo: string;
  decision: string;
  comentario: string | null;
  decidido_en: string;
  autor: { nombre: string | null; email: string } | null;
};

const VISTAS = [
  ["pendientes", "Pendientes"],
  ["decididas", "Decididas sin aplicar"],
  ["cerradas", "Cerradas"],
  ["todas", "Todas"],
] as const;
type Vista = (typeof VISTAS)[number][0];

const ORDEN: Record<string, number> = {
  "Marcado como corregido, pero sigue igual": 0, "Decisión incompleta": 1, Nuevo: 2, "Sin decisión": 3,
  [DECIDIDA]: 4, Cerrado: 5,
};
const COLOR: Record<string, string> = {
  "Marcado como corregido, pero sigue igual": "bg-alerta-suave text-alerta",
  "Decisión incompleta": "bg-aviso-suave text-aviso",
  Nuevo: "bg-aviso-suave text-aviso",
  "Sin decisión": "bg-aviso-suave text-aviso",
  [DECIDIDA]: "bg-acento-suave text-acento",
  Cerrado: "bg-acento text-white",
};

const fechaHora = (s: string) =>
  new Intl.DateTimeFormat("es-VE", { dateStyle: "short", timeStyle: "short", timeZone: "America/Caracas" }).format(new Date(s));
const fechaCorta = (s: string) => `${s.slice(8, 10)}/${s.slice(5, 7)}/${s.slice(0, 4)}`;
const uno = (v: string | string[] | undefined) => (Array.isArray(v) ? v[0] : v);

export default async function Revision({ params, searchParams }: PageProps<"/clientes/[id]/periodos/[periodoId]/revision">) {
  const { id, periodoId } = await params;
  const sp = await searchParams;
  const vista = (VISTAS.find(([k]) => k === uno(sp.ver))?.[0] ?? "pendientes") as Vista;
  const banco = uno(sp.banco) ?? "";
  await perfilActual();
  const supabase = await crearClienteServidor();

  const [{ data: cliente }, { data: periodo }, { data: corridaD }] = await Promise.all([
    supabase.from("clientes").select("id, nombre, nombre_comercial").eq("id", id).maybeSingle(),
    supabase.from("periodos").select("id, anio, mes, estado").eq("id", periodoId).eq("cliente_id", id).maybeSingle(),
    supabase.from("corridas").select("id, numero, ok_general, terminada_en, resumen")
      .eq("periodo_id", periodoId).eq("estado", "lista").order("numero", { ascending: false }).limit(1),
  ]);
  if (!cliente || !periodo) notFound();
  const corrida = corridaD?.[0];
  const volver = `/clientes/${id}/periodos/${periodoId}`;
  const titulo = `${MESES[periodo.mes - 1]} ${periodo.anio} · ${cliente.nombre_comercial ?? cliente.nombre}`;

  if (!corrida) {
    return (
      <>
        <Link href={volver} className="text-sm text-tenue hover:text-acento">← {titulo}</Link>
        <h1 className="titulo mt-2 mb-6">Revisión</h1>
        <p className="tarjeta p-4 text-sm text-tenue">Todavía no hay ninguna corrida terminada en este período. Procesa primero.</p>
      </>
    );
  }

  const [{ data: partidasD }, { data: decisionesD }] = await Promise.all([
    supabase.from("partidas")
      .select("codigo, banco, origen, tipo, fecha, descripcion, monto_bs::text, monto_usd::text, detalle, sugerencia, explicacion, que_hacer, situacion, aviso, propuesta")
      .eq("corrida_id", corrida.id),
    supabase.from("decisiones")
      .select("codigo, decision, comentario, decidido_en, autor:perfiles!decisiones_revisado_por_fkey(nombre, email)")
      .eq("periodo_id", periodoId).eq("vigente", true),
  ]);
  const partidas = (partidasD ?? []) as unknown as Partida[];
  const decisiones = new Map(((decisionesD ?? []) as unknown as Decidida[]).map((d) => [d.codigo, d]));
  const terminada = corrida.terminada_en ? new Date(corrida.terminada_en).getTime() : 0;
  const nueva = (c: string) => {
    const d = decisiones.get(c);
    return d && new Date(d.decidido_en).getTime() > terminada ? d : undefined;
  };
  // Situación en pantalla: la de la corrida, salvo que haya una decisión registrada después de ella.
  const situacion = (p: Partida) => (nueva(p.codigo) ? DECIDIDA : p.situacion);
  const enVista = (p: Partida) => {
    const s = situacion(p);
    return vista === "todas" ? true : vista === "pendientes" ? ABIERTAS.includes(s)
      : vista === "decididas" ? s === DECIDIDA : s === "Cerrado";
  };
  const cuenta = {
    pendientes: partidas.filter((p) => ABIERTAS.includes(situacion(p))).length,
    decididas: partidas.filter((p) => situacion(p) === DECIDIDA).length,
    cerradas: partidas.filter((p) => situacion(p) === "Cerrado").length,
    todas: partidas.length,
  };
  const bancos = [...new Set(partidas.map((p) => p.banco ?? ""))].sort();
  const lista = partidas
    .filter((p) => enVista(p) && (!banco || p.banco === banco))
    .sort((a, b) => (ORDEN[situacion(a)] ?? 9) - (ORDEN[situacion(b)] ?? 9)
      || (a.banco ?? "").localeCompare(b.banco ?? "") || a.tipo.localeCompare(b.tipo)
      || (a.fecha ?? "").localeCompare(b.fecha ?? ""));
  const cerrado = periodo.estado === "cerrado";
  const noCuadran: string[] = corrida.resumen?.bancos_no_cuadran ?? [];
  const url = (v: string, b: string) => `?ver=${v}${b ? `&banco=${encodeURIComponent(b)}` : ""}`;

  return (
    <>
      <Link href={volver} className="text-sm text-tenue hover:text-acento">← {titulo}</Link>
      <div className="mt-2 mb-4 flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="titulo">Revisión · corrida {corrida.numero}</h1>
          <p className="mt-1 text-sm text-tenue">
            {corrida.terminada_en && `Procesada ${fechaHora(corrida.terminada_en)} · `}
            {corrida.ok_general
              ? <span className="insignia bg-acento text-white">OK general</span>
              : <span className="insignia bg-aviso-suave text-aviso">{cuenta.pendientes} pendientes</span>}
            {cerrado && <span className="insignia ml-2 bg-acento-suave text-acento">período cerrado</span>}
          </p>
        </div>
        <a href={`/descargar/${corrida.id}`} className="boton-sec">Descargar Excel</a>
      </div>

      {noCuadran.length > 0 && (
        <p className="msg-error mb-4">
          No cuadra el estado de cuenta de: {noCuadran.map(nombreBanco).join(", ")}. Mientras no cuadre, no habrá OK general
          aunque todas las partidas estén decididas.
        </p>
      )}
      {cuenta.decididas > 0 && !cerrado && (
        <p className="msg-ok mb-4">
          Hay {cuenta.decididas} decisión(es) registradas después de esta corrida. Para aplicarlas (y ver si queda OK general),
          vuelve al período y pulsa <Link href={volver} className="font-medium underline">Procesar</Link>.
        </p>
      )}
      <p className="mb-4 text-sm text-tenue">
        Lee la explicación y «qué hacer» de cada partida y elige una decisión. «Aceptar»: lo que propone la app es correcto.
        «Justificado»: está bien así (comentario obligatorio). «Corregido en el sistema»: se corrigió el asiento o el archivo;
        en la próxima corrida debe desaparecer.
      </p>

      <nav className="mb-2 flex flex-wrap gap-2 text-sm">
        {VISTAS.map(([k, t]) => (
          <Link key={k} href={url(k, banco)}
            className={`rounded-full border px-3 py-1 ${vista === k ? "border-acento bg-acento text-white" : "border-linea bg-hoja hover:border-acento"}`}>
            {t} ({cuenta[k]})
          </Link>
        ))}
      </nav>
      {bancos.length > 1 && (
        <nav className="mb-6 flex flex-wrap gap-2 text-xs">
          <Link href={url(vista, "")} className={!banco ? "font-medium text-acento" : "text-tenue hover:text-acento"}>Todos</Link>
          {bancos.map((b) => (
            <Link key={b} href={url(vista, b)} className={banco === b ? "font-medium text-acento" : "text-tenue hover:text-acento"}>
              {nombreBanco(b)}
            </Link>
          ))}
        </nav>
      )}

      {lista.length === 0 ? (
        <p className="tarjeta p-4 text-sm text-tenue">
          {vista === "pendientes" ? "No queda ninguna partida pendiente en esta vista." : "No hay partidas en esta vista."}
        </p>
      ) : (
        <div className="space-y-4">
          {lista.map((p) => {
            const d = decisiones.get(p.codigo);
            const s = situacion(p);
            return (
              <article key={p.codigo} className="tarjeta grid gap-4 p-4 lg:grid-cols-3">
                <div className="space-y-2 lg:col-span-2">
                  <div className="flex flex-wrap items-center gap-2 text-xs text-tenue">
                    <span className={`insignia ${COLOR[s] ?? "bg-linea text-tinta"}`}>{s}</span>
                    <span className="font-mono">{p.codigo}</span>
                    <span>· {nombreBanco(p.banco)} · {p.origen}</span>
                    {p.fecha && <span>· {fechaCorta(p.fecha)}</span>}
                  </div>
                  <h3 className="font-medium">{p.tipo}</h3>
                  <p className="text-sm">
                    {p.descripcion}
                    {(p.monto_bs || p.monto_usd) && (
                      <span className="ml-2 whitespace-nowrap font-medium">
                        {p.monto_bs && `Bs. ${formatoVE(p.monto_bs)}`}
                        {p.monto_bs && p.monto_usd && " · "}
                        {p.monto_usd && `US$ ${formatoVE(p.monto_usd)}`}
                      </span>
                    )}
                  </p>
                  {p.explicacion && <p className="text-sm leading-relaxed">{p.explicacion}</p>}
                  {p.que_hacer && (
                    <p className="rounded-md bg-acento-suave px-3 py-2 text-sm text-acento">
                      <span className="font-medium">Qué hacer: </span>{p.que_hacer}
                    </p>
                  )}
                  {p.propuesta && (
                    <p className="text-xs text-tenue">
                      Si eliges «Aceptar», la próxima corrida cambia la fecha de la fila {p.propuesta.fila} del cierre de caja
                      a {fechaCorta(p.propuesta.fecha)}.
                    </p>
                  )}
                  {p.aviso && <p className="msg-error text-xs">{p.aviso}</p>}
                  {p.detalle && (
                    <details className="text-xs text-tenue">
                      <summary className="cursor-pointer">Detalle técnico</summary>
                      <p className="mt-1 whitespace-pre-wrap break-words">{p.detalle}</p>
                    </details>
                  )}
                </div>
                <div className="space-y-2 border-linea lg:border-l lg:pl-4">
                  {d && (
                    <p className="text-xs text-tenue">
                      Decisión actual: <span className="font-medium text-tinta">{d.decision}</span>
                      {" · "}{d.autor?.nombre ?? d.autor?.email} · {fechaHora(d.decidido_en)}
                      {d.comentario && <span className="mt-1 block italic">«{d.comentario}»</span>}
                    </p>
                  )}
                  <Decision
                    key={`${p.codigo}-${d?.decidido_en ?? ""}`}
                    corridaId={corrida.id}
                    codigo={p.codigo}
                    sugerida={p.sugerencia}
                    decision={d?.decision ?? null}
                    comentario={d?.comentario ?? null}
                    deshabilitado={cerrado}
                  />
                </div>
              </article>
            );
          })}
        </div>
      )}
    </>
  );
}
