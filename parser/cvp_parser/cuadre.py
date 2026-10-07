"""Cuadre de extractos contra el banco.

Validaciones (todas en Decimal, comparación exacta, sin tolerancia):
  1. Errores de lectura del lector: cualquiera impide dar el extracto por cuadrado.
  2. Saldo línea por línea: saldo previo − débito + crédito = saldo impreso.
     Tras una diferencia se continúa desde el saldo del banco, para que un solo
     error no se arrastre a todas las líneas siguientes.
  3. Totales contra el resumen del banco: saldo anterior, débitos, créditos,
     número de operaciones y nuevo saldo.
  4. Ecuación global: saldo anterior − débitos + créditos = nuevo saldo del banco.
  5. Continuidad: el saldo anterior de un mes = nuevo saldo del mes previo de la
     misma cuenta.

Nada se ajusta. Las diferencias se informan con dónde están y por cuánto.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from typing import Iterable, Optional

from .modelo import Extracto, Origen
from .montos import formato_ve


class Estado(str, Enum):
    CUADRA = "cuadra"
    # Cuadra, pero incluye montos deducidos (no impresos) o datos que el banco
    # no trae para verificar. Un analista debe revisarlo antes de darlo por bueno.
    REQUIERE_REVISION = "requiere_revision"
    NO_CUADRA = "no_cuadra"


class TipoDiferencia(str, Enum):
    ERROR_LECTURA = "error_lectura"
    SALDO_LINEA = "saldo_linea"
    SALDO_ANTERIOR = "saldo_anterior"
    TOTAL_DEBITOS = "total_debitos"
    TOTAL_CREDITOS = "total_creditos"
    NRO_OPERACIONES = "nro_operaciones"
    NRO_DEBITOS = "nro_debitos"
    NRO_CREDITOS = "nro_creditos"
    NUEVO_SALDO = "nuevo_saldo"
    CONTINUIDAD = "continuidad"
    SIN_RESUMEN = "sin_resumen"


class TipoAviso(str, Enum):
    MONTO_DEDUCIDO = "monto_deducido"
    NO_VERIFICABLE = "no_verificable"
    SIN_SALDOS_LINEA = "sin_saldos_linea"
    OBSERVACION = "observacion"


@dataclass
class Diferencia:
    tipo: TipoDiferencia
    mensaje: str
    linea: Optional[int] = None          # nº de movimiento (1 = primero)
    esperado: Optional[Decimal] = None   # según el banco
    obtenido: Optional[Decimal] = None   # calculado del detalle

    @property
    def diferencia(self) -> Optional[Decimal]:
        if self.esperado is None or self.obtenido is None:
            return None
        return self.obtenido - self.esperado


@dataclass
class Aviso:
    tipo: TipoAviso
    mensaje: str
    linea: Optional[int] = None


@dataclass
class ResultadoCuadre:
    extracto: Extracto
    diferencias: list[Diferencia] = field(default_factory=list)
    avisos: list[Aviso] = field(default_factory=list)
    total_debitos: Decimal = Decimal("0.00")
    total_creditos: Decimal = Decimal("0.00")
    nuevo_saldo_calculado: Decimal = Decimal("0.00")

    @property
    def estado(self) -> Estado:
        if self.diferencias:
            return Estado.NO_CUADRA
        if self.avisos:
            return Estado.REQUIERE_REVISION
        return Estado.CUADRA

    @property
    def cuadra(self) -> bool:
        """True solo si no hay ninguna diferencia (puede tener avisos)."""
        return not self.diferencias


def _ve(d: Optional[Decimal]) -> str:
    return "—" if d is None else formato_ve(d)


def cuadrar_extracto(e: Extracto) -> ResultadoCuadre:
    r = ResultadoCuadre(extracto=e)

    # 1. Errores de lectura
    for err in e.errores_lectura:
        r.diferencias.append(Diferencia(TipoDiferencia.ERROR_LECTURA, f"Línea no leída: {err}"))
    for obs in e.avisos_lectura:
        r.avisos.append(Aviso(TipoAviso.OBSERVACION, obs))

    # 2. Saldo línea por línea
    saldo = e.saldo_anterior
    lineas_con_saldo = 0
    for i, m in enumerate(e.movimientos, 1):
        saldo = saldo - m.debito + m.credito
        if m.origen is Origen.DEDUCIDO:
            monto = m.debito or m.credito
            r.avisos.append(Aviso(
                TipoAviso.MONTO_DEDUCIDO,
                f"Movimiento {i} ({m.fecha_contable:%d/%m/%Y}) no impreso por el banco; "
                f"monto {_ve(monto)} deducido por diferencia de saldo"
                + (f" ({m.nota})" if m.nota else ""),
                linea=i,
            ))
        if m.saldo is None:
            continue
        lineas_con_saldo += 1
        if saldo != m.saldo:
            r.diferencias.append(Diferencia(
                TipoDiferencia.SALDO_LINEA,
                f"Movimiento {i} ({m.fecha_contable:%d/%m/%Y}, {m.descripcion}): "
                f"saldo calculado {_ve(saldo)} vs. banco {_ve(m.saldo)} "
                f"(diferencia {_ve(saldo - m.saldo)})",
                linea=i, esperado=m.saldo, obtenido=saldo,
            ))
            saldo = m.saldo  # continuar desde el saldo del banco
    if e.movimientos and lineas_con_saldo == 0:
        r.avisos.append(Aviso(
            TipoAviso.SIN_SALDOS_LINEA,
            "El banco no imprime saldos por línea; solo se verifican los totales.",
        ))

    # Totales del detalle
    r.total_debitos = sum((m.debito for m in e.movimientos), Decimal("0.00"))
    r.total_creditos = sum((m.credito for m in e.movimientos), Decimal("0.00"))
    r.nuevo_saldo_calculado = e.saldo_anterior - r.total_debitos + r.total_creditos

    # 3 y 4. Contra el resumen del banco
    tb = e.totales_banco
    if tb is None:
        r.diferencias.append(Diferencia(
            TipoDiferencia.SIN_RESUMEN,
            "No se encontró el resumen del banco; el extracto no se puede verificar.",
        ))
        return r

    def comparar_monto(tipo: TipoDiferencia, nombre: str,
                       banco: Optional[Decimal], calculado: Decimal) -> None:
        if banco is None:
            r.avisos.append(Aviso(TipoAviso.NO_VERIFICABLE,
                                  f"{nombre}: el banco no lo informa; no se pudo verificar."))
        elif banco != calculado:
            r.diferencias.append(Diferencia(
                tipo,
                f"{nombre}: banco {_ve(banco)} vs. detalle {_ve(calculado)} "
                f"(diferencia {_ve(calculado - banco)})",
                esperado=banco, obtenido=calculado,
            ))

    def comparar_conteo(tipo: TipoDiferencia, nombre: str,
                        banco: Optional[int], calculado: int) -> None:
        if banco is not None and banco != calculado:
            r.diferencias.append(Diferencia(
                tipo,
                f"{nombre}: banco {banco} vs. detalle {calculado} "
                f"(diferencia {calculado - banco:+d})",
                esperado=Decimal(banco), obtenido=Decimal(calculado),
            ))

    if tb.saldo_anterior is None:
        r.avisos.append(Aviso(TipoAviso.NO_VERIFICABLE,
                              "Saldo anterior: el banco no lo informa; se dedujo de la primera línea."))
    elif tb.saldo_anterior != e.saldo_anterior:
        r.diferencias.append(Diferencia(
            TipoDiferencia.SALDO_ANTERIOR,
            f"Saldo anterior: resumen {_ve(tb.saldo_anterior)} vs. "
            f"encabezado/detalle {_ve(e.saldo_anterior)}",
            esperado=tb.saldo_anterior, obtenido=e.saldo_anterior,
        ))
    comparar_monto(TipoDiferencia.TOTAL_DEBITOS, "Total débitos", tb.total_debitos, r.total_debitos)
    comparar_monto(TipoDiferencia.TOTAL_CREDITOS, "Total créditos", tb.total_creditos, r.total_creditos)

    n_deb = sum(1 for m in e.movimientos if m.debito)
    n_cre = sum(1 for m in e.movimientos if m.credito)
    comparar_conteo(TipoDiferencia.NRO_OPERACIONES, "Nº de operaciones",
                    tb.nro_operaciones, len(e.movimientos))
    comparar_conteo(TipoDiferencia.NRO_DEBITOS, "Nº de débitos", tb.nro_debitos, n_deb)
    comparar_conteo(TipoDiferencia.NRO_CREDITOS, "Nº de créditos", tb.nro_creditos, n_cre)
    if tb.nro_operaciones is None and tb.nro_debitos is None and tb.nro_creditos is None:
        r.avisos.append(Aviso(TipoAviso.NO_VERIFICABLE,
                              "Nº de operaciones: el banco no lo informa; no se pudo verificar."))

    comparar_monto(TipoDiferencia.NUEVO_SALDO, "Nuevo saldo", tb.nuevo_saldo, r.nuevo_saldo_calculado)
    return r


def cuadrar(extractos: Iterable[Extracto]) -> list[ResultadoCuadre]:
    """Cuadra cada extracto y verifica la continuidad entre meses por cuenta.

    Devuelve los resultados ordenados por banco, cuenta y fecha de corte.
    """
    ordenados = sorted(extractos, key=lambda e: e.clave)
    resultados = [cuadrar_extracto(e) for e in ordenados]

    vistos: set[tuple[str, str, object]] = set()
    previo: Optional[ResultadoCuadre] = None
    for r in resultados:
        e = r.extracto
        if e.clave in vistos:
            r.diferencias.append(Diferencia(
                TipoDiferencia.CONTINUIDAD,
                f"Extracto duplicado: ya hay otro de {e.banco} cuenta {e.cuenta} "
                f"con corte {e.hasta:%d/%m/%Y}.",
            ))
        vistos.add(e.clave)
        if previo is not None and (previo.extracto.banco, previo.extracto.cuenta) == (e.banco, e.cuenta):
            pe = previo.extracto
            saldo_previo = (pe.totales_banco.nuevo_saldo
                            if pe.totales_banco and pe.totales_banco.nuevo_saldo is not None
                            else previo.nuevo_saldo_calculado)
            if saldo_previo != e.saldo_anterior:
                r.diferencias.append(Diferencia(
                    TipoDiferencia.CONTINUIDAD,
                    f"Saldo anterior {_ve(e.saldo_anterior)} no coincide con el nuevo saldo "
                    f"del corte {pe.hasta:%d/%m/%Y} ({_ve(saldo_previo)}). ¿Falta un mes?",
                    esperado=saldo_previo, obtenido=e.saldo_anterior,
                ))
        previo = r
    return resultados
