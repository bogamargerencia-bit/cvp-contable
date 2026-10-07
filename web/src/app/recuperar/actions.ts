"use server";

import { headers } from "next/headers";
import { redirect } from "next/navigation";
import { crearClienteServidor } from "@/lib/supabase/server";

const MENSAJE = "Si el correo está registrado, te llegará un enlace para crear una contraseña nueva. Revisa también el correo no deseado.";

/** Pide a Supabase el correo de recuperación. Siempre responde lo mismo: no revela si el correo existe. */
export async function pedirEnlace(f: FormData) {
  const email = String(f.get("email") ?? "").trim().toLowerCase();
  if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) redirect("/recuperar?error=" + encodeURIComponent("Escribe un correo válido"));
  const h = await headers();
  const origen = h.get("origin") ?? `https://${h.get("host")}`;
  const supabase = await crearClienteServidor();
  const { error } = await supabase.auth.resetPasswordForEmail(email, {
    redirectTo: `${origen}/auth/confirmar?siguiente=/nueva-clave`,
  });
  // Un límite de envíos o un fallo del correo sí se avisa (no revela nada sobre la cuenta).
  if (error && /rate|limit|seconds/i.test(error.message)) {
    redirect("/recuperar?error=" + encodeURIComponent("Se pidieron demasiados enlaces. Espera unos minutos o pide al administrador una contraseña temporal."));
  }
  redirect("/recuperar?ok=" + encodeURIComponent(MENSAJE));
}
