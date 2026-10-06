import Link from "next/link";
import { perfilActual } from "@/lib/sesion";
import { cerrarSesion } from "../login/actions";

export default async function LayoutApp({ children }: LayoutProps<"/">) {
  const perfil = await perfilActual();
  return (
    <>
      <header className="border-b border-linea bg-hoja">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center gap-x-8 gap-y-2 px-4 py-3">
          <Link href="/" className="font-serif text-lg font-semibold tracking-tight">CVP Contable</Link>
          <nav className="flex gap-5 text-sm">
            <Link href="/" className="text-tenue hover:text-acento">Clientes</Link>
            {perfil.rol === "admin" && (
              <Link href="/admin/usuarios" className="text-tenue hover:text-acento">Usuarios</Link>
            )}
          </nav>
          <div className="ml-auto flex items-center gap-3 text-sm">
            <Link href="/cuenta" className="text-right leading-tight hover:text-acento">
              <span className="block">{perfil.nombre ?? perfil.email}</span>
              <span className="block text-xs text-tenue">{perfil.rol === "admin" ? "Administrador" : "Analista"}</span>
            </Link>
            <form action={cerrarSesion}>
              <button className="boton-sec">Salir</button>
            </form>
          </div>
        </div>
      </header>
      <main className="mx-auto w-full max-w-6xl flex-1 px-4 py-8">{children}</main>
    </>
  );
}
