import { redirect } from "next/navigation";
import { Mensajes } from "@/components/mensajes";
import { crearClienteServidor } from "@/lib/supabase/server";

async function guardar(f: FormData) {
  "use server";
  const nueva = String(f.get("nueva") ?? "");
  const repetir = String(f.get("repetir") ?? "");
  const volver = (m: string): never => redirect(`/nueva-clave?error=${encodeURIComponent(m)}`);
  if (nueva.length < 10) volver("La contraseña debe tener al menos 10 caracteres");
  if (nueva !== repetir) volver("Las contraseñas no coinciden");
  const supabase = await crearClienteServidor();
  const { data } = await supabase.auth.getClaims();
  if (!data?.claims) redirect("/recuperar?error=" + encodeURIComponent("La sesión del enlace venció. Pide uno nuevo."));
  const { error } = await supabase.auth.updateUser({ password: nueva });
  if (error) volver(/different|same/i.test(error.message) ? "La contraseña nueva debe ser distinta de la anterior" : "No se pudo guardar la contraseña");
  redirect("/?ok=" + encodeURIComponent("Contraseña actualizada"));
}

/** Crear contraseña nueva después de abrir el enlace de recuperación (ya con sesión iniciada). */
export default async function NuevaClave({ searchParams }: PageProps<"/nueva-clave">) {
  const { error } = await searchParams;
  const supabase = await crearClienteServidor();
  const { data } = await supabase.auth.getClaims();
  if (!data?.claims) redirect("/recuperar");
  return (
    <main className="flex flex-1 items-center justify-center px-4 py-16">
      <div className="w-full max-w-sm">
        <div className="mb-8 text-center">
          <p className="font-serif text-3xl font-semibold tracking-tight">CVP Contable</p>
          <p className="mt-1 text-sm text-tenue">Crea tu contraseña nueva · {String(data.claims.email ?? "")}</p>
        </div>
        <form action={guardar} className="tarjeta space-y-4 p-6">
          <Mensajes error={error} />
          <div>
            <label htmlFor="nueva" className="etiqueta">Contraseña nueva (mínimo 10 caracteres)</label>
            <input id="nueva" name="nueva" type="password" minLength={10} required autoComplete="new-password" className="campo" />
          </div>
          <div>
            <label htmlFor="repetir" className="etiqueta">Repetir</label>
            <input id="repetir" name="repetir" type="password" minLength={10} required autoComplete="new-password" className="campo" />
          </div>
          <button className="boton w-full">Guardar contraseña</button>
        </form>
      </div>
    </main>
  );
}
