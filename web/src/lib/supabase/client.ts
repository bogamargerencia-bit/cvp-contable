import { createBrowserClient } from "@supabase/ssr";

/** Cliente del navegador (sesión del usuario, respeta RLS). Se usa para subir archivos directo a Storage. */
export function crearClienteNavegador() {
  return createBrowserClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY!,
  );
}
