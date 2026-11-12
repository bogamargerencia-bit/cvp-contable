"""Clasificación por cuenta de un Excel de movimientos del cliente (modo de Delicateses).

La primera parte usa datos ficticios (se generan aquí). La última compara con la clasificación final de
Delicateses de agosto 2026 (archivo real, fuera de git).
"""
import datetime as dt
import sys
from decimal import Decimal as D
from pathlib import Path

import openpyxl
import pytest

from cvp_parser.clasificacion_cuentas import (BS, CLIENTE, DIFERENCIA, EXCLUIDO, PENDIENTE, REGLA, SUGERIDO, USD,
                                              Cuenta, Regla, aprender, leer_movimientos, normalizar, procesar)
from cvp_parser.exportar_cuentas import excel_clasificacion

CAT = [Cuenta("VENTAS", "VENTAS", "INGRESOS"), Cuenta("INVENTARIO", "INVENTARIO", "COMPRAS DE INVENTARIO"),
       Cuenta("NOMINA", "GASTO", "GASTOS"), Cuenta("COMISION BANCARIA", "GASTO", "GASTOS"),
       Cuenta("ALQUILER", "GASTO", "GASTOS"), Cuenta("TRASLADO ENTRE CUENTAS", "TRASLADO ENTRE CUENTAS", "TRASLADOS")]
REGLAS = [
    Regla("empieza", "DEV CREDITO INMEDIATO", None, nota="Revisar siempre a mano"),
    Regla("empieza", "PAGO MOVIL BANCO B", "TRASLADO ENTRE CUENTAS"),
    Regla("empieza", "PAGO MOVIL", "VENTAS", signo="+"),
    Regla("empieza", "COMISION", "COMISION BANCARIA"),
    Regla("empieza", "NOMINA", "NOMINA"),
    Regla("empieza", "ALQUILER", "ALQUILER", "PÉRDIDA POR DIFERENCIAL CAMBIARIO"),
    Regla("igual", "FRIGORIFICO MUNDIAL", "INVENTARIO", nota="Igual que en meses anteriores"),
    Regla("igual", "DISTRIBUIDORA ACME", "INVENTARIO", nota="Igual que en meses anteriores"),
]


def _libro(tmp_path, filas):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "MOV BANCOS"
    ws.append(["Fecha", "CUENTA", "CUENTA 2", "CLASIFICACIÓN", "Descripción", "Monto Bs.", "BCV DÓLAR", "Monto $.",
               "BANCO", "BANCO"])
    for f in filas:
        ws.append(f)
    ruta = tmp_path / "mov.xlsx"
    wb.save(ruta)
    return ruta


def d(dia):
    return dt.datetime(2026, 9, dia)


@pytest.fixture
def ruta(tmp_path):
    filas = [
        [d(1), None, None, None, "Pago Móvil", 1500.25, 100, None, None, "BANCO A"],
        [d(1), None, "UTILIDAD POR DIFERENCIAL CAMBIARIO", None, "COMISION BANCARIA", -1.5, 100, None, None,
         "BANCO A"],
        [d(2), None, None, None, "NOMINA JOSE 02092026", -800, 100, None, None, "BANCO A"],
        [d(2), None, None, None, "FRIGORIDICO MUNDIAL", -300, 100, None, None, "BANCO A"],       # tipeo
        [d(3), None, None, None, "DIF DISTRIBUIDORA ACME", -12.5, 100, None, None, "BANCO A"],
        [d(3), None, None, None, "ALQUILER LOCAL", -2000, 101, None, None, "BANCO A"],
        [d(4), None, None, None, "PROVEEDOR NUEVO XYZ", -450, 101, None, None, "BANCO A"],
        [d(4), None, None, None, "DEV CREDITO INMEDIATO", 450, 101, None, None, "BANCO A"],
        [d(5), "INVENTARIO", None, None, "COMPRA RARA", "-99,50", 101, None, None, "BANCO A"],    # texto
        [d(5), None, None, None, "PAGO MOVIL BANCO B", -1000, 101, None, None, "BANCO A"],
        [d(5), None, None, None, "NOMINA ANA", -2093.3333, 101, None, None, "BANCO A"],          # 4 decimales
        [dt.datetime(2026, 10, 1), None, None, None, "PAGO MOVIL", 10, 101, None, None, "BANCO A"],
        [d(6), None, None, None, "PAGO MOVIL", 0, 0, 25, None, "EFECTIVO"],                     # caja en US$
        [d(6), None, None, None, "", -100, None, None, None, "BANCO A"],                        # sin desc ni tasa
    ]
    return _libro(tmp_path, filas)


