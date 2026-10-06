import { NextResponse, type NextRequest } from "next/server";
import { crearClienteServidor } from "@/lib/supabase/server";

/** Descarga del Excel de una corrida: enlace firmado de 60 s, emitido con la sesión del usuario (RLS). */
export async function GET(request: NextRequest, ctx: RouteContext<"/descargar/[corridaId]">) {
  const { corridaId } = await ctx.params;
  const supabase = await crearClienteServidor();
  const { data: claims } = await supabase.auth.getClaims();
  if (!claims?.claims) return NextResponse.redirect(new URL("/login", request.url));

  const { data: c } = await supabase.from("corridas").select("excel_path").eq("id", corridaId).maybeSingle();
  if (!c?.excel_path) return new NextResponse("Archivo no disponible", { status: 404 });
  const nombre = c.excel_path.split("/").pop()!;
  const { data, error } = await supabase.storage.from("archivos").createSignedUrl(c.excel_path, 60, { download: nombre });
  if (error || !data) return new NextResponse("No se pudo generar el enlace", { status: 500 });
  return NextResponse.redirect(data.signedUrl);
}
