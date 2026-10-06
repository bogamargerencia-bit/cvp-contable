"""Pruebas del módulo de cuadre con extractos sintéticos.

Las pruebas con PDF reales van en tests/test_lector_*.py (piezas 2 y 3).
"""
import datetime as dt
from decimal import Decimal as D

import pytest

from cvp_parser import (
    Estado, Extracto, MontoInvalido, Movimiento, Origen, TotalesBanco, cuadrar, cuadrar_extracto,
)
from cvp_parser.cuadre import TipoAviso, TipoDiferencia


def f(dia, mes=1, anio=2026):
    return dt.date(anio, mes, dia)


def extracto_ok(**cambios):
    """Extracto de enero que cuadra al céntimo: 1.000,00 − 150,25 + 500,10 − 0,05 = 1.349,80."""
    movs = [
        Movimiento(f(2), "PAGO PROVEEDOR", debito=D("150.25"), saldo=D("849.75")),
        Movimiento(f(3), "TRANSFERENCIA RECIBIDA", credito=D("500.10"), saldo=D("1349.85")),
        Movimiento(f(3), "COMIS. TCBS", debito=D("0.05"), saldo=D("1349.80")),
    ]
    datos = dict(
        banco="ACTIVO", cuenta="0171-0001", desde=f(1), hasta=f(31),
        saldo_anterior=D("1000.00"), movimientos=movs,
        totales_banco=TotalesBanco(
            saldo_anterior=D("1000.00"), nuevo_saldo=D("1349.80"),
            total_debitos=D("150.30"), total_creditos=D("500.10"), nro_operaciones=3,
        ),
    )
    datos.update(cambios)
    return Extracto(**datos)


# ---------------------------------------------------------------- caso bueno

def test_extracto_que_cuadra():
    r = cuadrar_extracto(extracto_ok())
    assert r.estado is Estado.CUADRA
    assert r.diferencias == [] and r.avisos == []
    assert r.total_debitos == D("150.30")
    assert r.total_creditos == D("500.10")
    assert r.nuevo_saldo_calculado == D("1349.80")


# ---------------------------------------------------------------- diferencias

def test_saldo_linea_senala_la_linea_y_no_arrastra_el_error():
    e = extracto_ok()
    # El banco imprime 849,76 en la línea 1 (un céntimo distinto); las demás están bien.
    e.movimientos[0].saldo = D("849.76")
    r = cuadrar_extracto(e)
    lineas = [d for d in r.diferencias if d.tipo is TipoDiferencia.SALDO_LINEA]
    # La línea 1 no cuadra; la línea 2 tampoco, porque continúa desde el saldo del banco
    # (849,76 + 500,10 = 1.349,86 ≠ 1.349,85). Las dos quedan señaladas.
    assert [d.linea for d in lineas] == [1, 2]
    assert lineas[0].diferencia == D("-0.01")
    assert r.estado is Estado.NO_CUADRA


def test_movimiento_faltante_descuadra_totales_y_conteo():
    e = extracto_ok()
    del e.movimientos[2]  # se "pierde" la comisión de 0,05
    r = cuadrar_extracto(e)
    tipos = {d.tipo for d in r.diferencias}
    assert TipoDiferencia.TOTAL_DEBITOS in tipos
    assert TipoDiferencia.NRO_OPERACIONES in tipos
    assert TipoDiferencia.NUEVO_SALDO in tipos
    nuevo = next(d for d in r.diferencias if d.tipo is TipoDiferencia.NUEVO_SALDO)
    assert nuevo.diferencia == D("0.05")
    assert "0,05" in nuevo.mensaje


def test_error_de_lectura_impide_cuadrar_aunque_los_numeros_den():
    e = extracto_ok(errores_lectura=["02/01/2026 02/01/2026 LINEA ILEGIBLE"])
    r = cuadrar_extracto(e)
    assert r.estado is Estado.NO_CUADRA
    assert r.diferencias[0].tipo is TipoDiferencia.ERROR_LECTURA


def test_sin_resumen_del_banco_no_cuadra():
    r = cuadrar_extracto(extracto_ok(totales_banco=None))
    assert r.estado is Estado.NO_CUADRA
    assert r.diferencias[-1].tipo is TipoDiferencia.SIN_RESUMEN


def test_saldo_anterior_del_resumen_distinto_al_del_encabezado():
    e = extracto_ok()
    e.totales_banco.saldo_anterior = D("999.99")
    r = cuadrar_extracto(e)
    assert any(d.tipo is TipoDiferencia.SALDO_ANTERIOR for d in r.diferencias)


