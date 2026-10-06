"""Pruebas de la conciliación banco vs. libro con datos sintéticos."""
import datetime as dt
from decimal import Decimal as D

from cvp_parser import Extracto, Movimiento, TotalesBanco
from cvp_parser.conciliacion import EstadoPartida as E, conciliar, conciliar_cliente
from cvp_parser.sistema import AsientoLibro, LibroBanco


def f(d):
    return dt.date(2026, 8, d)


def mov(d, monto, salida=True, desc="X"):
    return Movimiento(f(d), desc, debito=D(monto) if salida else D("0"),
                      credito=D("0") if salida else D(monto))


def asiento(n, d, monto_bs, salida=True, desc="A", usd="1.00", componentes=None):
    return AsientoLibro(fila=n + 1, fecha=f(d), comprobante="C", referencia=str(monto_bs), descripcion=desc,
                        debito_usd=D("0") if salida else D(usd), credito_usd=D(usd) if salida else D("0"),
                        saldo_usd=None, monto_bs=None if monto_bs is None else D(monto_bs),
                        componentes_bs=[D(c) for c in (componentes or [])])


def extracto(movs, banco="B1"):
    return Extracto(banco=banco, cuenta="1", desde=f(1), hasta=f(31), saldo_anterior=D("0"),
                    movimientos=movs, totales_banco=TotalesBanco())


def libro(asientos):
    return LibroBanco("x.xls", asientos, D("0"), D("0"))


def estados(r):
    return {j: p.estado for j, p in r.estado_asiento.items()}


def test_exacto_y_ventana_de_dias():
    e = extracto([mov(3, "100.00"), mov(20, "100.00")])
    r = conciliar(e, libro([asiento(1, 2, "100.00"), asiento(2, 24, "100.00")]))
    assert estados(r) == {0: E.CONCILIADO, 1: E.CONCILIADO}
    assert r.estado_asiento[0].movs == [0] and r.estado_asiento[1].movs == [1]


def test_fuera_de_ventana_no_concilia():
    r = conciliar(extracto([mov(20, "100.00")]), libro([asiento(1, 2, "100.00")]))
    assert estados(r)[0] is E.SOLO_LIBRO
    assert r.estado_mov[0].estado is E.SOLO_BANCO


def test_sentido_distinto_no_es_conciliado():
    r = conciliar(extracto([mov(3, "100.00", salida=False)]), libro([asiento(1, 3, "100.00", salida=True)]))
    assert estados(r)[0] is E.SENTIDO_INVERTIDO


def test_diferencia_de_centimos_se_empareja_pero_no_concilia():
    r = conciliar(extracto([mov(4, "62222.80")]), libro([asiento(1, 4, "62222.81")]))
    p = r.estado_asiento[0]
    assert p.estado is E.DIFERENCIA_MONTO and p.diferencia == D("0.01")


def test_diferencia_mayor_a_la_tolerancia_queda_sola():
    r = conciliar(extracto([mov(4, "100.00")]), libro([asiento(1, 4, "101.50")]))
    assert estados(r)[0] is E.SOLO_LIBRO


def test_un_asiento_contra_varios_movimientos():
    e = extracto([mov(5, "400.00"), mov(5, "250.50"), mov(5, "349.50"), mov(9, "7.00")])
    r = conciliar(e, libro([asiento(1, 5, "1000.00")]))
    p = r.estado_asiento[0]
    assert p.estado is E.CONCILIADO_AGRUPADO and p.movs == [0, 1, 2]


def test_un_movimiento_contra_varios_asientos():
    e = extracto([mov(31, "1080000.00")])
    r = conciliar(e, libro([asiento(1, 31, "419584.05"), asiento(2, 31, "334631.98"),
                            asiento(3, 31, "325783.97")]))
    p = r.estado_mov[0]
    assert p.estado is E.CONCILIADO_AGRUPADO and p.asientos == [0, 1, 2]


def test_asiento_resumen_por_componentes_en_todo_el_mes():
    e = extracto([mov(11, "7184.20"), mov(12, "970.30")])
    r = conciliar(e, libro([asiento(1, 31, None, componentes=["7184.20", "970.30"], usd="10.00")]))
    assert estados(r)[0] is E.CONCILIADO_COMPONENTES


def test_componentes_incompletos_no_concilian_y_lo_dicen():
    e = extracto([mov(11, "7184.20")])
    r = conciliar(e, libro([asiento(1, 31, None, componentes=["7184.20", "22782.48"])]))
    p = r.estado_asiento[0]
    assert p.estado is E.RESUMEN_SIN_MONTO
    assert "1 de 2" in p.nota and "22782.48" in p.nota
    assert r.estado_mov[0].estado is E.SOLO_BANCO  # no se consume el movimiento


def test_registrado_en_el_libro_de_otro_banco():
    e1 = extracto([mov(1, "7000.00")], banco="BNC")
    e2 = extracto([mov(1, "94000.00")], banco="BANPLUS")
    l1 = libro([asiento(1, 1, "94000.00", desc="EL HATO")])
    l2 = libro([asiento(1, 1, "7000.00", desc="EL HATO")])
    res = conciliar_cliente([(e1, l1), (e2, l2)])
    assert res["BNC"].estado_asiento[0].estado is E.OTRO_BANCO
    assert "BANPLUS" in res["BNC"].estado_asiento[0].nota
    assert res["BANPLUS"].estado_mov[0].estado is E.OTRO_BANCO
    assert res["BANPLUS"].estado_asiento[0].estado is E.OTRO_BANCO


def test_pista_para_solo_en_libro_no_concilia():
    e = extracto([mov(27, "12139.56")], banco="BNC")
    res = conciliar_cliente([(e, libro([asiento(1, 19, "12139.56")]))])
    p = res["BNC"].estado_asiento[0]
    assert p.estado is E.SOLO_LIBRO
    assert p.nota.startswith("Posible:") and "8 días" in p.nota
