"""Lectores Venezolano de Crédito y Bancamiga con los PDF reales de Shiro Alimentos (ago-sep 2026).

Los PDF van en tests/fixtures/shiro_2026/ (ignorado por git). Sin ellos, las pruebas se saltan.
Valores esperados tomados del resumen impreso por cada banco.
"""
import datetime as dt
from decimal import Decimal as D
from pathlib import Path

import pytest

from cvp_parser import Estado, cuadrar_extracto
from cvp_parser.lectores import LECTORES

FIX = Path(__file__).parent / "fixtures" / "shiro_2026"


def _requiere(nombre):
    return pytest.mark.skipif(not (FIX / nombre).exists(), reason=f"falta {nombre} (datos reales de Shiro)")


@_requiere("edo_venezolano_09.pdf")
def test_venezolano_septiembre():
    lector = LECTORES["VENEZOLANO"]
    ruta = FIX / "edo_venezolano_09.pdf"
    assert lector.reconoce(ruta)
    (e,) = lector.leer([ruta]).extractos
    assert e.errores_lectura == []
    assert e.cuenta == "0104-0107-15-0107215948"
    assert e.hasta == dt.date(2026, 9, 30)
    assert e.titular == "SHIRO ALIMENTOS C.A."
    assert e.saldo_anterior == D("490662.77")
    deb = [m for m in e.movimientos if m.debito]
    cre = [m for m in e.movimientos if m.credito]
    assert (len(deb), sum(m.debito for m in deb)) == (287, D("15309844.98"))
    assert (len(cre), sum(m.credito for m in cre)) == (159, D("14828570.55"))
    assert e.movimientos[-1].saldo == D("9388.34")
    assert cuadrar_extracto(e).estado == Estado.CUADRA
    # El detalle (beneficiario) queda en su propio campo
    assert "SUPER CHINA TOWN" in e.movimientos[0].detalle
    # Líneas sin número de referencia
    assert any(m.descripcion.startswith("POS DEB. TERM") and m.referencia == "" for m in e.movimientos)


@_requiere("edo_venezolano_08.pdf")
def test_venezolano_agosto_y_continuidad():
    lector = LECTORES["VENEZOLANO"]
    (ago,) = lector.leer([FIX / "edo_venezolano_08.pdf"]).extractos
    assert ago.errores_lectura == []
    assert ago.hasta == dt.date(2026, 8, 31)
    assert ago.saldo_anterior == D("257001.67")
    assert ago.movimientos[-1].saldo == D("490662.77")
    assert len(ago.movimientos) == 524
    assert cuadrar_extracto(ago).estado == Estado.CUADRA


@_requiere("edo_bancamiga_09.pdf")
def test_bancamiga_septiembre():
    lector = LECTORES["BANCAMIGA"]
    ruta = FIX / "edo_bancamiga_09.pdf"
    assert lector.reconoce(ruta)
    assert not LECTORES["VENEZOLANO"].reconoce(ruta)
    (e,) = lector.leer([ruta]).extractos
    assert e.errores_lectura == []
    assert e.hasta == dt.date(2026, 9, 30)
    assert e.saldo_anterior == D("10646.76")
    assert e.totales_banco.nro_debitos == 20 and e.totales_banco.total_debitos == D("1233100.13")
    assert e.totales_banco.nro_creditos == 12 and e.totales_banco.total_creditos == D("1377834.17")
    assert e.totales_banco.nuevo_saldo == D("155380.80")
    assert len(e.movimientos) == 32
    assert cuadrar_extracto(e).estado == Estado.CUADRA
    # Descripción que continúa en la línea siguiente
    assert e.movimientos[0].descripcion == "Consumo Masterdebit Nacional - SHIRO ALIMENTOS CA VALENCIA VEN"
    # Una descripción que no continúa no debe absorber texto del pie de página
    assert all("Hacemos Equipo" not in m.descripcion for m in e.movimientos)
