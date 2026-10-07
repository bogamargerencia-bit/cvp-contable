import type { EmailOtpType } from "@supabase/supabase-js";
import { NextResponse, type NextRequest } from "next/server";
import { crearClienteServidor } from "@/lib/supabase/server";

/**
 * Destino del enlace del correo de recuperación. Acepta los dos formatos de Supabase:
 *  - token_hash + type (plantilla de correo recomendada: funciona aunque se abra en otro dispositivo);
 *  - code (plantilla por defecto, flujo PKCE: solo funciona en el mismo navegador donde se pidió).
 * Si el enlace es válido, deja la sesión iniciada y manda a crear la contraseña nueva.
 */
export async function GET(request: NextRequest) {
  const url = request.nextUrl;
  const token_hash = url.searchParams.get("token_hash");
  const type = url.searchParams.get("type") as EmailOtpType | null;
  const code = url.searchParams.get("code");
  const pedido = url.searchParams.get("siguiente") ?? url.searchParams.get("next") ?? "/nueva-clave";
  const siguiente = pedido.startsWith("/") && !pedido.startsWith("//") ? pedido : "/nueva-clave";

  const supabase = await crearClienteServidor();
  let ok = false;
  if (token_hash && type) {
    ok = !(await supabase.auth.verifyOtp({ type, token_hash })).error;
  } else if (code) {
    ok = !(await supabase.auth.exchangeCodeForSession(code)).error;
  }
  const destino = url.clone();
  destino.search = "";
  if (ok) {
    destino.pathname = siguiente;
  } else {
    destino.pathname = "/recuperar";
    destino.searchParams.set("error", "El enlace no es válido o ya venció (dura 1 hora y sirve una sola vez). Pide uno nuevo.");
  }
  return NextResponse.redirect(destino);
}
