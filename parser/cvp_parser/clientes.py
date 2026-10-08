"""Configuración por cliente: lo que cambia de un cliente a otro y no se puede deducir con seguridad.

  - medios de caja: qué columna del cierre de caja va a qué banco(s), de qué tipo es y cómo se cruza:
      «desglose»     cada sumando de la fórmula es un pago del banco (WEI REST: pago móvil);
      «lote»         tarjetas: el total del día es un lote (o 2-3) abonado entre D+1 y D+4 (WEI REST, BNC);
      «total_diario» el total del día contra los créditos del banco de ese día; el fin de semana se abona
                     el lunes (CACAO: pago móvil Banplus sin desglose);
      «total_mes»    tarjetas sin correspondencia diaria exacta: se concilia el total del mes, separando
                     las ventas del mes anterior y lo que queda por abonar (CACAO: Banplus + Plaza).
  - asientos resumen del libro: qué asientos (por banco y texto) corresponden a qué columna de caja.

Si un cliente no está aquí se usa la detección automática por nombre de columna (como en WEI REST).
En la Fase 2 esto vivirá en la base de datos (tabla de configuración por cliente).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .divisas import CuentaDivisa
from .ventas import PAGO_MOVIL, POS, VUELTO


@dataclass
class MedioCaja:
    columna: str                  # encabezado de la columna en el cierre de caja
    bancos: list[str]
    tipo: str                     # pos / pago_movil / vuelto
    modo: str                     # desglose / lote / total_diario / total_mes
    nombre: Optional[str] = None  # cómo se muestra; por defecto el encabezado


@dataclass
class AsientoResumen:
    """Asientos del libro (de uno o varios bancos) que suman lo de una o más columnas de caja."""
    medios: list[str]                         # columnas de caja
    asientos: list[tuple[str, str]]           # (banco, regex sobre la descripción)


@dataclass
class ConfigCliente:
    nombre: str
    medios: list[MedioCaja] = field(default_factory=list)       # vacío = detección automática
    asientos_resumen: list[AsientoResumen] = field(default_factory=list)
    divisas: list[CuentaDivisa] = field(default_factory=list)   # cuentas en US$ (efectivo, Zelle, USDT…)


CLIENTES: dict[str, ConfigCliente] = {
    "WEI REST": ConfigCliente(
        nombre="ALIMENTOS SIERRA DEL SOL, C.A.",
        # Caja de bancos: detección automática por nombre de columna (medios vacío).
        divisas=[
            CuentaDivisa("Efectivo $", r"RECIBIDOS EN EFECTIVO", "DIVISAS"),
            CuentaDivisa("Zelle", r"RECIBIDOS EN\s+ZELLE", "ZELLE"),
            CuentaDivisa("USDT", r"RECIBIDOS EN USDT", "USDT"),
            CuentaDivisa("Fondo de efectivo", None, "FONDO"),
        ],
    ),
    "CACAO": ConfigCliente(
        nombre="CACAO COFFEE NG, C.A.",
        medios=[
            # El POS de la cuenta personal de Johana Gil (Plaza) se registra en caja como PUNTO CACAO;
            # la columna PUNTO JOHANA GIL viene en cero (agosto 2026).
            MedioCaja("PUNTO CACAO", ["BANPLUS", "PLAZA"], POS, "total_mes", "Punto Cacao"),
            MedioCaja("PUNTO JOHANA GIL", ["PLAZA"], POS, "total_mes", "Punto Johana Gil"),
            MedioCaja("PAGO MOVIL", ["BANPLUS"], PAGO_MOVIL, "total_diario", "Pago móvil"),
        ],
        asientos_resumen=[
            AsientoResumen(["Pago móvil"], [("BANPLUS", r"PAGO MOVIL")]),
            AsientoResumen(["Punto Cacao", "Punto Johana Gil"],
                           [("BANPLUS", r"PUNTO DE VENTAS"), ("PLAZA", r"PUNTO DE VENTAS")]),
        ],
    ),
    "SHIRO": ConfigCliente(
        nombre="SHIRO ALIMENTOS, C.A.",
        # Sin cierre de caja: las ventas del mes salen del Kardex (PDF) y se controlan contra el asiento mensual
        # («INGRESO POR VENTAS AGOSTO 2026», agosto 2026).
        divisas=[
            CuentaDivisa("Efectivo $", None, "DIVISAS", asiento_ventas=r"INGRESO POR VENTAS|VTAS", ventas_del_kardex=True),
            CuentaDivisa("Zelle", None, "ZELLE", asiento_ventas=r"INGRESO POR VENTAS|VTAS", ventas_del_kardex=True),
        ],
    ),
}


def config_de(cliente: str) -> Optional[ConfigCliente]:
    """Busca la configuración por clave o por coincidencia en el nombre del cliente."""
    c = cliente.upper()
    for clave, cfg in CLIENTES.items():
        if clave in c or cfg.nombre.upper() in c:
            return cfg
    return None
