import Link from "next/link";
import { Mensajes } from "@/components/mensajes";
import { pedirEnlace } from "./actions";

export default async function Recuperar({ searchParams }: PageProps<"/recuperar">) {
  const { error, ok } = await searchParams;
  return (
    <main className="flex flex-1 items-center justify-center px-4 py-16">
      <div className="w-full max-w-sm">
        <div className="mb-8 text-center">
          <p className="font-serif text-3xl font-semibold tracking-tight">CVP Contable</p>
          <p className="mt-1 text-sm text-tenue">Recuperar contraseña</p>
        </div>
        <form action={pedirEnlace} className="tarjeta space-y-4 p-6">
          <Mensajes error={error} ok={ok} />
          <p className="text-sm text-tenue">Escribe tu correo y te enviaremos un enlace para crear una contraseña nueva.</p>
          <p className="text-xs text-tenue">
            Importante: pídelo <span className="font-medium">una sola vez</span> y abre el enlace del correo{" "}
            <span className="font-medium">más reciente</span>, en <span className="font-medium">este mismo navegador</span>.
            Cada pedido anula el enlace anterior, y el enlace no funciona en otro dispositivo.
          </p>
          <div>
            <label htmlFor="email" className="etiqueta">Correo</label>
            <input id="email" name="email" type="email" autoComplete="email" required className="campo" />
          </div>
          <button className="boton w-full">Enviar enlace</button>
        </form>
        <p className="mt-6 text-center text-xs text-tenue">
          ¿No te llega el correo? Pide al administrador una contraseña temporal.
          <br />
          <Link href="/login" className="text-acento hover:underline">← Volver a entrar</Link>
        </p>
      </div>
    </main>
  );
}
