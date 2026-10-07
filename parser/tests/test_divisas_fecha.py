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
