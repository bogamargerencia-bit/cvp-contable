"""Kardex en PDF (Shiro Alimentos) y ventas del mes tomadas del Kardex cuando no hay cierre de caja."""
import datetime as dt
from decimal import Decimal as D
from pathlib import Path

import pytest

from cvp_parser.clientes import config_de
from cvp_parser.divisas import CuentaDivisa, conciliar_divisas
from cvp_parser.kardex import Kardex, MovKardex, leer_kardex
from cvp_parser.sistema import AsientoLibro, LibroBanco

FIX = Path(__file__).parent / "fixtures" / "shiro_2026" / "kardex_08.pdf"


@pytest.mark.skipif(not FIX.exists(), reason="falta kardex_08.pdf (datos reales de Shiro)")
def test_kardex_pdf_shiro_agosto():
    k = leer_kardex(FIX)
    assert k.errores == []            # los cuatro totales impresos cuadran (efectivo y Zelle)
    assert k.saldo_inicial == {"DIVISAS": D("5993.00"), "ZELLE": D("4201.66")}
    assert k.disponible == {"DIVISAS": D("5631.00"), "ZELLE": D("5123.57")}
    assert sum(k.ventas_dia("DIVISAS").values()) == D("8138.00")
    assert sum(k.ventas_dia("ZELLE").values()) == D("3961.91")
    compras = [m for m in k.no_ventas("DIVISAS") if m.monto > 0]
    assert sum(m.monto for m in compras) == D("7500.00") and len(compras) == 7
    pagos = {(m.fecha, m.monto) for m in k.no_ventas("DIVISAS") if m.monto < 0}
    assert (dt.date(2026, 8, 26), D("-8000.00")) in pagos
    # Concepto partido en dos líneas que invade la columna de Zelle: queda entero en el pago de efectivo
    tramite = next(m for m in k.no_ventas("DIVISAS") if m.fecha == dt.date(2026, 8, 14))
    assert tramite.descripcion.endswith("A RETIRARLOS") and tramite.monto == D("-1000.00")
    # Monto en la línea siguiente a la del concepto
    assert [(m.fecha, m.monto) for m in k.no_ventas("ZELLE")] == [
        (dt.date(2026, 8, 10), D("-3000.00")), (dt.date(2026, 8, 18), D("-40.00"))]


def _libro(asientos):
    return LibroBanco(archivo="x.xls", asientos=asientos, saldo_inicial_usd=D("0"), saldo_final_usd=D("0"))


def _asiento(fila, desc, debe):
    return AsientoLibro(fila=fila, fecha=dt.date(2026, 8, 31), comprobante="1", referencia="08/2026",
                        descripcion=desc, debito_usd=D(debe), credito_usd=D("0"), saldo_usd=None, monto_bs=None)


def test_ventas_del_kardex_sin_cierre_de_caja():
    k = Kardex("k.pdf", "PDF", [
        MovKardex(1, dt.date(2026, 8, 1), "ZELLE", D("100.00"), "Ventas del día", "venta_dia"),
        MovKardex(2, dt.date(2026, 8, 2), "ZELLE", D("50.06"), "Ventas del día", "venta_dia"),
    ], {}, {})
    cta = CuentaDivisa("Zelle", None, "ZELLE", asiento_ventas=r"INGRESO POR VENTAS", ventas_del_kardex=True)
    (r,) = conciliar_divisas([cta], {"Zelle": _libro([_asiento(2, "INGRESO POR VENTAS AGOSTO 2026", "150.00")])}, None, k)
    assert r.ventas_mes == D("150.06") and not r.ventas_ok
    assert "diferencia -0.06" in r.ventas_nota
    # Sin la opción, una cuenta sin columna de ventas no controla el asiento (comportamiento anterior).
    cta2 = CuentaDivisa("Zelle", None, "ZELLE", asiento_ventas=r"INGRESO POR VENTAS")
    (r2,) = conciliar_divisas([cta2], {"Zelle": _libro([_asiento(2, "INGRESO POR VENTAS AGOSTO 2026", "150.00")])}, None, k)
    assert r2.ventas_mes is None and r2.ventas_ok


def test_config_shiro():
    cfg = config_de("Shiro Alimentos C.A.")
    assert cfg is not None and [c.nombre for c in cfg.divisas] == ["Efectivo $", "Zelle"]
    assert all(c.ventas_del_kardex for c in cfg.divisas)
