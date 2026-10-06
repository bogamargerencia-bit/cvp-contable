"""Pruebas de la conciliación del cierre de caja con datos sintéticos."""
import datetime as dt
from decimal import Decimal as D

from cvp_parser import Extracto, Movimiento, TotalesBanco
from cvp_parser.conciliacion import EstadoPartida as EP, conciliar
from cvp_parser.conciliacion_caja import EstadoCaja as EC, _un_digito, conciliar_caja
from cvp_parser.naturaleza import clasificar_extracto
from cvp_parser.sistema import AsientoLibro, LibroBanco
from cvp_parser.ventas import PAGO_MOVIL, POS, CierreCaja, ItemCaja, _desglose


def f(d):
    return dt.date(2026, 8, d)


def pos(d, monto, lote, tipo="Deb"):
    return Movimiento(f(d), f"Abono Comercio por Tarjeta {tipo}", credito=D(monto),
                      detalle=f"POS: 1 FECHA:{d:02d}/08/2026 HORA:03:30:00 LOTE:{lote} TERM:1")


def pm(d, monto):
    return Movimiento(f(d), "Abono Pago Movil BNC", credito=D(monto))


def item(d, medio, tipo, monto, comps=None, usd="1.00"):
    comps = [D(c) for c in comps] if comps else [D(monto)]
    return ItemCaja(f(d), d + 4, medio, "BNC", tipo, D(monto), D(usd), comps)


def correr(movs, items, asientos=(), hasta=31):
    e = Extracto(banco="BNC", cuenta="1", desde=f(1), hasta=f(hasta), saldo_anterior=D("0"),
                 movimientos=movs, totales_banco=TotalesBanco())
    libro = LibroBanco("s.xls", list(asientos), D("0"), D("0"))
    conc = {"BNC": conciliar(e, libro)}
    cl = {"BNC": clasificar_extracto(e)}
    cierre = CierreCaja("v.xlsx", "VENTAS", {}, list(items))
    return conciliar_caja(cierre, cl, conc), conc


def resumen_asiento(ref, usd):
    return AsientoLibro(fila=2, fecha=f(31), comprobante="1", referencia=ref, descripcion="BNC",
                        debito_usd=D(usd), credito_usd=D("0"), saldo_usd=None, monto_bs=None)


def estados(r):
    return [(l.fecha.day, l.estado) for l in r.lineas]


def test_desglose_de_formula():
    assert _desglose("=37978.04+70926.78+81000") == [D("37978.04"), D("70926.78"), D("81000.00")]
    assert _desglose("=+AU5/D5") is None
    assert _desglose(150) is None


def test_un_digito():
    assert _un_digito(D("136535.04"), D("135535.04"))
    assert _un_digito(D("99020.11"), D("99020.01"))
    assert not _un_digito(D("5500.00"), D("55000.00"))
    assert not _un_digito(D("100.00"), D("111.00"))


def test_pos_lote_d_mas_2_un_lote_y_dos_lotes():
    movs = [pos(3, "600.00", "554", "Cre"), pos(3, "400.00", "554"),
            pos(15, "300.00", "567"), pos(16, "200.00", "568")]
    items = [item(1, "T. credito BNC", POS, "700.00"), item(1, "T. debito BNC", POS, "300.00"),
             item(14, "T. debito BNC", POS, "500.00")]
    r, conc = correr(movs, items)
    assert estados(r) == [(1, EC.CONCILIADO), (14, EC.LOTES)]
    assert "crédito 600.00 / débito 400.00" in r.lineas[0].nota   # el reparto distinto se informa


def test_pos_en_transito_y_lote_del_mes_anterior():
    movs = [pos(1, "999.00", "552")]
    items = [item(30, "T. debito BNC", POS, "800.00")]
    r, _ = correr(movs, items)
    assert estados(r) == [(30, EC.EN_TRANSITO)]
    assert r.sin_caja and "mes anterior" in r.sin_caja[0][2]


def test_pago_movil_exacto_fraccionado_digito_y_no_encontrado():
    movs = [pm(1, "120444.60"), pm(28, "25000.00"), pm(28, "25000.00"), pm(28, "25000.00"),
            pm(9, "135535.04"), pm(19, "777.00")]
    items = [item(1, "Pago móvil BNC", PAGO_MOVIL, "120444.60"),
             item(28, "Pago móvil BNC", PAGO_MOVIL, "75000.00"),
             item(9, "Pago móvil BNC", PAGO_MOVIL, "136535.04"),
             item(20, "Pago móvil BNC", PAGO_MOVIL, "5500.00")]
    r, conc = correr(movs, items)
    por_dia = dict(estados(r))
    assert por_dia == {1: EC.CONCILIADO, 28: EC.AGRUPADO, 9: EC.POSIBLE_ERROR, 20: EC.NO_ENCONTRADO}
    linea20 = next(l for l in r.lineas if l.fecha.day == 20)
    assert "777.00" in linea20.nota          # informa lo que queda sin caja en la ventana
    assert [(b, i) for b, i, _ in r.sin_caja] == [("BNC", 5)]


def test_asiento_resumen_mes_completo_y_parcial():
    items = [item(1, "Pago móvil BNC", PAGO_MOVIL, "100.00", usd="0.50"),
             item(2, "Pago móvil BNC", PAGO_MOVIL, "200.00", usd="1.00"),
             item(1, "T. debito BNC", POS, "300.00", usd="1.10"),
             item(31, "T. debito BNC", POS, "400.00", usd="2.25")]
    movs = [pm(1, "100.00"), pm(2, "200.00"), pos(3, "300.00", "1")]
    asientos = [resumen_asiento("PAGO MOVIL", "1.50"), resumen_asiento("DEBITO", "1.10")]
    r, conc = correr(movs, items, asientos)
    c_pm, c_deb = r.asientos
    assert c_pm.conciliado and "total del mes" in c_pm.nota
    assert c_deb.conciliado and c_deb.hasta == f(1) and "31/08" in c_deb.nota
    est = {j: p.estado for j, p in conc["BNC"].estado_asiento.items()}
    assert est == {0: EP.CONCILIADO_CAJA, 1: EP.CONCILIADO_CAJA}
    assert {conc["BNC"].estado_mov[i].estado for i in range(3)} == {EP.CONCILIADO_CAJA}
    l31 = next(l for l in r.lineas if l.fecha.day == 31)
    assert l31.estado is EC.EN_TRANSITO and l31.en_libro is False
