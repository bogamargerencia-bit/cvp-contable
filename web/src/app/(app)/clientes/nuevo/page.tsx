import Link from "next/link";
import { Mensajes } from "@/components/mensajes";
import { exigirAdmin } from "@/lib/sesion";
import { CONFIGS_PARSER, MODOS } from "@/lib/tipos";
import { crearCliente } from "../actions";

export default async function NuevoCliente({ searchParams }: PageProps<"/clientes/nuevo">) {
  await exigirAdmin();
  const { error } = await searchParams;
  return (
    <div className="max-w-xl">
      <Link href="/" className="text-sm text-tenue hover:text-acento">← Clientes</Link>
      <h1 className="titulo mt-2 mb-6">Nuevo cliente</h1>
      <Mensajes error={error} />
      <form action={crearCliente} className="tarjeta space-y-4 p-6">
        <div>
          <label htmlFor="nombre" className="etiqueta">Razón social *</label>
          <input id="nombre" name="nombre" required className="campo" placeholder="ALIMENTOS SIERRA DEL SOL, C.A." />
        </div>
        <div className="grid gap-4 sm:grid-cols-2">
          <div>
            <label htmlFor="nombre_comercial" className="etiqueta">Nombre comercial</label>
            <input id="nombre_comercial" name="nombre_comercial" className="campo" placeholder="WEI REST" />
          </div>
          <div>
            <label htmlFor="rif" className="etiqueta">RIF</label>
            <input id="rif" name="rif" className="campo" placeholder="J-12345678-9" />
          </div>
        </div>
        <div>
          <label htmlFor="modo" className="etiqueta">Servicio</label>
          <select id="modo" name="modo" className="campo" defaultValue={"conciliacion"}>
            {MODOS.map((m) => <option key={m.valor} value={m.valor}>{m.nombre} — {m.ayuda}</option>)}
          </select>
        </div>
        <div>
          <label htmlFor="clave_config" className="etiqueta">Reglas del parser</label>
          <select id="clave_config" name="clave_config" className="campo" defaultValue="">
            <option value="">Detección automática</option>
            {CONFIGS_PARSER.map((c) => <option key={c} value={c}>{c}</option>)}
          </select>
          <p className="mt-1 text-xs text-tenue">
            Medios de caja, asientos resumen y divisas configurados para ese cliente en el parser.
          </p>
        </div>
        <button className="boton">Crear cliente</button>
      </form>
    </div>
  );
}
