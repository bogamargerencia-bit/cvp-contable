"use server";

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";
import { exigirAdmin, perfilActual } from "@/lib/sesion";
import { crearClienteServidor } from "@/lib/supabase/server";
import { BANCOS, CONFIGS_PARSER } from "@/lib/tipos";

const txt = (f: FormData, k: string) => {
  const v = String(f.get(k) ?? "").trim();
  return v === "" ? null : v;
};
function err(ruta: string, m: string): never {
  redirect(`${ruta}?error=${encodeURIComponent(m)}`);
}

/** RIF venezolano: letra (J, V, E, G, P, C) + 8 dígitos + dígito verificador; se guarda «J-12345678-9». */
function normalizarRif(v: string | null): string | null {
  if (!v) return null;
  const s = v.toUpperCase().replace(/[^A-Z0-9]/g, "");
  const m = s.match(/^([JVEGPC])(\d{8})(\d)$/);
  return m ? `${m[1]}-${m[2]}-${m[3]}` : "INVALIDO";
}

export async function crearCliente(f: FormData) {
  const perfil = await exigirAdmin();
  const nombre = txt(f, "nombre");
  const rif = normalizarRif(txt(f, "rif"));
  const clave = txt(f, "clave_config");
  if (!nombre) err("/clientes/nuevo", "La razón social es obligatoria");
  if (rif === "INVALIDO") err("/clientes/nuevo", "RIF inválido. Formato esperado: J-12345678-9");
  if (clave && !CONFIGS_PARSER.includes(clave)) err("/clientes/nuevo", "Configuración del parser desconocida");

  const supabase = await crearClienteServidor();
  const { data, error } = await supabase
    .from("clientes")
    .insert({ nombre, nombre_comercial: txt(f, "nombre_comercial"), rif, clave_config: clave, creado_por: perfil.id })
    .select("id")
    .single();
  if (error) err("/clientes/nuevo", error.code === "23505" ? "Ya existe un cliente con ese RIF" : "No se pudo crear el cliente");
  revalidatePath("/");
  redirect(`/clientes/${data!.id}?ok=${encodeURIComponent("Cliente creado. Agrega sus cuentas.")}`);
}

export async function cambiarEstadoCliente(f: FormData) {
  await exigirAdmin();
  const id = String(f.get("id"));
  const activo = f.get("activo") === "true";
  const supabase = await crearClienteServidor();
  const { error } = await supabase.from("clientes").update({ activo }).eq("id", id);
  if (error) err(`/clientes/${id}`, "No se pudo cambiar el estado");
  revalidatePath(`/clientes/${id}`);
  revalidatePath("/");
}

export async function crearCuenta(f: FormData) {
  await exigirAdmin();
  const cliente_id = String(f.get("cliente_id"));
  const ruta = `/clientes/${cliente_id}`;
  const { error: invalido, datos } = datosCuenta(f);
  if (invalido) err(ruta, invalido);
  const supabase = await crearClienteServidor();
  const { error } = await supabase.from("cuentas").insert({ cliente_id, ...datos });
  if (error) err(ruta, "No se pudo crear la cuenta");
  revalidatePath(ruta);
  redirect(`${ruta}?ok=${encodeURIComponent("Cuenta agregada")}`);
}

export async function crearPeriodo(f: FormData) {
  await perfilActual();
  const cliente_id = String(f.get("cliente_id"));
  const ruta = `/clientes/${cliente_id}`;
  const [anio, mes] = String(f.get("mes") ?? "").split("-").map(Number);
  if (!anio || !mes) err(ruta, "Elige el mes");

  const supabase = await crearClienteServidor();
  const { error } = await supabase.from("periodos").insert({ cliente_id, anio, mes });
  if (error) err(ruta, error.code === "23505" ? "Ese período ya existe" : "No se pudo crear el período");
  revalidatePath(ruta);
  redirect(`${ruta}?ok=${encodeURIComponent("Período creado")}`);
}

