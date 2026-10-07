"""CACAO septiembre 2026: formatos nuevos (PDF de Plaza «ESTADO DE CUENTAS» y libro «reporte»)."""
from decimal import Decimal as D
from pathlib import Path

import pytest

from cvp_parser.cuadre import cuadrar
from cvp_parser.lectores import LECTORES
from cvp_parser.sistema import leer_libro

FIX = Path(__file__).parent / "fixtures" / "cacao_2026_09"
pytestmark = pytest.mark.skipif(not (FIX / "edo_plaza.pdf").exists(), reason="faltan los archivos reales de CACAO sept.")


def test_plaza_formato_nuevo():
    e = LECTORES["PLAZA"].leer([FIX / "edo_plaza.pdf"]).extractos[0]
    assert (e.cuenta, e.titular) == ("0138************7448", "JOHANA COROMOTO GIL GALINDEZ")
    assert (str(e.desde), str(e.hasta), len(e.movimientos)) == ("2026-09-01", "2026-09-30", 385)
    assert e.saldo_anterior == D("53696.15")            # = saldo final real de agosto
    assert e.movimientos[-1].saldo == D("227890.43") and not e.errores_lectura
    assert e.movimientos[0].referencia == "0390100252"
    (r,) = cuadrar([e])
    assert not r.diferencias                              # saldo corrido línea a línea


def test_libro_reporte():
    b = leer_libro(FIX / "sistema_banplus.xls")
    assert len(b.asientos) == 45
    assert sum(a.credito_usd for a in b.asientos) == D("7889.73")
    assert sum(a.monto_bs for a in b.asientos) == D("5676700.65")
    assert not any(a.debito_usd for a in b.asientos) and len(b.avisos) == 2
    p = leer_libro(FIX / "sistema_plaza.xls")
    assert (len(p.asientos), sum(a.monto_bs for a in p.asientos)) == (67, D("16634772.30"))


def test_pdf_con_extension_de_excel():
    with pytest.raises(ValueError, match="es un PDF con extensión de Excel"):
        leer_libro(FIX / "sistema_efectivo.xls")
