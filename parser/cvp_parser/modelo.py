"""Modelo de datos común a todos los lectores de bancos.

Cada lector (Activo, Mercantil, ...) recibe uno o varios PDF y devuelve un
ResultadoLectura con uno o más Extractos (uno por cuenta y período). El módulo
de cuadre trabaja solo con este modelo, sin saber de qué banco viene.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Optional, Protocol, Sequence

from .montos import CERO, MontoInvalido, a_monto


class Origen(str, Enum):
    """De dónde sale el monto de un movimiento."""

    IMPRESO = "impreso"    # el monto está impreso en el PDF
    DEDUCIDO = "deducido"  # el banco no lo imprimió; se dedujo por diferencia de saldo


@dataclass
class Movimiento:
    fecha_contable: dt.date
    descripcion: str
    debito: Decimal = CERO
    credito: Decimal = CERO
    # Saldo impreso por el banco después de este movimiento. Algunos bancos
    # (Mercantil) solo imprimen saldo al final del día: entonces es None.
    saldo: Optional[Decimal] = None
    fecha_real: Optional[dt.date] = None
    referencia: str = ""
    detalle: str = ""
    origen: Origen = Origen.IMPRESO
    nota: str = ""          # p. ej. "monto combinado de 2 movimientos no impresos"
    pagina: Optional[int] = None

    def __post_init__(self) -> None:
        self.debito = a_monto(self.debito)
        self.credito = a_monto(self.credito)
        if self.saldo is not None:
            self.saldo = a_monto(self.saldo)
        if self.debito < 0 or self.credito < 0:
            raise MontoInvalido(
                f"Débito y crédito deben ser positivos ({self.descripcion}): "
                f"débito {self.debito}, crédito {self.credito}"
            )
        if self.debito and self.credito:
            raise MontoInvalido(
                f"Un movimiento no puede tener débito y crédito a la vez ({self.descripcion})"
            )

    @property
    def neto(self) -> Decimal:
        """Efecto sobre el saldo: crédito − débito."""
        return self.credito - self.debito


@dataclass
class TotalesBanco:
    """Resumen impreso por el banco. Lo que el banco no imprime queda en None
    y el cuadre lo reporta como "no verificable", nunca como cuadrado."""

    saldo_anterior: Optional[Decimal] = None
    nuevo_saldo: Optional[Decimal] = None
    total_debitos: Optional[Decimal] = None
    total_creditos: Optional[Decimal] = None
    nro_operaciones: Optional[int] = None   # Activo: un solo conteo
    nro_debitos: Optional[int] = None       # Mercantil: conteos separados
    nro_creditos: Optional[int] = None

    def __post_init__(self) -> None:
        for campo in ("saldo_anterior", "nuevo_saldo", "total_debitos", "total_creditos"):
            v = getattr(self, campo)
            if v is not None:
                setattr(self, campo, a_monto(v))


@dataclass
class Extracto:
    """Un estado de cuenta: una cuenta y un período."""

    banco: str
    cuenta: str
    desde: Optional[dt.date]
    hasta: dt.date                   # fecha de corte
    saldo_anterior: Decimal          # saldo inicial con el que arranca el detalle
    movimientos: list[Movimiento] = field(default_factory=list)
    totales_banco: Optional[TotalesBanco] = None
    titular: str = ""
    moneda: str = "VES"
    archivo: str = ""
    # Líneas que parecían movimientos pero el lector no pudo interpretar.
    # Cualquier error de lectura impide que el extracto se dé por cuadrado.
    errores_lectura: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.saldo_anterior = a_monto(self.saldo_anterior)

    @property
    def clave(self) -> tuple[str, str, dt.date]:
        """Identifica el extracto: banco + cuenta + fecha de corte."""
        return (self.banco, self.cuenta, self.hasta)


@dataclass
class ResultadoLectura:
    extractos: list[Extracto]
    # Errores que no pertenecen a ningún extracto (p. ej. una página sin encabezado).
    errores_generales: list[str] = field(default_factory=list)


class Lector(Protocol):
    """Interfaz que implementa cada lector de banco."""

    banco: str

    def reconoce(self, ruta: Path) -> bool:
        """True si el PDF parece de este banco (para la detección automática)."""
        ...

    def leer(self, rutas: Sequence[Path]) -> ResultadoLectura:
        """Lee uno o varios PDF y devuelve los extractos encontrados."""
        ...
