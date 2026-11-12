"""Clasificación por cuenta a partir del Excel de movimientos del cliente (modo «Clasificación por cuenta»).

Las pruebas genéricas usan un archivo ficticio generado aquí; las de agosto 2026 usan el archivo real de
Delicateses (fixtures, fuera de git).
"""
import datetime as dt
from decimal import Decimal as D
from pathlib import Path

import openpyxl
import pytest

from cvp_parser.clasificacion_cuenta import (POR_CLASIFICAR, Regla, clasificar_archivo, clasificar_descripcion,
                                             claves, excel_clasificacion, leer_movimientos, normalizar,
                                             reglas_desde_clasificado, resumen)

REAL = Path(__file__).parent / "fixtures" / "delicateses_2026_08" / "clasificado.xlsx"
SIN_REAL = pytest.mark.skipif(not REAL.exists(), reason="falta el archivo real de Delicateses agosto")

REGLAS = [
    Regla("PAGO MOVIL", "VENTAS", "VENTAS"),
    Regla("INGRESO DE VENTAS", "VENTAS", "VENTAS"),
    Regla("COMISION BANCARIA", "COMISION BANCARIA", "GASTO", tipo="empieza"),
    Regla("PROVEEDOR UNO", "INVENTARIO", "INVENTARIO", tipo="contiene"),
    Regla("NOMINA", "NOMINA", "GASTO", tipo="contiene"),
    Regla("TRASPASO", "TRASLADO ENTRE CUENTAS", "TRASLADO ENTRE CUENTAS", sentido="ingreso"),
    Regla("TRASPASO", "CXC SOCIOS", "CXC SOCIOS", sentido="egreso"),
]


def _archivo(tmp_path, filas, banco_repetido=True):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "MOV BANCOS"
    enc = ["Fecha", "CUENTA", "CUENTA 2", "CLASIFICACIÓN", "Descripción", "Monto Bs.", "BCV DÓLAR", "Monto $.",
           "BANCO"] + (["BANCO"] if banco_repetido else [])
    ws.append(enc)
    for f in filas:
        fecha, desc, bs, tasa, usd, banco = f[:6]
        c2 = f[6] if len(f) > 6 else None
        fila = [fecha, None, c2, None, desc, bs, tasa, usd]
        fila += [None, banco] if banco_repetido else [banco]
        ws.append(fila)
    ruta = tmp_path / "movimientos.xlsx"
    wb.save(ruta)
    return ruta


def d(n):
    return dt.datetime(2026, 9, n)


def test_normalizar_y_prioridad():
    assert normalizar("  Comisión   bancaria. ") == "COMISION BANCARIA"
    a = clasificar_descripcion("Comision bancaria 0,3%", "BANESCO", "egreso", REGLAS)
    assert (a.cuenta, a.clasificacion) == ("COMISION BANCARIA", "GASTO")
    # «contiene» solo por palabra completa
    assert clasificar_descripcion("NOMINAS", "BANESCO", "egreso", REGLAS).cuenta is None
    assert clasificar_descripcion("PAGO NOMINA JUAN", "BANESCO", "egreso", REGLAS).cuenta == "NOMINA"
    # la exacta gana a la que contiene
    r = REGLAS + [Regla("PAGO NOMINA JUAN", "OTROS GASTOS", "GASTO")]
    assert clasificar_descripcion("pago nómina juan", "MERCANTIL", "egreso", r).cuenta == "OTROS GASTOS"
    # el sentido decide
    assert clasificar_descripcion("TRASPASO", "BANESCO", "ingreso", REGLAS).cuenta == "TRASLADO ENTRE CUENTAS"
    assert clasificar_descripcion("TRASPASO", "BANESCO", "egreso", REGLAS).cuenta == "CXC SOCIOS"


def test_reglas_en_conflicto_quedan_por_clasificar():
    r = [Regla("ALQUILER", "ALQUILER", "GASTO", tipo="contiene"), Regla("LOCAL", "OTROS GASTOS", "GASTO",
                                                                          tipo="contiene")]
    a = clasificar_descripcion("ALQUILER LOCAL", "BANESCO", "egreso", r)
    assert a.cuenta is None and "conflicto" in a.criterio
    # una regla de banco gana a la general
    r = [Regla("ZELLE", "VENTAS", "VENTAS"), Regla("ZELLE", "CAMBIO", "CAMBIO", banco="Mercantil")]
    assert clasificar_descripcion("ZELLE", "MERCANTIL", "ingreso", r).cuenta == "CAMBIO"
    assert clasificar_descripcion("ZELLE", "BANESCO", "ingreso", r).cuenta == "VENTAS"


