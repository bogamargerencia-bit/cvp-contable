"""WEI: el asiento «VTAS mm/aaaa — 100% BANCO PAGO MOVIL» con el total en Bs. en la Referencia se concilia con
los cobros por pago móvil del banco (total exacto del mes), sin quitarle esos cobros al cruce con el cierre de caja."""
from decimal import Decimal as D

import pytest

import test_wei_rest as tw
from cvp_parser import proceso
from cvp_parser.conciliacion import EstadoPartida as E
from cvp_parser.naturaleza import E_PAGO_MOVIL
from cvp_parser.revision import aplicar
from cvp_parser.sistema import AsientoLibro, leer_libro

pytestmark = pytest.mark.skipif(not tw.VENTAS.exists(), reason="faltan los archivos reales de WEI")


def _correr(monkeypatch, monto):
    def leer(ruta, *a, **k):
        lib = leer_libro(ruta, *a, **k)
        if "100" in str(ruta):
            u = lib.asientos[-1]
            lib.asientos.append(AsientoLibro(9999, u.fecha, "X", str(monto), "VTAS 08/2026 100% BANCO PAGO MOVIL",
                                             D("1500.00"), D("0"), None, monto))
        return lib
    monkeypatch.setattr(proceso, "leer_libro", leer)
    return proceso.procesar_cliente("WEI REST", "2026-08", tw.ARCHIVOS, cierre_caja=tw.VENTAS)


def _caja_pm(rep):
    return sorted((l.fecha, l.estado.value, l.monto) for l in rep.caja.lineas
                  if "100%" in l.medio.upper() and "MOVIL" in l.medio.upper())


def test_vtas_pago_movil_total_exacto(monkeypatch):
    base = proceso.procesar_cliente("WEI REST", "2026-08", tw.ARCHIVOS, cierre_caja=tw.VENTAS)
    rc0 = base.conciliaciones["100_BANCO"]
    pm = [x for x in base.clasificados["100_BANCO"] if x.naturaleza == E_PAGO_MOVIL and x.mov.credito]
    libres = sum((x.mov.credito for x in pm if rc0.estado_mov[x.indice].estado is not E.CONCILIADO), D("0"))
    assert libres == D("1123951.05")
    rep = _correr(monkeypatch, libres)
    rc = rep.conciliaciones["100_BANCO"]
    p = rc.estado_asiento[len(rc.libro.asientos) - 1]
    assert p.estado is E.CONCILIADO_TOTAL and len(p.movs) == 19
    assert _caja_pm(rep) == _caja_pm(base)          # el cruce con la caja no cambia


def test_vtas_pago_movil_con_total_completo_explica(monkeypatch):
    rep = _correr(monkeypatch, D("1143951.05"))     # incluye un cobro de 20.000 que ya tiene su propio asiento
    [p] = [x for x in aplicar(rep).pendientes if x.descripcion.startswith("VTAS 08/2026")]
    assert p.tipo == "Solo en libro" and "20.000,00" in p.explicacion and "dos veces" in p.explicacion
    assert "1.123.951,05" in p.que_hacer