def test_lectura_y_hallazgos(ruta):
    L = leer_movimientos(ruta, periodo=(2026, 9))
    assert len(L.filas) == 14
    f = {x.fila: x for x in L.filas}
    assert f[2].monto == D("1500.25") and f[2].tasa == D("100") and f[2].usd == D("15.00")
    assert f[10].monto == D("-99.50") and any("texto" in h for h in f[10].hallazgos)
    assert f[12].monto == D("-2093.3333") and any("más de 2 decimales" in h for h in f[12].hallazgos)
    assert any("fuera del período" in h for h in f[13].hallazgos)
    assert (f[14].moneda, f[14].monto, f[14].usd) == (USD, D("25"), D("25"))
    assert any("Sin descripción" in h for h in f[15].hallazgos) and any("tasa" in h for h in f[15].hallazgos)
    assert normalizar("Transporte  Einor 11082026") == "TRANSPORTE EINOR"
    assert normalizar("Panadería Ñ") == "PANADERIA Ñ"


def test_clasificacion(ruta, tmp_path):
    res = procesar("PRUEBA", "2026-09", ruta, REGLAS, CAT, excluir=[13])
    f = {x.fila: x for x in res.filas}
    assert (f[2].cuenta, f[2].estado) == ("VENTAS", REGLA)
    assert f[3].cuenta == "COMISION BANCARIA" and f[4].cuenta == "NOMINA"
    assert (f[5].cuenta, f[5].estado) == ("INVENTARIO", SUGERIDO) and "FRIGORIFICO MUNDIAL" in f[5].criterio
    assert (f[6].cuenta, f[6].estado) == ("INVENTARIO", DIFERENCIA)
    assert (f[7].cuenta, f[7].cuenta2) == ("ALQUILER", None)          # CUENTA 2 solo la pone el cliente
    assert (f[8].cuenta, f[8].estado) == (None, PENDIENTE)
    assert (f[9].cuenta, f[9].estado) == (None, PENDIENTE) and "a mano" in f[9].criterio
    assert (f[10].cuenta, f[10].estado) == ("INVENTARIO", CLIENTE)
    assert f[11].cuenta == "TRASLADO ENTRE CUENTAS"          # la regla de traslado va antes que PAGO MOVIL
    assert f[13].estado == EXCLUIDO
    # control: todo lo válido está en alguna cuenta o en POR CLASIFICAR
    for mon, (por, total) in res.control().items():
        assert por == total, mon
    assert {x.fila for x in res.pendientes} == {5, 8, 9, 15}
    banco = next(c for c in res.cuadres if c.banco == "BANCO A")
    banco.saldo_inicial = D("10000.00")
    assert banco.saldo_calculado == D("10000.00") + sum(x.monto for x in banco.filas if not x.excluida)
    out = excel_clasificacion(res, tmp_path / "salida.xlsx")
    wb = openpyxl.load_workbook(out)
    assert {"Resumen", "Hallazgos", "Por clasificar", "MOV BANCOS", "Cuadre Banco A", "Cuadre Efectivo",
            "VENTAS", "INVENTARIO", "Catálogo"} <= set(wb.sheetnames)
    mov = wb["MOV BANCOS"]
    assert mov.cell(2, 2).value == "VENTAS" and mov.cell(13, 13).value == "Sí"


