"""BBVA Provincial, estado de cuenta corriente en PDF, abril 2026 (Importadora La Fantástica)."""
import datetime as dt
from decimal import Decimal as D
from pathlib import Path

import pytest

from cvp_parser.conversion import convertir, items
from cvp_parser.cuadre import Estado, cuadrar_extracto
from cvp_parser.lectores import LECTORES, leer_estado

PDF = Path(__file__).parent / "fixtures" / "provincial_2026_04" / "edo_provincial.pdf"
SIN_PDF = pytest.mark.skipif(not PDF.exists(), reason="falta el estado de cuenta real de Provincial")


@SIN_PDF
def test_lee_y_cuadra():
    assert [k for k, l in LECTORES.items() if l.reconoce(PDF)] == ["PROVINCIAL"]
    e = leer_estado("PROVINCIAL", PDF)
    assert (e.cuenta, e.desde, e.hasta, e.titular) == ("01080082010100467817", dt.date(2026, 4, 1),
                                                       dt.date(2026, 4, 30), "IMPORTADORA Y COMERCIALIZADORA LA FANTAS")
    assert not e.errores_lectura
    assert (e.saldo_anterior, e.totales_banco.nuevo_saldo) == (D("593371.48"), D("580713.07"))
    assert len(e.movimientos) == 81 and all(m.saldo is not None for m in e.movimientos)
    assert (sum(1 for m in e.movimientos if m.debito), sum(1 for m in e.movimientos if m.credito)) == (52, 29)
    q = cuadrar_extracto(e)
    # El banco no imprime totales ni nº de operaciones: queda «revisar avisos», nunca «no cuadra».
    assert q.estado is Estado.REQUIERE_REVISION and not q.diferencias
    assert (q.total_debitos, q.total_creditos, q.nuevo_saldo_calculado) == (
        D("2231148.45"), D("2218490.04"), D("580713.07"))
    m = e.movimientos[16]
    assert (m.fecha_contable, m.referencia, m.descripcion, m.credito, m.saldo) == (
        dt.date(2026, 4, 5), "2665", "TD POS J0412293524003", D("170647.62"), D("182902.58"))
    assert e.movimientos[0].debito == D("52226.08") and e.movimientos[0].pagina == 1
    assert e.movimientos[-1].pagina == 2


@SIN_PDF
def test_resumen_por_item():
    conv = convertir("LA FANTASTICA", "2026-04", [("Provincial 7817", "PROVINCIAL", PDF)])
    its = items(conv.cuentas[0].movs)
    tot = lambda nat: sum(i.creditos - i.debitos for i in its if i.naturaleza == nat)
    assert tot("Cobros POS – tarjeta de débito") == D("2053886.79")
    assert tot("Cobros POS – tarjeta de crédito") == D("164603.25")
    assert tot("Comisiones bancarias") == D("-3482.65")
    assert tot("Cargos bancarios (mantenimiento, estado de cuenta, SMS)") == D("-3537.60")
    assert tot("Otros (sin clasificar)") == D("-12673.46")          # INV.PLATCO (domiciliación)
