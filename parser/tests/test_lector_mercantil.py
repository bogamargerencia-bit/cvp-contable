"""Mercantil, estado de cuenta corriente en PDF (dos columnas por página), septiembre 2026."""
import datetime as dt
from decimal import Decimal as D
from pathlib import Path

import pytest

from cvp_parser.conversion import convertir, items
from cvp_parser.cuadre import Estado, cuadrar_extracto
from cvp_parser.lectores import LECTORES
from cvp_parser.naturaleza import OTROS, clasificar_extracto

PDF = Path(__file__).parent / "fixtures" / "mercantil_2026_09" / "edo_mercantil.pdf"
pytestmark = pytest.mark.skipif(not PDF.exists(), reason="falta el estado de cuenta real de Mercantil")


@pytest.fixture(scope="module")
def extracto():
    assert LECTORES["MERCANTIL"].reconoce(PDF)
    [e] = LECTORES["MERCANTIL"].leer([PDF]).extractos
    return e


def test_resumen_y_cuadre(extracto):
    e = extracto
    assert (e.cuenta, e.desde, e.hasta) == ("0105-0014-17-1014675855", dt.date(2026, 9, 1), dt.date(2026, 9, 30))
    assert e.titular == "ALIMENTOS CORSEGA 515, C.A." and e.saldo_anterior == D("9768837.58")
    assert not e.errores_lectura
    q = cuadrar_extracto(e)
    assert q.estado is Estado.CUADRA, [d.mensaje for d in q.diferencias]
    assert (q.total_debitos, q.total_creditos, q.nuevo_saldo_calculado) == (
        D("118432343.47"), D("166552566.96"), D("57889061.07"))
    assert sum(1 for m in e.movimientos if m.debito) == 57 and sum(1 for m in e.movimientos if m.credito) == 72


def test_saldo_al_cierre_de_cada_dia(extracto):
    """El saldo de la tabla «SALDOS AL FINAL DEL DIA» se verifica en el último movimiento de cada día."""
    con_saldo = [m for m in extracto.movimientos if m.saldo is not None]
    dias = {m.fecha_contable for m in extracto.movimientos}
    assert len(con_saldo) == len(dias) == 16
    assert next(m for m in con_saldo if m.fecha_contable == dt.date(2026, 9, 7)).saldo == D("3250984.06")


def test_monto_con_numero_de_control_pegado(extracto):
    """«15.379,61103176»: el monto es 15.379,61 (103176 es un número de control del banco)."""
    m = next(m for m in extracto.movimientos if m.referencia == "00208334")
    assert m.credito == D("15379.61") and m.fecha_contable == dt.date(2026, 9, 7)
    assert "SALUMERIA" in m.detalle


def test_clasificacion_y_conversion(extracto):
    assert not [x for x in clasificar_extracto(extracto) if x.naturaleza == OTROS]
    conv = convertir("CORSEGA", "2026-09", [("Mercantil 5855", "MERCANTIL", PDF)])
    assert conv.todo_cuadra
    its = items(conv.cuentas[0].movs)
    com = sum(i.debitos for i in its if i.naturaleza == "Comisiones bancarias")
    assert com == sum(m.debito for m in extracto.movimientos if m.descripcion.startswith("COMISION"))
