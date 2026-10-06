import { cerrarSesion } from "../login/actions";

export default function Inactivo() {
  return (
    <main className="flex flex-1 items-center justify-center px-4">
      <div className="tarjeta max-w-md p-8 text-center">
        <p className="subtitulo">Tu usuario no está activo</p>
        <p className="mt-2 text-sm text-tenue">
          Un administrador debe activarlo antes de que puedas ver clientes. Avísale y vuelve a entrar.
        </p>
        <form action={cerrarSesion} className="mt-6">
          <button className="boton-sec">Cerrar sesión</button>
        </form>
      </div>
    </main>
  );
}
