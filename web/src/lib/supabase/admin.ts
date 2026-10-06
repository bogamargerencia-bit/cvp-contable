import "server-only";
import { createClient } from "@supabase/supabase-js";

/**
 * Cliente con la clave secreta (service_role): SALTA RLS.
 * Solo para acciones de administración ya autorizadas (crear usuarios). Nunca llega al navegador:
 * el import "server-only" rompe el build si alguien lo importa desde un componente cliente.
 */
export function crearClienteAdmin() {
  const clave = process.env.SUPABASE_SECRET_KEY;
  if (!clave) throw new Error("Falta SUPABASE_SECRET_KEY en las variables de entorno del servidor");
  return createClient(process.env.NEXT_PUBLIC_SUPABASE_URL!, clave, {
    auth: { persistSession: false, autoRefreshToken: false },
  });
}
