"""Comisiones, cargos bancarios y retenciones de ISLR en cobros POS: se agrupan aparte.

No se intentan conciliar movimiento por movimiento ni contra un asiento: se totalizan por banco
(y por tipo, según la descripción del banco) para que el analista compare cada total del mes con el
asiento que se registra en el sistema (un total por banco al mes). Solo entra lo que quedó «solo en banco»:
si el libro ya trae un asiento que la conciliación emparejó, ese movimiento no se repite aquí.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal
from typing import TYPE_CHECKING

from .conciliacion import NO_CONCILIAR, EstadoPartida as EP
from .modelo import Movimiento
from .montos import CERO
from .naturaleza import S_CARGOS, S_COMISION, S_ISLR

if TYPE_CHECKING:
    from .proceso import ReporteCliente

# Orden en que se muestran las categorías (las mismas que la conciliación deja fuera).
CATEGORIAS = [S_ISLR, S_COMISION, S_CARGOS]
assert set(CATEGORIAS) == NO_CONCILIAR


def tipo_de(m: Movimiento) -> str:
    """Tipo dentro de la categoría: la descripción del banco sin números de referencia (4+ dígitos)."""
    t = re.sub(r"\b\d{4,}\b", " ", m.descripcion or "")
    t = re.sub(r"\s+", " ", t).strip(" -.:")
    return t or "Sin descripción"


@dataclass
class Tipo:
    nombre: str
    movimientos: list[Movimiento] = field(default_factory=list)

    @property
    def total(self) -> Decimal:
        """Neto en Bs.: salidas en negativo (un reverso del banco resta)."""
        return sum((m.credito - m.debito for m in self.movimientos), CERO)


@dataclass
class Categoria:
    banco: str
    nombre: str                                  # S_ISLR / S_COMISION / S_CARGOS
    tipos: list[Tipo] = field(default_factory=list)

    @property
    def movimientos(self) -> list[Movimiento]:
        return [m for t in self.tipos for m in t.movimientos]

    @property
    def total(self) -> Decimal:
        return sum((t.total for t in self.tipos), CERO)


def por_conciliar(rep: "ReporteCliente", excluir: set[tuple[str, int]] = frozenset()) -> list[Categoria]:
    """Una Categoria por banco y categoría con movimientos «solo en banco», tipos ordenados por monto."""
    out: list[Categoria] = []
    for b in rep.bancos:
        rc = rep.conciliaciones[b]
        por_cat: dict[str, dict[str, Tipo]] = {}
        for x in rep.clasificados[b]:
            if x.naturaleza not in CATEGORIAS or (b, x.indice) in excluir:
                continue
            p = rc.estado_mov.get(x.indice)
            if not p or p.estado is not EP.SOLO_BANCO:
                continue
            tipos = por_cat.setdefault(x.naturaleza, {})
            nombre = tipo_de(x.mov)
            tipos.setdefault(nombre, Tipo(nombre)).movimientos.append(x.mov)
        for cat in CATEGORIAS:
            if cat in por_cat:
                tipos = sorted(por_cat[cat].values(), key=lambda t: (t.total, t.nombre))
                out.append(Categoria(b, cat, tipos))
    return out
