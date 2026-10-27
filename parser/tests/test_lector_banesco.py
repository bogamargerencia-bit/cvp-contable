"""Banesco, estado de cuenta en PDF, agosto 2026 (INVERSIONES P.T.S.)."""
import datetime as dt
from decimal import Decimal as D
from pathlib import Path

import pytest

from cvp_parser.conversion import convertir, items
from cvp_parser.cuadre import Estado, cuadrar_extracto
from cvp_parser.lectores import LECTORES

PDF = Path(__file__).parent / "fixtures" / "banesco_2026_08" / "edo_banesco.pdf"
pytestmark = pytest.mark.skipif(not PDF.exists(), reason="falta el estado de cuenta real de Banesco")


def test_lee_y_cuadra():
    assert LECTORES["BANESCO"].reconoce(PDF)
    assert not [k for k, l in LECTORES.items() if k != "BANESCO" and l.reconoce(PDF)]
    [e] = LECTORES["BANESCO"].leer([PDF]).extractos
    assert (e.cuenta, e.desde, e.hasta, e.titular) == ("01340025330251067692", dt.date(2026, 8, 1),
                                                       dt.date(2026, 8, 31), "INVERSIONES P.T.S. C,A.")
    assert e.saldo_anterior == D("35330.60") and not e.errores_lectura
    assert len(e.movimientos) == 10 and all(m.saldo is not None for m in e.movimientos)
    q = cuadrar_extracto(e)
    assert q.estado is Estado.CUADRA, [d.mensaje for d in q.diferencias]
    assert (q.total_debitos, q.total_creditos, q.nuevo_saldo_calculado) == (
        D("35850.01"), D("285854.41"), D("285335.00"))
    m = e.movimientos[2]
    assert (m.fecha_contable, m.referencia, m.descripcion, m.credito) == (
        dt.date(2026, 8, 18), "03617656953", "TRANS,CTAS", D("10122.63"))


def test_conversion():
    conv = convertir("PTS", "2026-08", [("Banesco 7692", "BANESCO", PDF)])
    assert conv.todo_cuadra
    its = {(i.naturaleza, i.concepto): i for i in items(conv.cuentas[0].movs)}
    assert its[("Cargos bancarios (mantenimiento, estado de cuenta, SMS)", "EMISION DE ESTADO DE CUENTA")].debitos == D("54.00")
    assert sum(i.creditos for i in its.values() if i.naturaleza == "Transferencias recibidas") == D("285854.41")
