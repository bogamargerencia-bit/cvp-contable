"use server";

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";
import { exigirAdmin } from "@/lib/sesion";
import { crearClienteAdmin } from "@/lib/supabase/admin";
import { crearClienteServidor } from "@/lib/supabase/server";

const RUTA = "/admin/usuarios";
function err(m: string): never {
  redirect(`${RUTA}?error=${encodeURIComponent(m)}`);
}

/** Crea el usuario con una contraseña temporal y lo deja activo. El usuario la cambia en «Mi cuenta». */
export async function crearUsuario(f: FormData) {
  await exigirAdmin();
  const email = String(f.get("email") ?? "").trim().toLowerCase();
  const nombre = String(f.get("nombre") ?? "").trim();
  const password = String(f.get("password") ?? "");
  const rol = f.get("rol") === "admin" ? "admin" : "analista";
  if (!email || !nombre) err("Correo y nombre son obligatorios");
  if (password.length < 10) err("La contraseña temporal debe tener al menos 10 caracteres");

  const admin = crearClienteAdmin();
  const { data, error } = await admin.auth.admin.createUser({
    email,
    password,
    email_confirm: true,
    user_metadata: { nombre },
  });
  if (error || !data.user) err(error?.message.includes("already") ? "Ya existe un usuario con ese correo" : "No se pudo crear el usuario");
  // El trigger crear_perfil ya insertó el perfil (inactivo); aquí se activa con su rol.
  const { error: e2 } = await admin.from("perfiles").update({ activo: true, rol, nombre }).eq("id", data.user.id);
  if (e2) err("Usuario creado, pero no se pudo activar: actívalo en la lista");
  revalidatePath(RUTA);
  redirect(`${RUTA}?ok=${encodeURIComponent(`Usuario ${email} creado. Entrégale la contraseña temporal por un canal seguro.`)}`);
}

/** Cambia rol o estado. Usa la sesión del admin: RLS y el trigger proteger_perfil lo validan también. */
export async function actualizarUsuario(f: FormData) {
  const yo = await exigirAdmin();
  const id = String(f.get("id"));
  const campo = String(f.get("campo"));
  if (id === yo.id) err("No puedes cambiar tu propio rol ni desactivarte (evita quedarte sin administrador)");

  const cambio =
    campo === "rol" ? { rol: f.get("valor") === "admin" ? "admin" : "analista" }
    : campo === "activo" ? { activo: f.get("valor") === "true" }
    : null;
  if (!cambio) err("Cambio no válido");

  const supabase = await crearClienteServidor();
  const { error } = await supabase.from("perfiles").update(cambio).eq("id", id);
  if (error) err("No se pudo actualizar el usuario");
  revalidatePath(RUTA);
}

/**
 * El admin le pone una contraseña temporal a otro usuario (cuando no le llega el correo de recuperación).
 * Usa la clave de servicio solo en el servidor; el usuario la cambia luego en «Mi cuenta».
 */
export async function restablecerContrasena(f: FormData) {
  const yo = await exigirAdmin();
  const id = String(f.get("id"));
  const password = String(f.get("password") ?? "");
  if (id === yo.id) err("Para tu propia contraseña usa «Mi cuenta»");
  if (password.length < 10) err("La contraseña temporal debe tener al menos 10 caracteres");
  const { error } = await crearClienteAdmin().auth.admin.updateUserById(id, { password });
  if (error) err("No se pudo cambiar la contraseña");
  revalidatePath(RUTA);
  redirect(`${RUTA}?ok=${encodeURIComponent("Contraseña temporal asignada. Entrégala por un canal seguro y pide que la cambie en «Mi cuenta».")}`);
}