def test_asignaciones_y_cuenta2(ruta):
    from cvp_parser.clasificacion_cuentas import ASIGNADA, claves
    k = claves(leer_movimientos(ruta, periodo=(2026, 9)).filas)
    res = procesar("PRUEBA", "2026-09", ruta, REGLAS, CAT,
                   asignadas={k[8]: ("INVENTARIO", False), k[2]: (None, True), "NO|EXISTE#1": ("VENTAS", False)})
    f = {x.fila: x for x in res.filas}
    assert (f[8].cuenta, f[8].estado) == ("INVENTARIO", ASIGNADA)
    assert f[2].excluida and f[2].estado == EXCLUIDO
    assert f[3].cuenta2 == "UTILIDAD POR DIFERENCIAL CAMBIARIO"          # se respeta lo del cliente
    hall = res.lectura.hallazgos
    assert any("ya no encuentran su movimiento" in h.detalle for h in hall)
    assert any(h.tipo == "CUENTA 2 (del cliente)" and "COMISION BANCARIA" in h.detalle for h in hall)


def test_reglas_de_base():
    from cvp_parser.clasificacion_cuentas import reglas_de_base
    rs = reglas_de_base([
        {"tipo": "empieza", "patron": "pago móvil", "cuenta": "VENTAS", "prioridad": 50, "sentido": "ingreso"},
        {"tipo": "empieza", "patron": "Pago Movil Banesco", "cuenta": "TRASLADO ENTRE CUENTAS", "prioridad": 10},
        {"tipo": "exacta", "patron": "Frigorífico  Mundial", "cuenta": "INVENTARIO", "banco": "banesco"},
        {"tipo": "regex", "patron": r"^\s*COBR", "cuenta": "VENTAS"},
        {"tipo": "empieza", "patron": "DEV CREDITO", "cuenta": None, "nota": "a mano"},
    ])
    assert [(r.tipo, r.patron) for r in rs][:3] == [("empieza", "PAGO MOVIL BANESCO"), ("empieza", "PAGO MOVIL"),
                                                    ("igual", "FRIGORIFICO MUNDIAL")]
    assert rs[1].signo == "+" and rs[2].bancos == ("BANESCO",) and rs[3].patron == r"^\s*COBR"
    assert rs[4].cuenta is None


def test_claves_estables(ruta):
    from cvp_parser.clasificacion_cuentas import claves
    L = leer_movimientos(ruta, periodo=(2026, 9))
    k = claves(L.filas)
    assert k[2] == "BANCO A|2026-09-01|1500.25|PAGO MOVIL#1"
    assert len(set(k.values())) == len(k)


def test_aprender():
    from cvp_parser.clasificacion_cuentas import Fila
    filas = [Fila(1, None, "Proveedor Uno", "B", BS, D("-1"), None, "INVENTARIO"),
             Fila(2, None, "PROVEEDOR UNO 123", "B", BS, D("-2"), None, "INVENTARIO"),
             Fila(3, None, "DEV CREDITO", "B", BS, D("5"), None, "VENTAS"),
             Fila(4, None, "DEV CREDITO", "B", BS, D("5"), None, "INVENTARIO"),
             Fila(5, None, "NOMINA ANA", "B", BS, D("-5"), None, "NOMINA")]
    nuevas = aprender(filas, REGLAS)
    assert [(r.patron, r.cuenta) for r in nuevas] == [("PROVEEDOR UNO", "INVENTARIO")]   # ambiguas y ya cubiertas no


def test_copia_de_bloque_y_grupo_repetido(tmp_path):
    montos = [100 + 7 * i for i in range(12)]
    filas = [[d(1), None, None, None, f"MOV {i}", m, 100, None, None, "B"] for i, m in enumerate(montos)]
    filas += [[d(2), None, None, None, "OTRO", 5, 100, None, None, "B"]]
    # copia con dos filas intercambiadas y una intercalada
    copia = montos[:]
    copia[3], copia[4] = copia[4], copia[3]
    copia.insert(6, 3)
    filas += [[d(30), None, None, None, "", m, 100, None, None, "B"] for m in copia]
    L = leer_movimientos(_libro(tmp_path, filas), periodo=(2026, 9))
    dup = [h for h in L.hallazgos if h.tipo == "Posible duplicado"]
    # la zona sin descripción (15–27) es la que se señala como probable copia
    assert len(dup) == 1 and dup[0].filas == "15–27 y 2–13" and "13 vienen sin descripción" in dup[0].detalle


