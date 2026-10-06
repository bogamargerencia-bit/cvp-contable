import { redirect } from "next/navigation";
import { Mensajes } from "@/components/mensajes";
import { perfilActual } from "@/lib/sesion";
import { crearClienteServidor } from "@/lib/supabase/server";

async function cambiarContrasena(f: FormData) {
  "use server";
  await perfilActual();
  const nueva = String(f.get("nueva") ?? "");
  const repetir = String(f.get("repetir") ?? "");
  const volver = (k: "error" | "ok", m: string): never => redirect(`/cuenta?${k}=${encodeURIComponent(m)}`);
  if (nueva.length < 10) volver("error", "La contraseña debe tener al menos 10 caracteres");
  if (nueva !== repetir) volver("error", "Las contraseñas no coinciden");
  const supabase = await crearClienteServidor();
  const { error } = await supabase.auth.updateUser({ password: nueva });
  if (error) volver("error", "No se pudo cambiar la contraseña");
  volver("ok", "Contraseña actualizada");
}

export default async function MiCuenta({ searchParams }: PageProps<"/cuenta">) {
  const perfil = await perfilActual();
  const { error, ok } = await searchParams;
  return (
    <div className="max-w-md">
      <h1 className="titulo mb-1">Mi cuenta</h1>
      <p className="mb-6 text-sm text-tenue">
        {perfil.nombre} · {perfil.email} · {perfil.rol === "admin" ? "Administrador" : "Analista"}
      </p>
      <Mensajes error={error} ok={ok} />
      <form action={cambiarContrasena} className="tarjeta space-y-4 p-6">
        <h2 className="subtitulo">Cambiar contraseña</h2>
        <div>
          <label htmlFor="nueva" className="etiqueta">Nueva contraseña</label>
          <input id="nueva" name="nueva" type="password" minLength={10} required autoComplete="new-password" className="campo" />
        </div>
        <div>
          <label htmlFor="repetir" className="etiqueta">Repetir</label>
          <input id="repetir" name="repetir" type="password" minLength={10} required autoComplete="new-password" className="campo" />
        </div>
        <button className="boton">Guardar</button>
      </form>
    </div>
  );
}
