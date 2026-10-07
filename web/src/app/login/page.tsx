import Link from "next/link";
import { Mensajes } from "@/components/mensajes";
import { iniciarSesion } from "./actions";

export default async function Login({ searchParams }: PageProps<"/login">) {
  const { error } = await searchParams;
  return (
    <main className="flex flex-1 items-center justify-center px-4 py-16">
      <div className="w-full max-w-sm">
        <div className="mb-8 text-center">
          <p className="font-serif text-3xl font-semibold tracking-tight">CVP Contable</p>
          <p className="mt-1 text-sm text-tenue">Conciliación de estados de cuenta · uso interno</p>
        </div>
        <form action={iniciarSesion} className="tarjeta space-y-4 p-6">
          <Mensajes error={error} />
          <div>
            <label htmlFor="email" className="etiqueta">Correo</label>
            <input id="email" name="email" type="email" autoComplete="email" required className="campo" />
          </div>
          <div>
            <label htmlFor="password" className="etiqueta">Contraseña</label>
            <input id="password" name="password" type="password" autoComplete="current-password" required className="campo" />
          </div>
          <button className="boton w-full">Entrar</button>
          <p className="text-center text-sm">
            <Link href="/recuperar" className="text-acento hover:underline">¿Olvidaste tu contraseña?</Link>
          </p>
        </form>
        <p className="mt-6 text-center text-xs text-tenue">
          Las cuentas las crea el administrador. Si no tienes acceso, pídeselo.
        </p>
      </div>
    </main>
  );
}
