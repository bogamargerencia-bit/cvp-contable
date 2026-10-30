"""Banesco: páginas con el detalle en dos bloques (izquierda y derecha).

El PDF se genera aquí con datos ficticios imitando el formato del banco: página 1 con el titular a la
izquierda y el detalle a la derecha; página 2 con el detalle en dos bloques y el resumen al pie.
"""
import datetime as dt
from decimal import Decimal as D

import pytest

from cvp_parser.cuadre import Estado, cuadrar_extracto
from cvp_parser.lectores import LECTORES

reportlab = pytest.importorskip("reportlab")
from reportlab.pdfgen import canvas  # noqa: E402

ANCHO, ALTO = 792, 612
# x del encabezado (DIA, REF., CONCEPTO) y borde derecho de CARGOS / ABONOS / SALDOS, por bloque
IZQ = dict(dia=20, ref=40, concepto=88, cargos=228, abonos=296, saldos=368)
DER = dict(dia=412, ref=432, concepto=480, cargos=609, abonos=675, saldos=747)


def ve(x: D) -> str:
    s = f"{x:,.2f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def movimientos(n: int, saldo: D):
    out = []
    for i in range(n):
        dia = 1 + i * 27 // n
        if i % 3 == 0:
            deb, cre = D(0), D(1000 + i * 37) + D("0.45")
        else:
            deb, cre = D(100 + i * 11) + D("0.10"), D(0)
        saldo += cre - deb
        desc = "TRF CR INM 0105 J000000000 CLI" if cre else ("COM,SERV.MTTO CTA" if i % 3 == 2 else "PAGO PROVEEDOR")
        out.append((dia, f"{9000000 + i:011d}", desc, deb, cre, saldo))
    return out


def encabezado(c, b, y):
    for k, t in (("dia", "DIA"), ("ref", "REF."), ("concepto", "CONCEPTO")):
        c.drawString(b[k], y, t)
    for k, t in (("cargos", "CARGOS"), ("abonos", "ABONOS"), ("saldos", "SALDOS")):
        c.drawRightString(b[k], y, t)


def fila(c, b, y, m):
    dia, ref, desc, deb, cre, saldo = m
    c.drawString(b["dia"], y, f"{dia:02d}")
    c.drawString(b["ref"], y, ref)
    c.drawString(b["concepto"], y, desc)
    if deb:
        c.drawRightString(b["cargos"], y, ve(deb))
    if cre:
        c.drawRightString(b["abonos"], y, ve(cre))
    c.drawRightString(b["saldos"], y, ve(saldo))


@pytest.fixture
def pdf(tmp_path):
    inicial = D("5000.00")
    movs = movimientos(60, inicial)
    p1, p2i, p2d = movs[:12], movs[12:36], movs[36:]
    ruta = tmp_path / "banesco_dos_columnas.pdf"
    c = canvas.Canvas(str(ruta), pagesize=(ANCHO, ALTO))
    c.setFont("Helvetica", 6)
    # página 1: titular a la izquierda, detalle a la derecha
    c.drawString(412, ALTO - 110, "DETALLE DE MOVIMIENTOS")
    encabezado(c, DER, ALTO - 122)
    c.drawString(148, ALTO - 131, "SL- 1000000.0")
    c.drawString(480, ALTO - 131, "SALDO MES ANTERIOR")
    c.drawRightString(DER["saldos"], ALTO - 131, ve(inicial))
    c.drawString(148, ALTO - 141, "EMPRESA DE PRUEBA, C.A.")
    for i, m in enumerate(p1):
        fila(c, DER, ALTO - 141 - 8 * i, m)
    c.showPage()
    # página 2: dos bloques de detalle y el resumen al pie
    c.setFont("Helvetica", 6)
    encabezado(c, IZQ, ALTO - 60)
    encabezado(c, DER, ALTO - 60)
    for i, m in enumerate(p2i):
        fila(c, IZQ, ALTO - 72 - 8 * i, m)
    for i, m in enumerate(p2d):
        fila(c, DER, ALTO - 72 - 8 * i, m)
    deb = sum(m[3] for m in movs)
    cre = sum(m[4] for m in movs)
    n_deb = sum(1 for m in movs if m[3])
    n_cre = sum(1 for m in movs if m[4])
    y = 200
    for t in ("RESUMEN DE MOVIMIENTOS   No. de Cuenta:   01340000000000000001   Período: 09-2026",
              "Concepto   Cantidad   Monto Total", "Cheques Pagados   0   0,00",
              f"Otros Débitos   {n_deb}   {ve(deb)}", "Depósitos   0   0,00",
              f"Otros Créditos   {n_cre}   {ve(cre)}", "RESUMEN DE SALDOS",
              f"Inicial   {ve(inicial)}", f"Final   {ve(movs[-1][5])}"):
        c.drawString(20, y, t)
        y -= 10
    c.save()
    return ruta, movs, inicial


def test_lee_ambos_bloques_en_orden(pdf):
    ruta, movs, inicial = pdf
    assert LECTORES["BANESCO"].reconoce(ruta)
    [e] = LECTORES["BANESCO"].leer([ruta]).extractos
    assert not e.errores_lectura, e.errores_lectura
    assert e.titular == "EMPRESA DE PRUEBA, C.A."
    assert e.saldo_anterior == inicial
    assert len(e.movimientos) == len(movs) == 60
    # mismo orden que el banco: página 1, bloque izquierdo de la página 2 y luego el derecho
    assert [(m.fecha_contable.day, m.referencia, m.debito, m.credito, m.saldo) for m in e.movimientos] == \
        [(d, r, deb, cre, s) for d, r, _, deb, cre, s in movs]
    assert [m.pagina for m in e.movimientos] == [1] * 12 + [2] * 48
    q = cuadrar_extracto(e)
    assert q.estado is Estado.CUADRA, [d.mensaje for d in q.diferencias]
    assert e.desde == dt.date(2026, 9, 1) and q.nuevo_saldo_calculado == movs[-1][5]
