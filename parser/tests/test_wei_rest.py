"""Prueba con los archivos reales de WEI REST (Alimentos Sierra del Sol, C.A.), agosto 2026.

Los archivos están en tests/fixtures/wei_rest_2026_08/ y NO se suben a git (datos de terceros).
Si no están, la prueba se omite. Las cifras esperadas salen de los propios archivos:
resumen impreso del banco, fila "Totales", "Saldo Inicial"/"Saldo Total".
"""
from decimal import Decimal as D
from pathlib import Path

import pytest

from cvp_parser.conciliacion import EstadoPartida as E
from cvp_parser.cuadre import Estado
from cvp_parser.proceso import procesar_cliente

FIX = Path(__file__).parent / "fixtures" / "wei_rest_2026_08"
ARCHIVOS = [
    ("100_BANCO", FIX / "edo_100_banco.pdf", FIX / "sistema_100_banco.xls"),
    ("BNC", FIX / "edo_bnc.xls", FIX / "sistema_bnc.xls"),
    ("BANPLUS", FIX / "edo_banplus.xlsx", FIX / "sistema_banplus.xls"),
]
pytestmark = pytest.mark.skipif(not all(p.exists() for _, a, b in ARCHIVOS for p in (a, b)),
                                reason="faltan los archivos reales de WEI REST (no van en git)")


@pytest.fixture(scope="module")
def rep():
    return procesar_cliente("WEI REST", "2026-08", ARCHIVOS)


@pytest.mark.parametrize("banco,n,ini,deb,cre,fin,estado", [
    ("100_BANCO", 78, "281701.51", "1789544.42", "1536892.55", "29049.64", Estado.CUADRA),
    ("BNC", 794, "135419.27", "50363951.11", "50379929.63", "151397.79", Estado.REQUIERE_REVISION),
    ("BANPLUS", 424, "209888.44", "9516769.42", "9334715.14", "27834.16", Estado.REQUIERE_REVISION),
])
def test_cuadre_al_centimo(rep, banco, n, ini, deb, cre, fin, estado):
    c = rep.cuadres[banco]
    assert c.diferencias == []
    assert c.estado is estado
    assert len(c.extracto.movimientos) == n
    assert c.extracto.saldo_anterior == D(ini)
    assert (c.total_debitos, c.total_creditos, c.nuevo_saldo_calculado) == (D(deb), D(cre), D(fin))


def test_100_banco_conteos_del_resumen(rep):
    tb = rep.cuadres["100_BANCO"].extracto.totales_banco
    assert (tb.nro_creditos, tb.nro_debitos) == (22, 56)


def test_libro_100_trae_una_diferencia_de_350_usd(rep):
    lb = rep.libros["100_BANCO"]
    assert lb.saldo_inicial_usd == D("377.30")
    assert len(lb.diferencias_saldo) == 1 and "466.96" in lb.diferencias_saldo[0]
    assert any("100_BANCO" in a for a in rep.alertas)
    assert rep.libros["BNC"].diferencias_saldo == [] and rep.libros["BANPLUS"].diferencias_saldo == []


def test_naturaleza_suma_los_totales_del_banco(rep):
    for b, lista in rep.clasificados.items():
        assert all(x.naturaleza != "Otros (sin clasificar)" for x in lista), b
        c = rep.cuadres[b]
        assert sum(x.mov.debito for x in lista) == c.total_debitos
        assert sum(x.mov.credito for x in lista) == c.total_creditos


def test_traslados_entre_cuentas_propias(rep):
    tr = [x for l in rep.clasificados.values() for x in l if x.naturaleza.startswith("Traslados")]
    assert len(tr) == 12  # 6 pares
    assert sum(x.mov.debito for x in tr) == sum(x.mov.credito for x in tr) == D("1605000.00")


