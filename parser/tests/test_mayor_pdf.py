"""Mayor Analítico del sistema impreso a PDF (Shiro Alimentos). Valores esperados = «Totales:» impresos."""
from decimal import Decimal as D
from pathlib import Path

import pytest

from cvp_parser.sistema import leer_libro

FIX = Path(__file__).parent / "fixtures" / "shiro_2026"


def _requiere(nombre):
    return pytest.mark.skipif(not (FIX / nombre).exists(), reason=f"falta {nombre} (datos reales de Shiro)")


@_requiere("mayor_venezolano_09.pdf")
def test_mayor_pdf_venezolano_septiembre():
    lb = leer_libro(FIX / "mayor_venezolano_09.pdf")
    assert lb.diferencias_saldo == [] and lb.filas_ignoradas == []
    assert len(lb.asientos) == 67
    assert lb.saldo_inicial_usd == D("617.19") and lb.saldo_final_usd == D("-16871.87")
    assert sum(a.credito_usd for a in lb.asientos) == D("17489.06")
    assert not any(a.debito_usd for a in lb.asientos)
    a = lb.asientos[0]
    assert (a.monto_bs, a.credito_usd) == (D("223121.00"), D("279.49"))
    assert a.descripcion == "FACT 199082 FRIGORIFICO LA CARRETA, C.A"
    # Descripción que sigue en la página siguiente
    assert any(x.descripcion == "FACT 4437 CONGELADOS IMPORT, PAPA FRITAS" for x in lb.asientos)
    # Referencia que no es un monto («000071»): sin monto en Bs.
    surami = next(x for x in lb.asientos if "SURAMI JOSEFINA" in x.descripcion)
    assert surami.monto_bs is None


@_requiere("mayor_efectivo_08.pdf")
def test_mayor_pdf_con_debitos_y_creditos():
    lb = leer_libro(FIX / "mayor_efectivo_08.pdf")
    assert lb.diferencias_saldo == [] and lb.filas_ignoradas == []
    assert sum(a.debito_usd for a in lb.asientos) == D("15638.00")
    assert sum(a.credito_usd for a in lb.asientos) == D("16000.00")
    assert (lb.saldo_inicial_usd, lb.saldo_final_usd) == (D("5993.00"), D("5631.00"))
    ventas = next(a for a in lb.asientos if "INGRESO POR VENTAS" in a.descripcion)
    assert ventas.debito_usd == D("8138.00") and ventas.descripcion == "INGRESO POR VENTAS AGOSTO 2026"


@_requiere("mayor_bancamiga_09.pdf")
def test_mayor_pdf_sin_saldo_anterior():
    lb = leer_libro(FIX / "mayor_bancamiga_09.pdf")
    assert lb.diferencias_saldo == []
    assert (lb.saldo_inicial_usd, lb.saldo_final_usd) == (D("0.00"), D("-1422.41"))
    assert [a.monto_bs for a in lb.asientos] == [D("301924.11"), D("400000.00"), D("500000.00")]


@_requiere("mayor_gastos_08.pdf")
def test_mayor_pdf_con_varias_cuentas_se_rechaza():
    with pytest.raises(ValueError, match="trae 48 cuentas"):
        leer_libro(FIX / "mayor_gastos_08.pdf")


@_requiere("edo_venezolano_09.pdf")
def test_pdf_que_no_es_mayor_se_rechaza():
    with pytest.raises(ValueError, match="no es un Mayor Analítico"):
        leer_libro(FIX / "edo_venezolano_09.pdf")


@_requiere("mayor_venezolano_09.pdf")
def test_corrida_shiro_septiembre():
    from cvp_parser.proceso import procesar_cliente
    rep = procesar_cliente("Shiro Alimentos C.A.", "2026-09", [
        ("VENEZOLANO", FIX / "edo_venezolano_09.pdf", FIX / "mayor_venezolano_09.pdf"),
        ("BANCAMIGA", FIX / "edo_bancamiga_09.pdf", FIX / "mayor_bancamiga_09.pdf"),
    ])
    assert all(c.estado.value == "cuadra" for c in rep.cuadres.values())
    assert rep.conciliaciones["BANCAMIGA"].partidas
    v = rep.conciliaciones["VENEZOLANO"]
    solo_libro = [p for p in v.partidas if p.estado.name == "SOLO_LIBRO"]
    assert len(solo_libro) == 4        # Monte Verde, Santamaría (montos mal transcritos), Surami, Ángeles Huamán