/** Datos de una cuenta desde el formulario (crear o editar). Devuelve el error a mostrar, si lo hay. */
function datosCuenta(f: FormData) {
  const tipo = f.get("tipo") === "divisa" ? "divisa" : "banco";
  const banco = txt(f, "banco");
  const nombre = txt(f, "nombre");
  const numero = txt(f, "numero")?.replace(/\D/g, "") ?? null;
  let error = "";
  if (!nombre) error = "El nombre de la cuenta es obligatorio";
  else if (tipo === "banco" && !BANCOS.some((b) => b.codigo === banco)) error = "Elige el banco";
  else if (numero && numero.length !== 20) error = "El número de cuenta debe tener 20 dígitos";
  return {
    error,
    datos: {
      tipo,
      banco: tipo === "banco" ? banco : null,
      nombre,
      numero,
      titular: txt(f, "titular"),
      es_personal: f.get("es_personal") === "on",
      moneda: tipo === "divisa" ? "USD" : "VES",
    },
  };
}

/** Editar una cuenta. El número solo cambia si se escribe uno nuevo (la pantalla nunca muestra el completo). */
export async function editarCuenta(f: FormData) {
  await exigirAdmin();
  const cliente_id = String(f.get("cliente_id"));
  const id = String(f.get("id"));
  const ruta = `/clientes/${cliente_id}`;
  const { error: invalido, datos } = datosCuenta(f);
  if (invalido) redirect(`${ruta}?editar=${id}&error=${encodeURIComponent(invalido)}`);
  const { numero, ...resto } = datos;
  const cambios = { ...resto, activo: f.get("activo") === "on", ...(numero ? { numero } : {}) };
  if (f.get("borrar_numero") === "on") Object.assign(cambios, { numero: null });

  const supabase = await crearClienteServidor();
  const { error } = await supabase.from("cuentas").update(cambios).eq("id", id).eq("cliente_id", cliente_id);
  if (error) err(ruta, "No se pudo guardar la cuenta");
  revalidatePath(ruta);
  redirect(`${ruta}?ok=${encodeURIComponent("Cuenta actualizada")}`);
}

/** Eliminar una cuenta: solo si nunca se le subió un archivo; si tiene historia, se desactiva. */
export async function eliminarCuenta(f: FormData) {
  await exigirAdmin();
  const cliente_id = String(f.get("cliente_id"));
  const id = String(f.get("id"));
  const ruta = `/clientes/${cliente_id}`;
  const supabase = await crearClienteServidor();
  const { count } = await supabase.from("archivos").select("id", { count: "exact", head: true }).eq("cuenta_id", id);
  if (count) {
    err(ruta, `La cuenta tiene ${count} archivo(s) subidos: no se elimina para conservar la historia. `
      + "Desmarca «Activa» para que deje de aparecer en los períodos.");
  }
  const { error } = await supabase.from("cuentas").delete().eq("id", id).eq("cliente_id", cliente_id);
  if (error) err(ruta, "No se pudo eliminar la cuenta");
  revalidatePath(ruta);
  redirect(`${ruta}?ok=${encodeURIComponent("Cuenta eliminada")}`);
}

/** Editar los datos del cliente, incluidas las reglas del parser. */
export async function editarCliente(f: FormData) {
  await exigirAdmin();
  const id = String(f.get("id"));
  const ruta = `/clientes/${id}`;
  const nombre = txt(f, "nombre");
  const rif = normalizarRif(txt(f, "rif"));
  const clave = txt(f, "clave_config");
  if (!nombre) err(ruta, "La razón social es obligatoria");
  if (rif === "INVALIDO") err(ruta, "RIF inválido. Formato esperado: J-12345678-9");
  if (clave && !CONFIGS_PARSER.includes(clave)) err(ruta, "Configuración del parser desconocida");

  const supabase = await crearClienteServidor();
  const { error } = await supabase.from("clientes")
    .update({ nombre, nombre_comercial: txt(f, "nombre_comercial"), rif, clave_config: clave }).eq("id", id);
  if (error) err(ruta, error.code === "23505" ? "Ya existe un cliente con ese RIF" : "No se pudo guardar el cliente");
  revalidatePath(ruta);
  revalidatePath("/");
  redirect(`${ruta}?ok=${encodeURIComponent("Datos del cliente actualizados")}`);
}