def test_lectura_controles_y_cuadre(tmp_path):
    filas = [
        (d(1), "PAGO MOVIL", 1000.10, 200.5, None, "BANESCO"),
        (d(1), "COMISION BANCARIA", -3.0, 200.5, None, "BANESCO"),
        (d(2), "PROVEEDOR UNO CA", "-500,25", 201.0, None, "BANESCO"),          # monto como texto
        (d(2), "NOMINA", -2093.3333333, 201.0, None, "BANESCO"),                # más de 2 decimales
        (d(3), "GASTO RARO", -10.0, 201.0, None, "BANESCO"),                    # sin regla
        (None, None, None, None, None, None),                                   # fila vacía
        (None, "-", None, None, None, None),                                    # un guion suelto
        (d(3), "SIN BANCO", 50.0, 201.0, None, None),                           # fila incompleta
        (d(4), "INGRESO DE VENTAS", 0, 0, 35, "zelle"),                         # US$
        (dt.datetime(2026, 10, 1), "INGRESO DE VENTAS", 0, 0, 20, "zelle"),     # fuera del período
        (d(5), "PROVEEDOR UNO", -100.0, 202.0, None, "MERCANTIL", "UTILIDAD POR DIFERENCIAL CAMBIARIO"),
    ]
    ruta = _archivo(tmp_path, filas)
    res = clasificar_archivo("CLIENTE PRUEBA", "2026-09", ruta, REGLAS,
                             saldos={"BANESCO": (D("100.00"), None), "ZELLE": (D("10.00"), D("65.00"))})
    assert [m.banco for m in res.movimientos] == ["BANESCO"] * 5 + ["ZELLE"] * 2 + ["MERCANTIL"]
    assert [m.monto for m in res.movimientos] == [D("1000.10"), D("-3.00"), D("-500.25"), D("-2093.3333333"),
                                                 D("-10.00"), D("35"), D("20"), D("-100.00")]
    assert [m.cuenta for m in res.movimientos] == ["VENTAS", "COMISION BANCARIA", "INVENTARIO", "NOMINA", None,
                                                  "VENTAS", "VENTAS", "INVENTARIO"]
    assert res.movimientos[5].moneda == "USD" and res.movimientos[5].usd == D("35")
    assert res.movimientos[0].usd == D("4.99")                                  # 1000,10 / 200,5
    tipos = {(h.tipo, h.banco, h.filas): h.detalle for h in res.hallazgos}
    assert any("texto" in v for (t, b, f), v in tipos.items() if b == "BANESCO" and f == "4")
    assert any("más de 2 decimales" in v for (t, b, f), v in tipos.items() if f == "5")
    assert any("incompleta" in v and "banco" in v for (t, b, f), v in tipos.items() if f == "9")
    assert any("fuera del período" in v for (t, b, f), v in tipos.items() if b == "ZELLE" and f == "11")
    assert any("CUENTA 2" in v for v in tipos.values())
    # Banesco: 100 + 1000,10 − 3 − 500,25 − 2093,3333333 − 10 < 0  → error de saldo negativo
    neg = [h for h in res.hallazgos if h.tipo == "Error" and "negativo" in h.detalle]
    assert len(neg) == 1 and neg[0].banco == "BANESCO" and neg[0].filas == "desde 5"
    banesco = next(c for c in res.cuadres if c.banco == "BANESCO")
    assert (banesco.ingresos, banesco.egresos) == (D("1000.10"), D("2606.5833333"))
    zelle = next(c for c in res.cuadres if c.banco == "ZELLE")
    assert zelle.saldo_final_calculado == D("65.00") and zelle.diferencia == 0
    assert [m.fila for m in res.pendientes] == [6]


