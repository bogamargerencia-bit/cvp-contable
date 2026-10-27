"""Banco Activo, estado de cuenta en PDF (FPDF), agosto 2026 (Pistazie)."""
import datetime as dt
from decimal import Decimal as D
from pathlib import Path

import pytest

from cvp_parser.conversion import convertir, items
from cvp_parser.cuadre import Estado, cuadrar_extracto
from cvp_parser.lectores import LECTORES, leer_estado

PDF = Path(__file__).parent / "fixtures" / "activo_2026_08" / "edo_activo.pdf"
pytestmark = pytest.mark.skipif(not PDF.exists(), reason="falta el estado de cuenta real de Banco Activo")


def test_lee_y_cuadra():
    assert [k for k, l in LECTORES.items() if l.reconoce(PDF)] == ["ACTIVO"]
    [e] = LECTORES["ACTIVO"].leer([PDF]).extractos
    assert (e.cuenta, e.titular, e.desde, e.hasta, e.saldo_anterior) == (
        "6002185098", "PISTAZIE, C.A.", dt.date(2026, 8, 1), dt.date(2026, 8, 31), D("237366.18"))
    assert not e.errores_lectura and len(e.movimientos) == 122 and all(m.saldo is not None for m in e.movimientos)
    q = cuadrar_extracto(e)
    assert q.estado is Estado.CUADRA, [d.mensaje for d in q.diferencias[:5]]
    assert (q.total_debitos, q.total_creditos, q.nuevo_saldo_calculado) == (
        D("10268970.08"), D("10075000.00"), D("43396.10"))
    m = e.movimientos[1]   # fecha real distinta de la contable
    assert (m.fecha_real, m.fecha_contable, m.referencia, m.credito) == (
        dt.date(2026, 8, 2), dt.date(2026, 8, 3), "140680672", D("900000.00"))


def test_conceptos_sin_rif_y_clasificados():
    conv = convertir("PISTAZIE", "2026-08", [("Activo 5098", "ACTIVO", PDF)])
    its = {(i.naturaleza, i.concepto): i for i in items(conv.cuentas[0].movs)}
    assert its[("Pagos por transferencia / crédito inmediato", "N/D CRED I")].n == 38
    assert its[("Comisiones bancarias", "N/D COM. CINM")].debitos == D("25420.78")
    assert its[("Transferencias recibidas", "N/C CRED I")].creditos == D("10075000.00")
    assert [k for k in its if k[0] == "Otros (sin clasificar)"] == [("Otros (sin clasificar)", "CORPOELEC")]


def test_pdf_de_activo_en_cuenta_banplus():
    """El caso real de Pistazie: el PDF de Activo subido en una cuenta de Banplus."""
    with pytest.raises(ValueError, match="parece un estado de cuenta de Banco Activo"):
        leer_estado("BANPLUS", PDF, "Banplus")
