"""Cuentas en divisas: ventas ↔ libro ↔ Kardex. Sintético + WEI REST agosto 2026 (si están los archivos)."""
import datetime as dt
from decimal import Decimal as D
from pathlib import Path

import pytest

from cvp_parser.divisas import CuentaDivisa, conciliar_cuenta
from cvp_parser.kardex import Kardex, MovKardex
from cvp_parser.sistema import AsientoLibro, LibroBanco


def f(d):
    return dt.date(2026, 8, d)


def asiento(d, desc, deb="0", cre="0", ref="X"):
    return AsientoLibro(fila=d, fecha=f(d), comprobante="4", referencia=ref, descripcion=desc,
                        debito_usd=D(deb), credito_usd=D(cre), saldo_usd=None, monto_bs=None)


def test_cuenta_divisa_sintetica():
    cta = CuentaDivisa("Zelle", "ZELLE", "ZELLE")
    libro = LibroBanco("z.xls", [asiento(26, "ZELLE WEI", cre="3831.00"), asiento(28, "ART COCINA", cre="50.00"),
                                 asiento(25, "COMPRA 100", deb="100.00"),
                                 asiento(31, "ZELLE WEI", deb="300.00", ref="VTAS 08/2026")],
                       D("1000.00"), D("-3581.00"))
    ventas = {f(1): D("200.00"), f(2): D("100.00"), f(25): D("0.00")}
    kx = Kardex("k.xlsx", "AGOSTO", [
        MovKardex(1, f(1), "ZELLE", D("200.00"), "Ventas del día", "venta_dia"),
        MovKardex(2, f(2), "ZELLE", D("100.00"), "Ventas del día", "venta_dia"),
        MovKardex(3, f(25), "ZELLE", D("100.00"), "Ventas del día", "venta_dia"),     # no es venta: compra
        MovKardex(4, f(26), "ZELLE", D("-5000.00"), "Reparto", "evento"),
        MovKardex(5, f(26), "ZELLE", D("1169.00"), "Cxc Pagadas", "evento"),
        MovKardex(6, f(29), "ZELLE", D("-7.00"), "Algo", "evento"),
    ], {"ZELLE": D("1000.00")}, {"ZELLE": D("-3581.00")})
    r = conciliar_cuenta(cta, libro, ventas, kx)
    assert r.ventas_ok
    estados = {libro.asientos[p.asientos[0]].descripcion if p.asientos else p.kardex[0].descripcion: p.estado
               for p in r.partidas}
    assert estados == {"ZELLE WEI": "Conciliado (agrupado)", "ART COCINA": "Solo en libro",
                       "COMPRA 100": "Incluido en el día del Kardex", "Algo": "Solo en Kardex"}
    assert r.dias_con_diferencia == []          # la del 25/08 queda explicada
    assert r.saldo_fin == (D("-3581.00"), D("-3581.00"))


def test_ventas_distintas_al_asiento():
    cta = CuentaDivisa("USDT", "USDT", None)
    libro = LibroBanco("u.xls", [asiento(31, "USDT", deb="90.00", ref="VTAS 08/2026")], D("0"), D("90.00"))
    r = conciliar_cuenta(cta, libro, {f(1): D("90.00"), f(31): D("10.00")}, None)
    assert not r.ventas_ok and "hasta el 01/08" in r.ventas_nota


FIX = Path(__file__).parent / "fixtures" / "wei_rest_2026_08"
NEC = ["sistema_efectivo.xls", "sistema_zelle.xls", "sistema_usdt.xls", "sistema_fondo_efectivo.xls",
       "kardex.xlsx", "ventas.xlsx", "edo_bnc.xls", "sistema_bnc.xls"]


@pytest.mark.skipif(not all((FIX / n).exists() for n in NEC), reason="faltan los archivos reales de WEI REST")
def test_wei_divisas():
    from cvp_parser.proceso import procesar_cliente
    rep = procesar_cliente("WEI REST", "2026-08", [("BNC", FIX / "edo_bnc.xls", FIX / "sistema_bnc.xls")],
                           cierre_caja=FIX / "ventas.xlsx", kardex=FIX / "kardex.xlsx",
                           libros_divisas={"Efectivo $": FIX / "sistema_efectivo.xls", "Zelle": FIX / "sistema_zelle.xls",
                                           "USDT": FIX / "sistema_usdt.xls", "Fondo": FIX / "sistema_fondo_efectivo.xls"})
    res = {r.cuenta.nombre: r for r in rep.divisas}
    assert {n: r.ventas_mes for n, r in res.items() if r.ventas_mes is not None} == {
        "Efectivo $": D("11928.00"), "Zelle": D("6017.21"), "USDT": D("4888.39")}
    for r in res.values():
        assert r.ventas_ok and r.saldo_ini[0] == r.saldo_ini[1] and r.saldo_fin[0] == r.saldo_fin[1]
        assert r.dias_con_diferencia == []
        assert not any(p.estado.startswith("Solo") for p in r.partidas)
    assert [p.estado for p in res["Efectivo $"].partidas].count("Incluido en el día del Kardex") == 1
    (cruce,) = rep.cruces_divisas_bancos
    assert "US$ 2600.00" in cruce and "Bs. 2327000.00" in cruce and "diferencia US$ 417.88" in cruce