def test_bloque_duplicado(tmp_path):
    montos = [100.5, -20.0, 300.25, -4.1, 55.0, 61.0]
    filas = [(d(1 + i // 3), "PAGO MOVIL" if m > 0 else "COMISION BANCARIA", m, 200.0, None, "BANESCO")
             for i, m in enumerate(montos + [999.0] + montos)]
    res = clasificar_archivo("X", "2026-09", _archivo(tmp_path, filas), REGLAS)
    dup = [h for h in res.hallazgos if "duplicado" in h.detalle]
    assert len(dup) == 1 and dup[0].filas == "2–7 y 9–14" and "6 filas" in dup[0].detalle
    # comisiones iguales seguidas no son un bloque
    filas = [(d(1), "COMISION BANCARIA", -21.45, 200.0, None, "BANESCO")] * 12
    res = clasificar_archivo("X", "2026-09", _archivo(tmp_path, filas), REGLAS)
    assert not [h for h in res.hallazgos if "duplicado" in h.detalle]


def test_decisiones_del_analista(tmp_path):
    filas = [(d(1), "GASTO RARO", -10.0, 200.0, None, "BANESCO"), (d(1), "GASTO RARO", -10.0, 200.0, None, "BANESCO")]
    ruta = _archivo(tmp_path, filas)
    res = clasificar_archivo("X", "2026-09", ruta, REGLAS)
    k = claves(res.movimientos)
    assert len(set(k.values())) == 2                       # dos movimientos iguales: claves distintas
    from cvp_parser.clasificacion_cuenta import clave_movimiento
    res = clasificar_archivo("X", "2026-09", ruta, REGLAS,
                             decisiones={clave_movimiento(res.movimientos[0]): ("OTROS GASTOS", "GASTO")})
    assert [m.cuenta for m in res.movimientos] == ["OTROS GASTOS", "OTROS GASTOS"]
    assert {m.origen for m in res.movimientos} == {"decision"}


def test_excel(tmp_path):
    filas = [(d(1), "PAGO MOVIL", 1000.10, 200.5, None, "BANESCO"),
             (d(2), "GASTO / RARO", -10.0, 201.0, None, "MERCANTIL"),
             (d(4), "INGRESO DE VENTAS", 0, 0, 35, "EFECTIVO")]
    res = clasificar_archivo("CLIENTE PRUEBA", "2026-09", _archivo(tmp_path, filas, banco_repetido=False), REGLAS)
    out = excel_clasificacion(res, tmp_path / "out.xlsx")
    wb = openpyxl.load_workbook(out)
    assert wb.sheetnames[:3] == ["Resumen", "Hallazgos", "MOV BANCOS"]
    assert {"BANESCO (Bs.)", "MERCANTIL (Bs.)", "EFECTIVO (US$)", "VENTAS", POR_CLASIFICAR} <= set(wb.sheetnames)
    mb = wb["MOV BANCOS"]
    assert [mb.cell(r, 2).value for r in (2, 3, 4)] == ["VENTAS", POR_CLASIFICAR, "VENTAS"]
    assert mb["H2"].value == "=IF(N(G2)=0,\"\",ROUND(F2/G2,2))" and mb["H4"].value == 35
    assert mb["B3"].fill.start_color.rgb.endswith("FFF2CC")
    assert [c.value for c in wb["Resumen"][4]] == ["Cuenta", "Clasificación", "N° Movs", "BANESCO (Bs.)",
                                                   "MERCANTIL (Bs.)", "EFECTIVO (US$)", "Total US$"]
    [(t, ls)] = [g for g in resumen(res) if g[0] == "INGRESOS"]
    assert ls[0].movimientos == 2 and ls[0].por_banco == {"BANESCO": D("1000.10"), "EFECTIVO": D("35")}
    assert ls[0].usd == D("39.99")


@SIN_REAL
def test_agosto_real_reproduce_la_clasificacion_entregada():
    movs, _ = leer_movimientos(REAL)
    assert len(movs) == 2063
    reglas, ambiguas = reglas_desde_clasificado(movs)
    assert ambiguas == ["DEV CREDITO INMEDIATO"]          # depende del caso: lo decide el analista
    res = clasificar_archivo("DELICATESES", "2026-08", REAL, reglas,
                             saldos={"BANESCO": (D("635917.59"), None), "MERCANTIL": (D("1719212.74"), None),
                                     "EFECTIVO": (D("4426"), None), "ZELLE": (D("8447.71"), None)})
    distintos = [m for m in res.movimientos if m.cuenta_cliente and
                 (m.cuenta, m.clasificacion) != (m.cuenta_cliente, m.clasif_cliente)]
    assert [m.descripcion for m in distintos] == ["DEV CREDITO INMEDIATO"] * 2 and all(m.cuenta is None
                                                                                       for m in distintos)
    # Efectivo y Zelle (sin cuenta en el archivo): 92 de 121 se clasifican con las mismas reglas
    usd = [m for m in res.movimientos if m.moneda == "USD"]
    assert len(usd) == 121 and sum(1 for m in usd if m.cuenta) == 92
    assert len(res.pendientes) == 31
    c = {x.banco: x for x in res.cuadres}
    assert (c["EFECTIVO"].saldo_final_calculado, c["ZELLE"].saldo_final_calculado) == (D("6982"), D("5003.92"))
    neg = [h for h in res.hallazgos if "negativo" in h.detalle]
    assert [(h.banco, h.filas) for h in neg] == [("BANESCO", "desde 704")]