def test_conteos_separados_estilo_mercantil():
    e = extracto_ok()
    e.totales_banco.nro_operaciones = None
    e.totales_banco.nro_debitos = 2
    e.totales_banco.nro_creditos = 2  # el banco dice 2 créditos, el detalle tiene 1
    r = cuadrar_extracto(e)
    d = [d for d in r.diferencias if d.tipo is TipoDiferencia.NRO_CREDITOS]
    assert len(d) == 1 and "-1" in d[0].mensaje


# ---------------------------------------------------------------- avisos (requiere revisión)

def test_monto_deducido_cuadra_pero_requiere_revision():
    e = extracto_ok()
    e.movimientos[2].origen = Origen.DEDUCIDO
    r = cuadrar_extracto(e)
    assert r.cuadra
    assert r.estado is Estado.REQUIERE_REVISION
    assert r.avisos[0].tipo is TipoAviso.MONTO_DEDUCIDO and r.avisos[0].linea == 3


def test_banco_sin_saldos_por_linea_estilo_mercantil():
    e = extracto_ok()
    e.movimientos[0].saldo = None
    e.movimientos[1].saldo = None  # solo el saldo del cierre del día
    r = cuadrar_extracto(e)
    assert r.estado is Estado.CUADRA  # la última línea sí tiene saldo y cuadra

    for m in e.movimientos:
        m.saldo = None
    r = cuadrar_extracto(e)
    assert r.cuadra and r.estado is Estado.REQUIERE_REVISION
    assert any(a.tipo is TipoAviso.SIN_SALDOS_LINEA for a in r.avisos)


def test_total_no_informado_por_el_banco_no_se_da_por_bueno():
    e = extracto_ok()
    e.totales_banco.total_creditos = None
    r = cuadrar_extracto(e)
    assert r.estado is Estado.REQUIERE_REVISION
    assert any(a.tipo is TipoAviso.NO_VERIFICABLE for a in r.avisos)


# ---------------------------------------------------------------- continuidad entre meses

def febrero(saldo_anterior):
    return Extracto(
        banco="ACTIVO", cuenta="0171-0001", desde=f(1, 2), hasta=f(28, 2),
        saldo_anterior=saldo_anterior,
        movimientos=[Movimiento(f(5, 2), "DEPOSITO", credito=D("10.00"),
                                saldo=saldo_anterior + D("10.00"))],
        totales_banco=TotalesBanco(saldo_anterior=saldo_anterior, nuevo_saldo=saldo_anterior + D("10.00"),
                                   total_debitos=D("0"), total_creditos=D("10.00"),
                                   nro_operaciones=1),
    )


def test_continuidad_ok_aunque_lleguen_desordenados():
    res = cuadrar([febrero(D("1349.80")), extracto_ok()])
    assert [r.extracto.hasta.month for r in res] == [1, 2]
    assert all(r.estado is Estado.CUADRA for r in res)


def test_falta_un_mes():
    res = cuadrar([extracto_ok(), febrero(D("2000.00"))])
    feb = res[1]
    assert feb.estado is Estado.NO_CUADRA
    d = feb.diferencias[0]
    assert d.tipo is TipoDiferencia.CONTINUIDAD and "¿Falta un mes?" in d.mensaje


def test_cuentas_distintas_no_se_mezclan():
    otra = febrero(D("2000.00"))
    otra.cuenta = "0171-9999"
    res = cuadrar([extracto_ok(), otra])
    assert all(r.estado is Estado.CUADRA for r in res)


def test_extracto_duplicado():
    res = cuadrar([extracto_ok(), extracto_ok()])
    assert any(d.tipo is TipoDiferencia.CONTINUIDAD and "duplicado" in d.mensaje
               for d in res[1].diferencias)


# ---------------------------------------------------------------- validación del modelo

def test_movimiento_rechaza_float():
    with pytest.raises(MontoInvalido):
        Movimiento(f(1), "X", debito=150.25)


def test_movimiento_rechaza_debito_y_credito_a_la_vez():
    with pytest.raises(MontoInvalido):
        Movimiento(f(1), "X", debito=D("1.00"), credito=D("1.00"))


def test_movimiento_rechaza_montos_negativos():
    with pytest.raises(MontoInvalido):
        Movimiento(f(1), "X", debito=D("-1.00"))
