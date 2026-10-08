"""WEI sept. 2026: la misma compra de US$ 1.000 en el libro (25/09) y en el Kardex (29/09), a 4 días.
No se empareja sola (±3 días), pero las dos partidas deben explicarse como la misma operación."""
import datetime as dt
from decimal import Decimal as D

from cvp_parser.diagnostico import explicar_divisa_fecha
from cvp_parser.divisas import CuentaDivisa, conciliar_cuenta
from cvp_parser.kardex import Kardex, MovKardex
from cvp_parser.sistema import AsientoLibro, LibroBanco


def test_misma_compra_fuera_de_tres_dias():
    a = AsientoLibro(10, dt.date(2026, 9, 25), "C1", "", "COMPRA 1000 A 1000", D("1000.00"), D("0"), None, None)
    libro = LibroBanco("efectivo.xls", [a], D("0"), D("1000.00"))
    k = MovKardex(44, dt.date(2026, 9, 29), "DIVISAS", D("1000.00"), "Compra", "evento")
    kx = Kardex("kardex.xlsx", "SEP", [k], {}, {})
    r = conciliar_cuenta(CuentaDivisa("Efectivo $", None, "DIVISAS"), libro, None, kx)
    [sl] = [p for p in r.partidas if p.estado == "Solo en libro"]
    assert sl.pista is k and "fuera de ±3 días" in sl.nota
    assert [p.kardex for p in r.partidas if p.estado == "Solo en Kardex"] == [[k]]
    e = explicar_divisa_fecha("Efectivo $", a, k, "libro")
    assert "misma operación" in e.texto and "25/09" in e.texto and "29/09" in e.texto
    assert "4 días" in e.texto and "1.000,00" in e.texto and e.decision == "Justificado"


def test_venta_del_dia_anotada_aparte():
    """WEI 04/09: ventas de efectivo $ completas en la caja; el Kardex pone 546 en una fila aparte («Vierenes»)."""
    from cvp_parser.diagnostico import explicar_venta_aparte
    from cvp_parser.divisas import VENTA_APARTE
    libro = LibroBanco("efectivo.xls", [], D("0"), D("0"))
    dia = dt.date(2026, 9, 4)
    kx = Kardex("kardex.xlsx", "SEP", [MovKardex(20, dia, "DIVISAS", D("1000.00"), "Ventas", "venta_dia"),
                                       MovKardex(21, dia, "DIVISAS", D("546.00"), "Vierenes", "evento")], {}, {})
    r = conciliar_cuenta(CuentaDivisa("Efectivo $", None, "DIVISAS"), libro, {dia: D("1546.00")}, kx)
    [p] = r.partidas
    assert p.estado == VENTA_APARTE and p.kardex[0].fila == 21
    assert r.dias_con_diferencia == []                      # la diferencia del día queda explicada
    e = explicar_venta_aparte("Efectivo $", p.kardex[0], D("1546.00"), D("1000.00"))
    assert "546,00" in e.texto and "fila 21" in e.texto and e.decision == "Aceptar"


def test_kardex_fondo_fecha_como_texto():
    """WEI sept.: fila 131 del Fondo con «07-09» como texto y «RONNY» en la columna de la fecha."""
    from pathlib import Path
    import pytest
    from cvp_parser.kardex import leer_kardex
    ruta = Path(__file__).parent / "fixtures" / "wei_rest_2026_09" / "kardex.xlsx"
    if not ruta.exists():
        pytest.skip("falta el Kardex real de WEI septiembre")
    k = leer_kardex(ruta)
    [m] = [m for m in k.movimientos if m.fila == 131]
    assert (m.medio, m.fecha, m.monto, m.descripcion) == ("FONDO", dt.date(2026, 9, 7), D("-1750.00"),
                                                          "Fondo de efectivo RONNY")
    fondo = [m for m in k.movimientos if m.medio == "FONDO"]
    assert k.saldo_inicial["FONDO"] + sum(m.monto for m in fondo) == k.disponible["FONDO"] == D("2800.00")
    assert len(k.errores) == 1 and "fila 131" in k.errores[0]


def test_kardex_fondo_que_no_suma_avisa(tmp_path):
    import openpyxl
    from cvp_parser.kardex import leer_kardex
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["FECHA", "ZELLE", "BOLIVARES", "DIVISAS", "USDT", "PAGOS DIVISAS", "", "PAGOS BOLIVARES"])
    ws.append(["TOTALES"])
    ws.append([None, None, " FONDO DE EFECTIVO"])
    ws.append([None, None, "NRO.", "VIENEN", 1000])
    ws.append([None, None, "1", dt.datetime(2026, 9, 7), 400])
    ws.append([None, None, "SIN FECHA", None, -200])          # no se puede leer
    ws.append([None, None, None, None, 1200])
    ruta = tmp_path / "k.xlsx"
    wb.save(ruta)
    k = leer_kardex(ruta)
    assert any("no cuadra" in e and "1400.00" in e and "1200" in e for e in k.errores)
