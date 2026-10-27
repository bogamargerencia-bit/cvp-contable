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


PDF_PERSONAL = Path(__file__).parent / "fixtures" / "mercantil_personal_2026_09" / "edo_mercantil.pdf"


@pytest.mark.skipif(not PDF_PERSONAL.exists(), reason="falta el estado de la cuenta personal de Mercantil")
def test_variante_movimientos_de_cuenta():
    """Cuenta personal (69 páginas): CARGOS | ABONOS | SALDO por mitad de página; en la página 1 el banco
    omite «POR» en «377 OTROS CREDITOS A SU CUENTA 45.305.570,80»."""
    [e] = LECTORES["MERCANTIL"].leer([PDF_PERSONAL]).extractos
    assert (e.cuenta, e.titular, e.saldo_anterior) == ("0105-0121-14-1121252354", "TABARES LEON ROSA MARIA",
                                                       D("91209.83"))
    assert not e.errores_lectura
    q = cuadrar_extracto(e)
    assert q.estado is Estado.CUADRA, [d.mensaje for d in q.diferencias[:5]]
    assert (q.total_debitos, q.total_creditos, q.nuevo_saldo_calculado) == (
        D("44922588.74"), D("45305570.80"), D("474191.89"))
    assert sum(1 for m in e.movimientos if m.debito) == 739 and sum(1 for m in e.movimientos if m.credito) == 377
    assert sum(1 for m in e.movimientos if m.saldo is not None) >= 16


@pytest.mark.skipif(not PDF_PERSONAL.exists(), reason="falta el estado de la cuenta personal de Mercantil")
def test_variante_personal_conceptos():
    """El concepto no se parte por la fecha incrustada; «pago movil» escrito por el usuario en el detalle de
    una transferencia no la vuelve pago móvil."""
    conv = convertir("ROSA", "2026-09", [("Mercantil 2354", "MERCANTIL", PDF_PERSONAL)])
    its = {(i.naturaleza, i.concepto): i for i in items(conv.cuentas[0].movs)}
    assert its[("Cobros por pago móvil / P2C", "RECEPCION DE PAGO MOVIL")].n == 92
    assert its[("Pagos por transferencia / crédito inmediato", "OPERACION DE CREDITO INMEDIATO - TRANSF. PRES")].n == 232
    assert its[("Cobros POS – liquidación de ventas", "CANCELACION RESUMEN DE VENTAS Y RETENCIONES")].creditos == D("32709589.57")
    assert its[("Comisiones bancarias", "DESCUENTO TARJETA")].n == 52


def test_archivo_de_otro_banco_mensaje_claro(tmp_path):
    """Pistazie: un PDF de otro banco subido en una cuenta de Banplus. Antes salía un error interno de openpyxl;
    ahora el mensaje dice de qué banco parece el archivo."""
    from cvp_parser.lectores import leer_estado
    with pytest.raises(ValueError, match=r"parece un estado de cuenta de Mercantil"):
        leer_estado("BANPLUS", PDF, "Banplus")
    falso = tmp_path / "09 ESTADO DE CUENTA BANCO ACTIVO.pdf"
    falso.write_bytes(b"%PDF-1.4\n%%EOF\n")
    with pytest.raises(ValueError, match=r"\(PDF\) no se pudo leer como estado de cuenta de «Banplus» \(Banplus\)"):
        leer_estado("BANPLUS", falso, "Banplus")