# --- Datos reales: Delicateses agosto 2026 -------------------------------------------------------------------

FX = Path(__file__).parent / "fixtures" / "delicateses_2026_08"
REAL = pytest.mark.skipif(not (FX / "agosto_final.xlsx").exists() or not (FX / "reglas_base.py").exists(),
                          reason="faltan los archivos reales de Delicateses (no van en git)")


@REAL
def test_delicateses_agosto_reproduce_la_clasificacion_final(tmp_path):
    sys.path.insert(0, str(FX))
    from reglas_base import CATALOGO, REGLAS as BASE
    final = leer_movimientos(FX / "agosto_final.xlsx", periodo=(2026, 8))
    dup = set(range(904, 974))
    reglas = aprender([f for f in final.filas if f.fila not in dup], BASE) + BASE
    verdad = {f.fila: f.cuenta_cliente for f in final.filas}
    crudo = tmp_path / "crudo.xlsx"
    wb = openpyxl.load_workbook(FX / "agosto_final.xlsx")
    ws = wb["MOV BANCOS"]
    for r in range(2, ws.max_row + 1):
        ws.cell(r, 2).value = ws.cell(r, 4).value = None
    wb.save(crudo)
    res = procesar("Delicateses", "2026-08", crudo, reglas, CATALOGO, excluir=dup,
                   saldos={"BANESCO": (D("635917.59"), None), "MERCANTIL": (D("1719212.74"), None),
                           "EFECTIVO": (D("4426"), None), "ZELLE": (D("8447.71"), None)})
    distintas = [(f.fila, f.descripcion) for f in res.filas
                 if f.moneda == BS and not f.excluida and f.cuenta != verdad[f.fila]]
    assert distintas == [(1898, "DEV CREDITO INMEDIATO"), (1911, "DEV CREDITO INMEDIATO")]   # siempre a mano
    saldo = {c.banco: c.saldo_calculado for c in res.cuadres}
    # Saldos calculados en la revisión de agosto (las fracciones vienen de los montos con más de 2 decimales).
    assert round(saldo["BANESCO"], 2) == D("75733.05") and round(saldo["MERCANTIL"], 2) == D("327129.29")
    assert (saldo["EFECTIVO"], saldo["ZELLE"]) == (D("6982.00"), D("5003.92"))
    hall = res.lectura.hallazgos
    assert any(h.tipo == "Posible duplicado" and h.filas.startswith("904–973") for h in hall)
    assert any(h.filas == "900–903 y 1011–1014" for h in hall)


@REAL
def test_delicateses_mes_nuevo_simulado():
    """Aprende del 1 al 15 y clasifica del 16 al 31: nada mal clasificado; lo nuevo queda por clasificar."""
    sys.path.insert(0, str(FX))
    from reglas_base import CATALOGO, REGLAS as BASE
    from cvp_parser.clasificacion_cuentas import clasificar
    import copy
    final = leer_movimientos(FX / "agosto_final.xlsx", periodo=(2026, 8))
    bs = [f for f in final.filas if f.moneda == BS and not 904 <= f.fila <= 973]
    verdad = {f.fila: f.cuenta_cliente for f in bs}
    reglas = aprender([f for f in bs if f.fecha.day <= 15], BASE) + BASE
    resto = copy.deepcopy([f for f in bs if f.fecha.day > 15])
    for f in resto:
        f.cuenta_cliente = None
    clasificar(resto, reglas, CATALOGO)
    mal = [(f.fila, f.descripcion, f.cuenta) for f in resto if f.cuenta and f.cuenta != verdad[f.fila]]
    assert not mal
    assert sum(1 for f in resto if f.cuenta) / len(resto) > 0.9
