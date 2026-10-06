import { Mensajes } from "@/components/mensajes";
import { exigirAdmin } from "@/lib/sesion";
import { crearClienteServidor } from "@/lib/supabase/server";
import type { Perfil } from "@/lib/tipos";
import { actualizarUsuario, crearUsuario } from "./actions";

export default async function Usuarios({ searchParams }: PageProps<"/admin/usuarios">) {
  const yo = await exigirAdmin();
  const { error, ok } = await searchParams;
  const supabase = await crearClienteServidor();
  const { data } = await supabase.from("perfiles").select("*").order("activo", { ascending: false }).order("nombre");
  const usuarios = (data ?? []) as Perfil[];

  return (
    <>
      <h1 className="titulo mb-1">Usuarios</h1>
      <p className="mb-6 text-sm text-tenue">Solo personal de CVP. Los clientes no tienen acceso a la aplicación.</p>
      <Mensajes error={error} ok={ok} />

      <div className="grid gap-8 lg:grid-cols-3">
        <section className="lg:col-span-2">
          <div className="tarjeta overflow-x-auto">
            <table className="tabla">
              <thead>
                <tr><th>Usuario</th><th>Rol</th><th>Estado</th><th></th></tr>
              </thead>
              <tbody>
                {usuarios.map((u) => {
                  const soyYo = u.id === yo.id;
                  return (
                    <tr key={u.id} className={u.activo ? "" : "opacity-60"}>
                      <td>
                        {u.nombre ?? "—"}{soyYo && <span className="text-tenue"> (tú)</span>}
                        <span className="block text-xs text-tenue">{u.email}</span>
                      </td>
                      <td>{u.rol === "admin" ? "Administrador" : "Analista"}</td>
                      <td>
                        <span className={`insignia ${u.activo ? "bg-acento-suave text-acento" : "bg-alerta-suave text-alerta"}`}>
                          {u.activo ? "activo" : "inactivo"}
                        </span>
                      </td>
                      <td>
                        {!soyYo && (
                          <div className="flex justify-end gap-2">
                            <form action={actualizarUsuario}>
                              <input type="hidden" name="id" value={u.id} />
                              <input type="hidden" name="campo" value="rol" />
                              <input type="hidden" name="valor" value={u.rol === "admin" ? "analista" : "admin"} />
                              <button className="boton-sec whitespace-nowrap">
                                {u.rol === "admin" ? "Hacer analista" : "Hacer admin"}
                              </button>
                            </form>
                            <form action={actualizarUsuario}>
                              <input type="hidden" name="id" value={u.id} />
                              <input type="hidden" name="campo" value="activo" />
                              <input type="hidden" name="valor" value={String(!u.activo)} />
                              <button className="boton-sec">{u.activo ? "Desactivar" : "Activar"}</button>
                            </form>
                          </div>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </section>

        <section>
          <form action={crearUsuario} className="tarjeta space-y-4 p-5">
            <h2 className="subtitulo">Nuevo usuario</h2>
            <div>
              <label htmlFor="nombre" className="etiqueta">Nombre *</label>
              <input id="nombre" name="nombre" required className="campo" />
            </div>
            <div>
              <label htmlFor="email" className="etiqueta">Correo *</label>
              <input id="email" name="email" type="email" required className="campo" />
            </div>
            <div>
              <label htmlFor="password" className="etiqueta">Contraseña temporal *</label>
              <input id="password" name="password" type="text" minLength={10} required autoComplete="off" className="campo font-mono" />
              <p className="mt-1 text-xs text-tenue">Mínimo 10 caracteres. El usuario la cambia en «Mi cuenta».</p>
            </div>
            <div>
              <label htmlFor="rol" className="etiqueta">Rol</label>
              <select id="rol" name="rol" className="campo" defaultValue="analista">
                <option value="analista">Analista</option>
                <option value="admin">Administrador</option>
              </select>
            </div>
            <button className="boton w-full">Crear usuario</button>
          </form>
        </section>
      </div>
    </>
  );
}
