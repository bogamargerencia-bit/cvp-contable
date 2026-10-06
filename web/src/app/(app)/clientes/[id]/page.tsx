import Link from "next/link";
import { notFound } from "next/navigation";
import { Mensajes } from "@/components/mensajes";
import { perfilActual } from "@/lib/sesion";
import { crearClienteServidor } from "@/lib/supabase/server";
import { BANCOS, MESES, nombreBanco, type Cliente, type Cuenta, type Periodo } from "@/lib/tipos";
import { cambiarEstadoCliente, crearCuenta, crearPeriodo } from "../actions";

/** Muestra solo los últimos 4 dígitos: son datos bancarios de terceros. */
const enmascarar = (n: string | null) => (n ? `•••• ${n.slice(-4)}` : "—");

export default async function DetalleCliente({ params, searchParams }: PageProps<"/clientes/[id]">) {
  const { id } = await params;
  const { error, ok } = await searchParams;
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
                  <tr><th>Cuenta</th><th>Banco / medio</th><th>Número</th><th>Moneda</th></tr>
                </thead>
                <tbody>
                  {ctas.map((k) => (
                    <tr key={k.id}>
                      <td>
                        {k.nombre}
                        {k.es_personal && (
                          <span className="insignia ml-2 bg-aviso-suave text-aviso" title={k.titular ?? undefined}>personal</span>
                        )}
                        {k.titular && <span className="block text-xs text-tenue">{k.titular}</span>}
                      </td>
                      <td>{k.tipo === "divisa" ? "Divisas" : nombreBanco(k.banco)}</td>
                      <td className="whitespace-nowrap font-mono text-xs">{enmascarar(k.numero)}</td>
                      <td>{k.moneda === "USD" ? "US$" : "Bs."}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>

          {esAdmin && (
            <details className="tarjeta mt-4">
              <summary className="cursor-pointer px-4 py-3 text-sm font-medium">Agregar cuenta</summary>
              <form action={crearCuenta} className="grid gap-4 border-t border-linea p-4 sm:grid-cols-2">
                <input type="hidden" name="cliente_id" value={c.id} />
                <div>
                  <label htmlFor="tipo" className="etiqueta">Tipo</label>
                  <select id="tipo" name="tipo" className="campo" defaultValue="banco">
                    <option value="banco">Cuenta bancaria (Bs.)</option>
                    <option value="divisa">Divisas (US$: efectivo, Zelle, USDT, fondo)</option>
                  </select>
                </div>
                <div>
                  <label htmlFor="banco" className="etiqueta">Banco (si es bancaria)</label>
                  <select id="banco" name="banco" className="campo" defaultValue="">
                    <option value="">—</option>
                    {BANCOS.map((b) => (
                      <option key={b.codigo} value={b.codigo}>{b.nombre}{b.pendiente ? " (lector pendiente)" : ""}</option>
                    ))}
                  </select>
                </div>
                <div>
                  <label htmlFor="nombre" className="etiqueta">Nombre *</label>
                  <input id="nombre" name="nombre" required className="campo" placeholder="BNC ***1800 · Zelle" />
                </div>
                <div>
                  <label htmlFor="numero" className="etiqueta">Número (20 dígitos)</label>
                  <input id="numero" name="numero" inputMode="numeric" className="campo font-mono" />
                </div>
                <div>
                  <label htmlFor="titular" className="etiqueta">Titular</label>
                  <input id="titular" name="titular" className="campo" />
                </div>
                <label className="flex items-center gap-2 self-end pb-2 text-sm">
                  <input type="checkbox" name="es_personal" className="accent-acento" />
                  Cuenta personal de un socio usada por la empresa
                </label>
                <div className="sm:col-span-2">
                  <button className="boton">Agregar cuenta</button>
                </div>
              </form>
            </details>
          )}
        </section>
      </div>
    </>
  );
}
