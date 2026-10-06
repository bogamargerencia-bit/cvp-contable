import Link from "next/link";
import { Mensajes } from "@/components/mensajes";
import { perfilActual } from "@/lib/sesion";
import { crearClienteServidor } from "@/lib/supabase/server";
import { MESES } from "@/lib/tipos";

type Fila = {
  id: string;
  nombre: string;
  nombre_comercial: string | null;
  rif: string | null;
  activo: boolean;
  cuentas: { count: number }[];
  periodos: { anio: number; mes: number; estado: string }[];
};

export default async function Clientes({ searchParams }: PageProps<"/">) {
  const { error, ok } = await searchParams;
  const perfil = await perfilActual();
  const supabase = await crearClienteServidor();
  const { data, error: e } = await supabase
    .from("clientes")
    .select("id, nombre, nombre_comercial, rif, activo, cuentas(count), periodos(anio, mes, estado)")
    .order("nombre_comercial", { ascending: true, nullsFirst: false })
    .order("anio", { referencedTable: "periodos", ascending: false })
    .order("mes", { referencedTable: "periodos", ascending: false })
    .limit(1, { referencedTable: "periodos" });
  const clientes = (data ?? []) as Fila[];

  return (
    <>
      <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="titulo">Clientes</h1>
          <p className="mt-1 text-sm text-tenue">
            {clientes.length} {clientes.length === 1 ? "cliente" : "clientes"}
          </p>
        </div>
        {perfil.rol === "admin" && <Link href="/clientes/nuevo" className="boton">Nuevo cliente</Link>}
      </div>
      <Mensajes error={error ?? (e ? "No se pudieron cargar los clientes" : undefined)} ok={ok} />

      {clientes.length === 0 ? (
        <div className="tarjeta p-10 text-center text-sm text-tenue">
          {perfil.rol === "admin"
            ? "Aún no hay clientes. Crea el primero con «Nuevo cliente»."
            : "No tienes clientes visibles. Pide al administrador que te asigne alguno."}
        </div>
      ) : (
        <div className="tarjeta overflow-x-auto">
          <table className="tabla">
            <thead>
              <tr>
                <th>Cliente</th>
                <th>RIF</th>
                <th className="text-right">Cuentas</th>
                <th>Último período</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {clientes.map((c) => {
                const p = c.periodos[0];
                return (
                  <tr key={c.id} className={c.activo ? "" : "opacity-55"}>
                    <td>
                      <Link href={`/clientes/${c.id}`} className="font-medium hover:text-acento">
                        {c.nombre_comercial ?? c.nombre}
                      </Link>
                      {c.nombre_comercial && <span className="block text-xs text-tenue">{c.nombre}</span>}
                    </td>
                    <td className="whitespace-nowrap text-tenue">{c.rif ?? "—"}</td>
                    <td className="text-right">{c.cuentas[0]?.count ?? 0}</td>
                    <td className="whitespace-nowrap">
                      {p ? (
                        <>
                          {MESES[p.mes - 1]} {p.anio}{" "}
                          <span className={`insignia ${p.estado === "cerrado" ? "bg-acento-suave text-acento" : "bg-aviso-suave text-aviso"}`}>
                            {p.estado}
                          </span>
                        </>
                      ) : (
                        <span className="text-tenue">—</span>
                      )}
                    </td>
                    <td className="text-right">
                      {!c.activo && <span className="insignia bg-linea text-tenue">inactivo</span>}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}
