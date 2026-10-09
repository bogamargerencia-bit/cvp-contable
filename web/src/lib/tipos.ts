// Tipos de las tablas que usa la web (ver supabase/migrations).
// Los montos (numeric 18,2) NO se tipan como number: se leen como texto (monto::text) para no perder céntimos.

export type Rol = "admin" | "analista";

export interface Perfil {
  id: string;
  email: string;
  nombre: string | null;
  rol: Rol;
  activo: boolean;
  creado_en: string;
}

export interface Cliente {
  id: string;
  nombre: string;
  nombre_comercial: string | null;
  rif: string | null;
  clave_config: string | null;
  config: { modo?: Modo } | null;
  activo: boolean;
  creado_en: string;
}

/** Tipo de servicio: conciliación completa, o solo conversión de estados de cuenta a Excel. */
export type Modo = "conciliacion" | "conversion";
export const MODOS: { valor: Modo; nombre: string; ayuda: string }[] = [
  { valor: "conciliacion", nombre: "Conciliación", ayuda: "Estados de cuenta + libro del sistema, caja y divisas." },
  { valor: "conversion", nombre: "Solo conversión a Excel", ayuda: "Solo estados de cuenta: Excel con resumen por ítem." },
];
export const modoDe = (c: { config?: { modo?: string } | null }): Modo =>
  c.config?.modo === "conversion" ? "conversion" : "conciliacion";

export interface Cuenta {
  id: string;
  cliente_id: string;
  tipo: "banco" | "divisa";
  banco: string | null;
  nombre: string;
  numero: string | null;
  titular: string | null;
  es_personal: boolean;
  moneda: "VES" | "USD";
  activo: boolean;
}

export interface Periodo {
  id: string;
  cliente_id: string;
  anio: number;
  mes: number;
  estado: "abierto" | "cerrado";
  cerrado_en: string | null;
  creado_en: string;
}

/** Lectores del parser (cvp_parser/lectores). Los marcados «pendiente» aún no tienen lector. */
export const BANCOS: { codigo: string; nombre: string; pendiente?: boolean }[] = [
  { codigo: "100_BANCO", nombre: "100% Banco" },
  { codigo: "BNC", nombre: "BNC" },
  { codigo: "BANPLUS", nombre: "Banplus" },
  { codigo: "PLAZA", nombre: "Banco Plaza" },
  { codigo: "VENEZOLANO", nombre: "Venezolano de Crédito" },
  { codigo: "BANCAMIGA", nombre: "Bancamiga" },
  { codigo: "ACTIVO", nombre: "Banco Activo", pendiente: true },
  { codigo: "MERCANTIL", nombre: "Mercantil", pendiente: true },
];

/** Claves de configuración que existen en parser/cvp_parser/clientes.py. */
export const CONFIGS_PARSER = ["WEI REST", "CACAO", "SHIRO"];

/** Nombres de las cuentas en divisas que reconoce el parser para cada configuración (clientes.py). */
export const DIVISAS_PARSER: Record<string, string[]> = {
  "WEI REST": ["Efectivo $", "Zelle", "USDT", "Fondo de efectivo"],
  SHIRO: ["Efectivo $", "Zelle"],
};

export const MESES = [
  "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
  "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre",
];

export function nombreBanco(codigo: string | null): string {
  return BANCOS.find((b) => b.codigo === codigo)?.nombre ?? codigo ?? "—";
}

/** Minutos que una corrida puede quedar «en cola» antes de darla por no tomada por el servicio. */
export const MINUTOS_EN_COLA = 3;

/** Hora actual (servidor). Separada para que los componentes no llamen a Date.now() directamente. */
export function ahoraMs(): number {
  return Date.now();
}
