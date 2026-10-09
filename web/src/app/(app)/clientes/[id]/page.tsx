import Link from "next/link";
import { notFound } from "next/navigation";
import { Mensajes } from "@/components/mensajes";
import { perfilActual } from "@/lib/sesion";
import { crearClienteServidor } from "@/lib/supabase/server";
import { BANCOS, CONFIGS_PARSER, DIVISAS_PARSER, MODOS, modoDe, MESES, nombreBanco, type Cliente, type Cuenta, type Periodo } from "@/lib/tipos";
import { cambiarEstadoCliente, crearCuenta, crearPeriodo, editarCliente, editarCuenta, eliminarCuenta } from "../actions";

/** Muestra solo los últimos 4 dígitos: son datos bancarios de terceros. */
const enmascarar = (n: string | null) => (n ? `•••• ${n.slice(-4)}` : "—");

export default async function DetalleCliente({ params, searchParams }: PageProps<"/clientes/[id]">) {
  const { id } = await params;
  const { error, ok, editar } = await searchParams;
  const perfil = await perfilActual();
  const esAdmin = perfil.rol === "admin";
  const supabase = await crearClienteServidor();

  const [{ data: cliente }, { data: cuentas }, { data: periodos }] = await Promise.all([
    supabase.from("clientes").select("*").eq("id", id).maybeSingle(),
    supabase.from("cuentas").select("*").eq("cliente_id", id).order("tipo").order("nombre"),
    supabase.from("periodos").select("*").eq("cliente_id", id).order("anio", { ascending: false }).order("mes", { ascending: false }),
  ]);
  if (!cliente) notFound(); // no existe o RLS no le deja verlo
  const c = cliente as Cliente;
  const ctas = (cuentas ?? []) as Cuenta[];
  const pers = (periodos ?? []) as Periodo[];
  const editando = esAdmin ? ctas.find((k) => k.id === editar) : undefined;
  const divisasParser = c.clave_config ? DIVISAS_PARSER[c.clave_config] ?? [] : [];

  const hoy = new Date();
  const mesAnterior = new Date(hoy.getFullYear(), hoy.getMonth() - 1, 1);
  const valorMes = `${mesAnterior.getFullYear()}-${String(mesAnterior.getMonth() + 1).padStart(2, "0")}`;

  return (
    <>
      <Link href="/" className="text-sm text-tenue hover:text-acento">← Clientes</Link>
      <div className="mt-2 mb-6 flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="titulo">{c.nombre_comercial ?? c.nombre}</h1>
          <p className="mt-1 text-sm text-tenue">
            {c.nombre}{c.rif && ` · ${c.rif}`}{c.clave_config && ` · reglas ${c.clave_config}`}
            {modoDe(c) === "conversion" && <span className="insignia ml-2 bg-acento-suave text-acento">solo conversión</span>}
            {!c.activo && " · inactivo"}
          </p>
        </div>
        {esAdmin && (
          <form action={cambiarEstadoCliente}>
            <input type="hidden" name="id" value={c.id} />
            <input type="hidden" name="activo" value={String(!c.activo)} />
            <button className="boton-sec">{c.activo ? "Desactivar cliente" : "Reactivar cliente"}</button>
          </form>
        )}
      </div>
      <Mensajes error={error} ok={ok} />

      {esAdmin && (
        <details className="tarjeta mb-6">
          <summary className="cursor-pointer px-4 py-3 text-sm font-medium">Editar datos del cliente</summary>
          <form action={editarCliente} className="grid gap-4 border-t border-linea p-4 sm:grid-cols-2">
            <input type="hidden" name="id" value={c.id} />
            <div>
              <label htmlFor="c_nombre" className="etiqueta">Razón social *</label>
              <input id="c_nombre" name="nombre" required defaultValue={c.nombre} className="campo" />
            </div>
            <div>
              <label htmlFor="c_comercial" className="etiqueta">Nombre comercial</label>
              <input id="c_comercial" name="nombre_comercial" defaultValue={c.nombre_comercial ?? ""} className="campo" />
            </div>
            <div>
              <label htmlFor="c_rif" className="etiqueta">RIF</label>
              <input id="c_rif" name="rif" defaultValue={c.rif ?? ""} className="campo" placeholder="J-12345678-9" />
            </div>
            <div className="sm:col-span-2">
              <label htmlFor="c_modo" className="etiqueta">Servicio</label>
              <select id="c_modo" name="modo" className="campo" defaultValue={modoDe(c)}>
                {MODOS.map((m) => <option key={m.valor} value={m.valor}>{m.nombre} — {m.ayuda}</option>)}
              </select>
            </div>
            <div>
              <label htmlFor="c_clave" className="etiqueta">Reglas del parser</label>
              <select id="c_clave" name="clave_config" className="campo" defaultValue={c.clave_config ?? ""}>
                <option value="">Detección automática</option>
                {CONFIGS_PARSER.map((k) => <option key={k} value={k}>{k}</option>)}
              </select>
            </div>
            <div className="sm:col-span-2">
              <button className="boton">Guardar cliente</button>
            </div>
          </form>
        </details>
      )}

      <div className="grid gap-8 lg:grid-cols-5">
        {/* ------------------------------------------------ períodos */}
        <section className="lg:col-span-2">
          <h2 className="subtitulo mb-3">Períodos</h2>
          <div className="tarjeta">
            {pers.length === 0 ? (
              <p className="p-5 text-sm text-tenue">Sin períodos todavía.</p>
            ) : (
              <ul>
                {pers.map((p) => (
                  <li key={p.id} className="border-b border-linea/70 last:border-b-0">
                    <Link href={`/clientes/${c.id}/periodos/${p.id}`}
                      className="flex items-center justify-between px-4 py-2.5 text-sm hover:bg-acento-suave/50">
                      <span className="font-medium">{MESES[p.mes - 1]} {p.anio}</span>
                      <span className={`insignia ${p.estado === "cerrado" ? "bg-acento-suave text-acento" : "bg-aviso-suave text-aviso"}`}>
                        {p.estado}
                      </span>
                    </Link>
                  </li>
                ))}
              </ul>
            )}
            <form action={crearPeriodo} className="flex items-end gap-2 border-t border-linea p-4">
              <input type="hidden" name="cliente_id" value={c.id} />
              <div className="flex-1">
                <label htmlFor="mes" className="etiqueta">Abrir período</label>
                <input id="mes" name="mes" type="month" required defaultValue={valorMes} className="campo" />
              </div>
              <button className="boton">Crear</button>
            </form>
          </div>
          <p className="mt-2 text-xs text-tenue">Entra a un período para subir sus archivos y procesarlo.</p>
        </section>

        {/* ------------------------------------------------ cuentas */}
        <section className="lg:col-span-3">
          <h2 className="subtitulo mb-3">Cuentas</h2>
          <div className="tarjeta overflow-x-auto">
            {ctas.length === 0 ? (
              <p className="p-5 text-sm text-tenue">Sin cuentas registradas.</p>
            ) : (
              <table className="tabla">
                <thead>
                  <tr><th>Cuenta</th><th>Banco / medio</th><th>Número</th><th>Moneda</th>{esAdmin && <th />}</tr>
                </thead>
                <tbody>
                  {ctas.map((k) => (
                    <tr key={k.id} className={k.activo ? "" : "text-tenue"}>
                      <td>
                        {k.nombre}
                        {!k.activo && <span className="insignia ml-2 bg-linea text-tenue">inactiva</span>}
                        {k.es_personal && (
                          <span className="insignia ml-2 bg-aviso-suave text-aviso" title={k.titular ?? undefined}>personal</span>
                        )}
                        {k.titular && <span className="block text-xs text-tenue">{k.titular}</span>}
                      </td>
                      <td>{k.tipo === "divisa" ? "Divisas" : nombreBanco(k.banco)}</td>
                      <td className="whitespace-nowrap font-mono text-xs">{enmascarar(k.numero)}</td>
                      <td>{k.moneda === "USD" ? "US$" : "Bs."}</td>
                      {esAdmin && (
                        <td className="text-right">
                          <Link href={`/clientes/${c.id}?editar=${k.id}#editar`} className="text-sm text-acento hover:underline">Editar</Link>
                        </td>
                      )}
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>

          {editando && (
            <div id="editar" className="tarjeta mt-4 border-acento">
              <div className="flex items-center justify-between px-4 py-3">
                <p className="text-sm font-medium">Editar cuenta «{editando.nombre}»</p>
                <Link href={`/clientes/${c.id}`} className="text-sm text-tenue hover:text-acento">Cancelar</Link>
              </div>
              <FormCuenta clienteId={c.id} cuenta={editando} divisas={divisasParser} />
              <form action={eliminarCuenta} className="border-t border-linea px-4 py-3">
                <input type="hidden" name="cliente_id" value={c.id} />
                <input type="hidden" name="id" value={editando.id} />
                <button className="text-sm text-alerta hover:underline">Eliminar esta cuenta</button>
                <span className="ml-2 text-xs text-tenue">Solo si nunca se le subió un archivo; si no, desmárcala como activa.</span>
              </form>
            </div>
          )}

          {esAdmin && !editando && (
            <details className="tarjeta mt-4">
              <summary className="cursor-pointer px-4 py-3 text-sm font-medium">Agregar cuenta</summary>
              <FormCuenta clienteId={c.id} divisas={divisasParser} />
            </details>
          )}
        </section>
      </div>
    </>
  );
}

/** Formulario de cuenta: sin `cuenta` crea una nueva; con `cuenta` la edita. */
function FormCuenta({ clienteId, cuenta, divisas }: { clienteId: string; cuenta?: Cuenta; divisas: string[] }) {
  const k = cuenta;
  const p = k ? `e_` : "n_";
  return (
    <form action={k ? editarCuenta : crearCuenta} className="grid gap-4 border-t border-linea p-4 sm:grid-cols-2">
      <input type="hidden" name="cliente_id" value={clienteId} />
      {k && <input type="hidden" name="id" value={k.id} />}
      <div>
        <label htmlFor={`${p}tipo`} className="etiqueta">Tipo</label>
        <select id={`${p}tipo`} name="tipo" className="campo" defaultValue={k?.tipo ?? "banco"}>
          <option value="banco">Cuenta bancaria (Bs.)</option>
          <option value="divisa">Divisas (US$: efectivo, Zelle, USDT, fondo)</option>
        </select>
      </div>
      <div>
        <label htmlFor={`${p}banco`} className="etiqueta">Banco (si es bancaria)</label>
        <select id={`${p}banco`} name="banco" className="campo" defaultValue={k?.banco ?? ""}>
          <option value="">—</option>
          {BANCOS.map((b) => (
            <option key={b.codigo} value={b.codigo}>{b.nombre}{b.pendiente ? " (lector pendiente)" : ""}</option>
          ))}
        </select>
      </div>
      <div>
        <label htmlFor={`${p}nombre`} className="etiqueta">Nombre *</label>
        <input id={`${p}nombre`} name="nombre" required className="campo" defaultValue={k?.nombre ?? ""}
          placeholder="BNC ***1800 · Zelle" list={divisas.length ? `${p}divisas` : undefined} />
        {divisas.length > 0 && (
          <>
            <datalist id={`${p}divisas`}>{divisas.map((d) => <option key={d} value={d} />)}</datalist>
            <span className="mt-1 block text-xs text-tenue">
              Cuentas en divisas: el nombre debe ser uno de estos: {divisas.join(" · ")}
            </span>
          </>
        )}
      </div>
      <div>
        <label htmlFor={`${p}numero`} className="etiqueta">Número (20 dígitos)</label>
        <input id={`${p}numero`} name="numero" inputMode="numeric" className="campo font-mono"
          placeholder={k?.numero ? `${enmascarar(k.numero)} · vacío = no cambiar` : ""} />
        {k?.numero && (
          <label className="mt-1 flex items-center gap-2 text-xs text-tenue">
            <input type="checkbox" name="borrar_numero" className="accent-acento" /> Quitar el número guardado
          </label>
        )}
      </div>
      <div>
        <label htmlFor={`${p}titular`} className="etiqueta">Titular</label>
        <input id={`${p}titular`} name="titular" className="campo" defaultValue={k?.titular ?? ""} />
      </div>
      <div className="space-y-2 self-end pb-2 text-sm">
        <label className="flex items-center gap-2">
          <input type="checkbox" name="es_personal" defaultChecked={k?.es_personal ?? false} className="accent-acento" />
          Cuenta personal de un socio usada por la empresa
        </label>
        {k && (
          <label className="flex items-center gap-2">
            <input type="checkbox" name="activo" defaultChecked={k.activo} className="accent-acento" />
            Activa (aparece en los períodos)
          </label>
        )}
      </div>
      <div className="sm:col-span-2">
        <button className="boton">{k ? "Guardar cambios" : "Agregar cuenta"}</button>
      </div>
    </form>
  );
}
