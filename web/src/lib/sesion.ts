import "server-only";
import { redirect } from "next/navigation";
import { cache } from "react";
import { crearClienteServidor } from "./supabase/server";
import type { Perfil } from "./tipos";

/** Perfil del usuario con sesión. Sin sesión → /login; inactivo → /inactivo. */
export const perfilActual = cache(async (): Promise<Perfil> => {
  const supabase = await crearClienteServidor();
  const { data: claims } = await supabase.auth.getClaims();
  const id = claims?.claims?.sub;
  if (!id) redirect("/login");
  const { data } = await supabase.from("perfiles").select("*").eq("id", id).single();
  if (!data || !data.activo) redirect("/inactivo");
  return data as Perfil;
});

/** Igual que perfilActual, pero exige rol admin. */
export async function exigirAdmin(): Promise<Perfil> {
  const p = await perfilActual();
  if (p.rol !== "admin") redirect("/?error=" + encodeURIComponent("Esa sección es solo para administradores"));
  return p;
}
