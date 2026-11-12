"use server";

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";
import { perfilActual } from "@/lib/sesion";
import { crearClienteServidor } from "@/lib/supabase/server";
import type { CuentaCatalogo } from "@/lib/tipos";

const TIPOS = ["exacta", "empieza", "contiene", "regex"];

function volver(clienteId: string, k: "error" | "ok", m: string, q = ""): never {
  redirect(`/clientes/${clienteId}/reglas?${k}=${encodeURIComponent(m)}${q ? `&q=${encodeURIComponent(q)}` : ""}`);
}

/** Como el parser (normalizar): mayúsculas, sin acentos (salvo Ñ), sin signos ni números sueltos. */
function normalizar(t: string): string {
  return t.toUpperCase().replace(/Ñ/g, "\0").normalize("NFD").replace(/[̀-ͯ]/g, "").replace(/\0/g, "Ñ")
    .replace(/[^A-Z0-9Ñ&]+/g, " ").split(" ").filter((w) => w && !/^\d+$/.test(w)).join(" ");
}

async function catalogo(clienteId: string): Promise<CuentaCatalogo[]> {
  const supabase = await crearClienteServidor();
  const { data } = await supabase.from("clientes").select("config").eq("id", clienteId).maybeSingle();
  return ((data?.config as { catalogo?: CuentaCatalogo[] } | null)?.catalogo ?? []);
}

export async function crearRegla(f: FormData) {
  const perfil = await perfilActual();
  const clienteId = String(f.get("cliente_id"));
  const tipo = String(f.get("tipo"));
  const crudo = String(f.get("patron") ?? "").trim();
  const cuenta = String(f.get("cuenta") ?? "");
  const sentido = String(f.get("sentido") ?? "");
  const prioridad = Number.parseInt(String(f.get("prioridad") || "100"), 10);
  if (!TIPOS.includes(tipo)) volver(clienteId, "error", "Tipo de regla no válido");
  if (tipo === "regex") {
    try { new RegExp(crudo); } catch { volver(clienteId, "error", "La expresión regular no es válida"); }
  }
  const patron = tipo === "regex" ? crudo : normalizar(crudo);
  if (!patron) volver(clienteId, "error", "Escribe el texto de la regla");
  const cat = (await catalogo(clienteId)).find((c) => c.cuenta === cuenta);
  if (cuenta !== "__MANO__" && !cat) volver(clienteId, "error", "Elige una cuenta del catálogo");
  if (!Number.isInteger(prioridad) || prioridad < 0 || prioridad > 10000) volver(clienteId, "error", "Prioridad no válida");
  const supabase = await crearClienteServidor();
  const { error } = await supabase.from("reglas_clasificacion").insert({
    cliente_id: clienteId, tipo, patron, cuenta: cat?.cuenta ?? null, clasificacion: cat?.clasificacion ?? null,
    sentido: sentido === "ingreso" || sentido === "egreso" ? sentido : null,
    banco: String(f.get("banco") ?? "").trim().toUpperCase() || null, prioridad,
    nota: String(f.get("nota") ?? "").trim() || null, origen: "manual", creada_por: perfil.id,
  });
  if (error) {
    volver(clienteId, "error", error.code === "23505" ? "Ya existe una regla activa igual" : "No se pudo crear la regla");
  }
  revalidatePath(`/clientes/${clienteId}/reglas`);
  volver(clienteId, "ok", `Regla creada: «${patron}»`, patron);
}

export async function cambiarRegla(f: FormData) {
  await perfilActual();
  const clienteId = String(f.get("cliente_id"));
  const id = String(f.get("id"));
  const q = String(f.get("q") ?? "");
  const supabase = await crearClienteServidor();
  let datos: Record<string, unknown>;
  if (f.has("activa")) {
    datos = { activa: f.get("activa") === "true" };
  } else {
    const cuenta = String(f.get("cuenta") ?? "");
    const cat = (await catalogo(clienteId)).find((c) => c.cuenta === cuenta);
    if (cuenta !== "__MANO__" && !cat) volver(clienteId, "error", "Elige una cuenta del catálogo", q);
    datos = { cuenta: cat?.cuenta ?? null, clasificacion: cat?.clasificacion ?? null };
  }
  const { error } = await supabase.from("reglas_clasificacion").update(datos).eq("id", id).eq("cliente_id", clienteId);
  if (error) {
    volver(clienteId, "error", error.code === "23505" ? "Ya hay otra regla activa igual" : "No se pudo cambiar la regla", q);
  }
  revalidatePath(`/clientes/${clienteId}/reglas`);
  volver(clienteId, "ok", "Regla actualizada", q);
}