@pytest.mark.parametrize("banco,esperado", [
    ("100_BANCO", {E.CONCILIADO: (13, 13), E.DIFERENCIA_MONTO: (6, 6), E.RESUMEN_SIN_MONTO: (0, 1),
                   E.OTRO_BANCO: (1, 0), E.SOLO_BANCO: (58, 0)}),
    ("BNC", {E.CONCILIADO: (288, 288), E.DIFERENCIA_MONTO: (6, 6), E.OTRO_BANCO: (4, 4),
             E.SOLO_LIBRO: (0, 9), E.RESUMEN_SIN_MONTO: (0, 3), E.SOLO_BANCO: (496, 0)}),
    ("BANPLUS", {E.CONCILIADO: (58, 58), E.DIFERENCIA_MONTO: (12, 12), E.OTRO_BANCO: (3, 4),
                 E.SOLO_LIBRO: (0, 5), E.RESUMEN_SIN_MONTO: (0, 2), E.SOLO_BANCO: (351, 0)}),
])
def test_conciliacion_por_estado(rep, banco, esperado):
    res = {k: (v[0], v[1]) for k, v in rep.conciliaciones[banco].resumen().items()}
    assert res == esperado
    r = rep.conciliaciones[banco]
    assert len(r.estado_mov) == len(r.extracto.movimientos)   # todo movimiento tiene estado
    assert len(r.estado_asiento) == len(r.libro.asientos)     # todo asiento tiene estado


def test_excel_se_genera(rep, tmp_path):
    from cvp_parser.exportar import excel_conciliacion
    out = excel_conciliacion(rep, tmp_path / "wei.xlsx")
    import openpyxl
    wb = openpyxl.load_workbook(out)
    assert wb.sheetnames[:3] == ["Revisión", "Resumen", "Naturaleza"]
    assert wb["_control"].sheet_state == "hidden"
    assert "Banco BNC" in wb.sheetnames and "Libro Banplus" in wb.sheetnames


# ---------------------------------------------------------------- con el cierre de caja
from cvp_parser.conciliacion_caja import EstadoCaja as EC  # noqa: E402

VENTAS = FIX / "ventas.xlsx"


@pytest.fixture(scope="module")
def rep_caja():
    if not VENTAS.exists():
        pytest.skip("falta el cierre de caja de WEI REST")
    return procesar_cliente("WEI REST", "2026-08", ARCHIVOS, cierre_caja=VENTAS)


def test_caja_totales_por_medio(rep_caja):
    c = rep_caja.caja.cierre
    assert c.errores == []
    tot = {m: sum(i.monto_bs for i in c.items_de(m)) for m in c.medios}
    assert tot["T. credito BNC"] == D("27293369.85")
    assert tot["T. debito BNC"] == D("16819404.86")
    assert tot["Pago móvil BANPLUS"] == D("9293260.10")


def test_caja_asientos_resumen(rep_caja):
    cruces = {(c.banco, c.medio): c for c in rep_caja.caja.asientos}
    assert all(c.conciliado for c in cruces.values())
    assert cruces[("BNC", "T. debito BNC")].hasta.day == 30      # falta el 31/08 en el libro
    assert cruces[("BNC", "T. credito BNC")].hasta.day == 30
    assert "Faltan" not in cruces[("BANPLUS", "Pago móvil BANPLUS")].nota


def test_caja_tarjetas_bnc_por_lote(rep_caja):
    pos = [l for l in rep_caja.caja.lineas if l.medio == "Tarjetas BNC"]
    from collections import Counter
    assert Counter(l.estado for l in pos) == {EC.CONCILIADO: 27, EC.LOTES: 2, EC.EN_TRANSITO: 2}
    assert sum(l.monto for l in pos if l.estado is EC.EN_TRANSITO) == D("1663586.31")


def test_caja_pago_movil(rep_caja):
    from collections import Counter
    pm = Counter((l.medio, l.estado) for l in rep_caja.caja.lineas if l.medio.startswith("Pago móvil"))
    assert pm[("Pago móvil 100% BANCO", EC.CONCILIADO)] == 17
    assert pm[("Pago móvil BNC", EC.POSIBLE_ERROR)] == 1
    assert pm[("Pago móvil BANPLUS", EC.POSIBLE_ERROR)] == 3
    assert pm[("Pago móvil BANPLUS", EC.NO_ENCONTRADO)] == 1
