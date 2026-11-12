"""Excel de la clasificación por cuenta (modo «Clasificación por cuenta», p. ej. Delicateses).

Hojas:
  - Resumen: total por cuenta (agrupado como en el catálogo) con fórmulas SUMIFS sobre MOV BANCOS, en Bs., en US$
    al BCV y por banco/caja, más los controles (todo lo clasificado = todos los movimientos válidos).
  - Hallazgos: lo que hay que revisar con el cliente (duplicados, montos en texto o con más de 2 decimales, fechas…).
  - Por clasificar: movimientos sin cuenta y los sugeridos por parecido, para que el analista decida.
  - MOV BANCOS: la hoja del cliente con CUENTA / CUENTA 2 / CLASIFICACIÓN, el criterio de cada fila y «Excluir».
    Si el analista cambia una CUENTA o marca Excluir = Sí aquí, el Resumen y los cuadres se recalculan.
  - Un cuadre por banco/caja: saldo inicial y final del cliente (celdas amarillas), saldo acumulado fila a fila.
  - Una hoja por cuenta con sus movimientos.
  - Catálogo: cuentas, clasificación y grupo.
Los montos en Bs. se suman tal cual; el US$ de cada fila en Bs. es ROUND(Bs. / BCV, 2).
"""
from __future__ import annotations

import re
from collections import OrderedDict
from decimal import Decimal
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

from .clasificacion_cuentas import (ASIGNADA, BS, CLIENTE, DIFERENCIA, EXCLUIDO, PENDIENTE, POR_CLASIFICAR, REGLA,
                                    SUGERIDO, USD, Resultado)
from .exportar import B, BLANCA, ENC, FECHA, NOTA, NUM, SUB, TIT, TOT, F, _fila

AMARILLO = PatternFill("solid", start_color="FFF2CC")
NARANJA = PatternFill("solid", start_color="FCE4D6")
GRIS = PatternFill("solid", start_color="EDEDED")
VERDE = PatternFill("solid", start_color="E2EFDA")
TASA = "#,##0.00##"
MESES = ["", "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio", "Agosto", "Septiembre", "Octubre",
         "Noviembre", "Diciembre"]
FILL_ESTADO = {PENDIENTE: AMARILLO, SUGERIDO: NARANJA, EXCLUIDO: GRIS}

# Columnas de MOV BANCOS
COL = dict(fecha=1, cuenta=2, cuenta2=3, clasif=4, desc=5, bs=6, tasa=7, usd=8, banco=9, moneda=10, estado=11,
           criterio=12, excluir=13, fila=14)
L = {k: get_column_letter(v) for k, v in COL.items()}


def _enc(ws, r: int, titulos: list[str], anchos: list[int] | None = None) -> None:
    for i, t in enumerate(titulos, 1):
        c = ws.cell(r, i, t)
        c.font, c.fill = BLANCA, ENC
        c.alignment = Alignment(wrap_text=True, vertical="center")
        if anchos:
            ws.column_dimensions[get_column_letter(i)].width = anchos[i - 1]


def _nombre_hoja(n: str, usados: set[str]) -> str:
    base = re.sub(r"[\\/*?:\[\]]", "-", n)[:31]
    nombre, k = base, 2
    while nombre.upper() in usados:
        nombre = f"{base[:28]} {k}"
        k += 1
    usados.add(nombre.upper())
    return nombre


def excel_clasificacion(res: Resultado, salida: Path) -> Path:
    wb = Workbook()
    resumen = wb.active
    resumen.title = "Resumen"
    hall = wb.create_sheet("Hallazgos")
    pend = wb.create_sheet("Por clasificar")
    mov = wb.create_sheet("MOV BANCOS")
    anio, mes = (int(x) for x in res.periodo.split("-"))
    usados = {"RESUMEN", "HALLAZGOS", "POR CLASIFICAR", "MOV BANCOS", "CATÁLOGO"}

    ultima = _hoja_mov(mov, res)
    rng = lambda k: f"'MOV BANCOS'!${L[k]}$2:${L[k]}${ultima}"
    bancos = [c.banco for c in res.cuadres]
    bancos.sort(key=lambda b: (next(c.moneda for c in res.cuadres if c.banco == b) != BS, b))
    hojas_banco = {}
    for c in sorted(res.cuadres, key=lambda c: bancos.index(c.banco)):
        hojas_banco[c.banco] = _nombre_hoja(f"Cuadre {c.banco.title()}", usados)
        _hoja_cuadre(wb.create_sheet(hojas_banco[c.banco]), c, res, rng, ultima, anio, mes)
    hojas_cuenta = {}
    por = res.por_cuenta()
    for cta in [c.nombre for c in res.catalogo] + sorted(set(por) - {c.nombre for c in res.catalogo}):
        if cta in por:
            hojas_cuenta[cta] = _nombre_hoja(cta, usados)
            _hoja_cuenta(wb.create_sheet(hojas_cuenta[cta]), cta, por[cta], res)
    cat = wb.create_sheet("Catálogo")
    _hoja_catalogo(cat, res)
    _hoja_resumen(resumen, res, rng, bancos, hojas_cuenta, anio, mes)
    _hoja_hallazgos(hall, res, hojas_banco)
    _hoja_pendientes(pend, res)
    wb.save(salida)
    return salida


def _hoja_mov(ws, res: Resultado) -> int:
    _enc(ws, 1, ["Fecha", "CUENTA", "CUENTA 2", "CLASIFICACIÓN", "Descripción", "Monto Bs.", "BCV DÓLAR", "Monto $.",
                 "BANCO", "Moneda", "Estado", "Criterio de clasificación", "Excluir", "Fila original"],
         [11, 26, 30, 22, 38, 15, 10, 13, 12, 8, 20, 55, 8, 8])
    dv = DataValidation(type="list", formula1='"Sí,No"', allow_blank=True)
    ws.add_data_validation(dv)
    r = 1
    for f in res.filas:
        r += 1
        usd = f.monto if f.moneda == USD else (f"=IF(N({L['tasa']}{r})>0,ROUND({L['bs']}{r}/{L['tasa']}{r},2),\"\")")
        _fila(ws, r, [f.fecha, f.cuenta, f.cuenta2,
                      f'=IF({L["cuenta"]}{r}="","",IFERROR(VLOOKUP({L["cuenta"]}{r},Catálogo!$A:$B,2,0),"¿?"))',
                      f.descripcion, f.monto if f.moneda == BS else 0, f.tasa, usd, f.banco, f.moneda, f.estado,
                      f.criterio + (" · " + " ".join(f.hallazgos) if f.hallazgos else ""),
                      "Sí" if f.excluida else "No", f.fila],
              {1: FECHA, 6: NUM, 7: TASA, 8: NUM}, fill=FILL_ESTADO.get(f.estado))
        dv.add(ws.cell(r, COL["excluir"]))
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = f"A1:{L['fila']}{max(r, 2)}"
    return max(r, 2)


def _hoja_resumen(ws, res: Resultado, rng, bancos: list[str], hojas_cuenta: dict, anio: int, mes: int) -> None:
    ws["A1"] = f"{res.cliente.upper()} – RESUMEN POR CUENTA · {MESES[mes].upper()} {anio}"
    ws["A1"].font = TIT
    ws["A2"] = ("Fuente: MOV BANCOS (filas con Excluir = Sí no suman). Negativo = egreso, positivo = ingreso. "
                "Cada cuenta tiene su hoja con el detalle (clic en el nombre).")
    ws["A2"].font = NOTA
    bs = [b for b in bancos if next(c.moneda for c in res.cuadres if c.banco == b) == BS]
    us = [b for b in bancos if b not in bs]
    tit = ["Cuenta", "Clasificación", "N° Movs", "Monto Bs.", "Monto $ (BCV)"] + [f"$ {b.title()}" for b in bs] + \
          [f"US$ {b.title()}" for b in us] + ["$ total (BCV + cajas US$)"]
    _enc(ws, 4, tit, [34, 24, 9, 17, 15] + [14] * (len(bs) + len(us)) + [17])
    n_cols = len(tit)
    no_excl = f',{rng("excluir")},"<>Sí"'

    def formulas(r: int, crit: str) -> list:
        """crit: condición sobre la CUENTA ya escrita como 'rango,valor'."""
        cnt = f"=COUNTIFS({crit}{no_excl},{rng('banco')},\"<>\")"
        sbs = f"=SUMIFS({rng('bs')},{crit}{no_excl},{rng('moneda')},\"{BS}\")"
        sus = f"=SUMIFS({rng('usd')},{crit}{no_excl},{rng('moneda')},\"{BS}\")"
        pb = [f"=SUMIFS({rng('usd')},{crit}{no_excl},{rng('banco')},\"{b}\")" for b in bs + us]
        c_ini = get_column_letter(5)
        c_fin = get_column_letter(5 + len(bs) + len(us))
        primera_us = get_column_letter(6 + len(bs))
        tot = f"=E{r}" + (f"+SUM({primera_us}{r}:{c_fin}{r})" if us else "")
        return [cnt, sbs, sus] + pb + [tot]

    grupos: "OrderedDict[str, list]" = OrderedDict()
    por = res.por_cuenta()
    for c in res.catalogo:
        if c.nombre in por:
            grupos.setdefault(c.grupo, []).append((c.nombre, c.clasificacion))
    fuera = sorted(set(por) - {c.nombre for c in res.catalogo} - {POR_CLASIFICAR})
    if fuera:
        grupos["FUERA DEL CATÁLOGO (revisar)"] = [(n, "¿?") for n in fuera]
    if POR_CLASIFICAR in por:
        grupos["POR CLASIFICAR (resaltados)"] = [(POR_CLASIFICAR, POR_CLASIFICAR)]

    r, totales = 5, []
    for grupo, cuentas in grupos.items():
        ws.cell(r, 1, grupo).font = SUB
        r += 1
        ini = r
        for nombre, clasif in cuentas:
            crit = f'{rng("cuenta")},"{nombre}"' if nombre != POR_CLASIFICAR else f'{rng("cuenta")},""'
            _fila(ws, r, [nombre, clasif] + formulas(r, crit), {i: NUM for i in range(4, n_cols + 1)})
            if nombre in res.por_cuenta() and nombre in hojas_cuenta:
                ws.cell(r, 1).hyperlink = f"#'{hojas_cuenta[nombre]}'!A1"
                ws.cell(r, 1).font = Font(name="Arial", size=10, color="0563C1", underline="single")
            if nombre == POR_CLASIFICAR:
                for i in range(1, n_cols + 1):
                    ws.cell(r, i).fill = AMARILLO
            r += 1
        _fila(ws, r, [f"Total {grupo}", None] + [f"=SUM({get_column_letter(i)}{ini}:{get_column_letter(i)}{r - 1})"
                                                  for i in range(3, n_cols + 1)],
              {i: NUM for i in range(4, n_cols + 1)}, fill=TOT, font=B)
        totales.append(r)
        r += 2
    _fila(ws, r, ["TOTAL GENERAL (flujo neto del mes)", None] +
          ["=" + "+".join(f"{get_column_letter(i)}{t}" for t in totales) for i in range(3, n_cols + 1)],
          {i: NUM for i in range(4, n_cols + 1)}, fill=TOT, font=B)
    tg = r
    r += 2
    ws.cell(r, 1, "Controles (deben dar 0)").font = SUB
    r += 1
    ctr = [
        ("Movimientos resumidos − movimientos válidos de MOV BANCOS",
         f"=C{tg}-COUNTIFS({rng('excluir')},\"<>Sí\",{rng('banco')},\"<>\")", None),
        ("Monto Bs. resumido − Monto Bs. de MOV BANCOS",
         f"=ROUND(D{tg}-SUMIFS({rng('bs')},{rng('excluir')},\"<>Sí\"),2)", NUM),
        ("$ por banco − Monto $ (BCV) (cuentas en Bs.)",
         f"=ROUND(SUM(F{tg}:{get_column_letter(5 + len(bs))}{tg})-E{tg},2)" if bs else "=0", NUM),
    ]
    for t, fo, fm in ctr:
        _fila(ws, r, [t, None, None, fo], {4: fm} if fm else None)
        ws.cell(r, 4).font = B
        r += 1
    r += 1
    sin_tasa = sum(1 for f in res.filas if not f.excluida and f.moneda == BS and not f.tasa)
    for nota in [
        f"• Clasificación: {sum(1 for f in res.filas if f.estado in (REGLA, DIFERENCIA, CLIENTE, ASIGNADA))} por "
        f"regla, del cliente o del analista, {sum(1 for f in res.filas if f.estado == SUGERIDO)} sugeridas por parecido (naranja) y "
        f"{sum(1 for f in res.filas if f.estado == PENDIENTE and not f.excluida)} por clasificar (amarillo). "
        f"{sum(1 for f in res.filas if f.excluida)} filas excluidas (gris).",
        "• CUENTA 2 (utilidad/pérdida por diferencial cambiario) la marca el cliente; su total por cuenta está en Hallazgos.",
        "• Las cajas en US$ (Efectivo, Zelle…) se suman en su moneda; no entran en «Monto Bs.» ni en «Monto $ (BCV)».",
    ] + ([f"• {sin_tasa} movimiento(s) en Bs. sin tasa BCV: no suman en las columnas de $."] if sin_tasa else []):
        ws.cell(r, 1, nota).font = NOTA
        r += 1
    ws.freeze_panes = "C5"


def _hoja_cuadre(ws, c, res: Resultado, rng, ultima: int, anio: int, mes: int) -> None:
    mon = "Bs." if c.moneda == BS else "US$"
    col_monto = L["bs"] if c.moneda == BS else L["usd"]
    ws["A1"] = f"{c.banco.title()} ({mon}) — Cuadre de lo enviado por el cliente · {MESES[mes]} {anio}"
    ws["A1"].font = TIT
    ws["A2"] = "Llene en amarillo los saldos según el banco. Las filas con Excluir = Sí (en MOV BANCOS) no suman."
    ws["A2"].font = NOTA
    n0, n1 = 12, 11 + len(c.filas)
    filas = [
        ("Saldo inicial (dato del cliente)", c.saldo_inicial),
        ("(+) Créditos", f"=SUMIFS(F{n0}:F{n1},H{n0}:H{n1},\"<>Sí\")"),
        ("(−) Débitos", f"=SUMIFS(E{n0}:E{n1},H{n0}:H{n1},\"<>Sí\")"),
        ("Saldo final calculado", "=IF(B4=\"\",\"Falta saldo inicial\",B4+B5-B6)"),
        ("Saldo final según el banco (dato del cliente)", c.saldo_final_cliente),
        ("Diferencia (debe ser 0)", "=IF(OR(B4=\"\",B8=\"\"),\"Falta saldo\",ROUND(B7-B8,2))"),
    ]
    for i, (t, v) in enumerate(filas, 4):
        ws.cell(i, 1, t).font = B if i in (7, 9) else F
        cel = ws.cell(i, 2, v)
        cel.number_format = NUM
        if i in (4, 8):
            cel.fill = AMARILLO
    ws.cell(4, 4, "Movimientos"), ws.cell(4, 5, f"=COUNT(A{n0}:A{n1})")
    ws.cell(5, 4, "Filas excluidas"), ws.cell(5, 5, f"=COUNTIF(H{n0}:H{n1},\"Sí\")")
    ws.cell(6, 4, "Neto de las excluidas"), ws.cell(6, 5, f"=SUMIFS(F{n0}:F{n1},H{n0}:H{n1},\"Sí\")-"
                                                           f"SUMIFS(E{n0}:E{n1},H{n0}:H{n1},\"Sí\")")
    ws.cell(6, 5).number_format = NUM
    neg = c.dias_en_negativo()
    if neg:
        ws.cell(10, 1, f"OJO: con estos movimientos el saldo cierra en negativo {len(neg)} día(s); el primero es el "
                       f"{neg[0][0]:%d/%m/%Y} ({neg[0][1]}). Suele indicar filas repetidas o un saldo inicial errado."
                ).font = Font(name="Arial", size=10, bold=True, color="C00000")
    _enc(ws, 11, ["Fecha", "Fila MOV BANCOS", "Descripción", "Cuenta", "Débito", "Crédito", "Saldo acumulado",
                  "Excluir", "Observación"], [12, 10, 40, 26, 15, 15, 17, 8, 50])
    # fila de MOV BANCOS de cada movimiento (posición en la hoja, no la fila original del cliente)
    pos = {id(f): i for i, f in enumerate(res.filas, 2)}
    for k, f in enumerate(c.filas):
        r, m = n0 + k, pos[id(f)]
        ant = "$B$4" if k == 0 else f"G{r - 1}"
        _fila(ws, r, [f"='MOV BANCOS'!A{m}", m, f"='MOV BANCOS'!E{m}",
                      f"=IF('MOV BANCOS'!B{m}=\"\",\"{POR_CLASIFICAR}\",'MOV BANCOS'!B{m})",
                      f"=IF(N('MOV BANCOS'!{col_monto}{m})<0,-'MOV BANCOS'!{col_monto}{m},0)",
                      f"=IF(N('MOV BANCOS'!{col_monto}{m})>0,'MOV BANCOS'!{col_monto}{m},0)",
                      f"=IF($B$4=\"\",\"\",IF(H{r}=\"Sí\",{'$B$4' if k == 0 else ant},N({ant})+F{r}-E{r}))",
                      f"='MOV BANCOS'!M{m}", " ".join(f.hallazgos) or None],
              {1: FECHA, 5: NUM, 6: NUM, 7: NUM}, fill=FILL_ESTADO.get(f.estado) if f.excluida else None)
    ws.freeze_panes = f"A{n0}"


def _hoja_cuenta(ws, nombre: str, filas, res: Resultado) -> None:
    clasif = next((c.clasificacion for c in res.catalogo if c.nombre == nombre), "")
    ws["A1"] = nombre
    ws["A1"].font = TIT
    ws["A2"] = f"Clasificación: {clasif or '—'} · {len(filas)} movimientos (sin las filas excluidas)"
    ws["A2"].font = NOTA
    _enc(ws, 4, ["Fecha", "Descripción", "CUENTA 2", "Banco", "Monto Bs.", "BCV DÓLAR", "Monto $.", "Criterio"],
         [11, 40, 30, 12, 15, 10, 13, 50])
    r = 4
    for f in filas:
        r += 1
        _fila(ws, r, [f.fecha, f.descripcion, f.cuenta2, f.banco, f.monto if f.moneda == BS else None, f.tasa,
                      f.usd, f.criterio], {1: FECHA, 5: NUM, 6: TASA, 7: NUM}, fill=FILL_ESTADO.get(f.estado))
    _fila(ws, r + 1, ["TOTAL", f"{len(filas)} movimientos", None, None, f"=SUM(E5:E{r})", None,
                      f"=SUM(G5:G{r})"], {5: NUM, 7: NUM}, fill=TOT, font=B)
    ws.freeze_panes = "A5"


def _hoja_pendientes(ws, res: Resultado) -> None:
    ws["A1"] = "Por clasificar y sugeridos"
    ws["A1"].font = TIT
    ws["A2"] = ("Amarillo: ninguna regla la reconoce. Naranja: parecida a una descripción conocida (confirmar). "
                "La cuenta se decide en la app (o en MOV BANCOS, columna CUENTA).")
    ws["A2"].font = NOTA
    _enc(ws, 4, ["Fila original", "Fecha", "Banco", "Descripción", "Monto", "Moneda", "Cuenta sugerida", "Criterio"],
         [10, 11, 12, 40, 15, 8, 26, 55])
    r = 4
    for f in sorted(res.pendientes, key=lambda f: (f.estado != PENDIENTE, f.banco, f.fila)):
        r += 1
        _fila(ws, r, [f.fila, f.fecha, f.banco, f.descripcion, f.monto, f.moneda, f.cuenta, f.criterio],
              {2: FECHA, 5: NUM}, fill=FILL_ESTADO.get(f.estado))
    if r == 4:
        ws.cell(5, 1, "No queda nada por clasificar.").font = B
    ws.freeze_panes = "A5"


def _hoja_hallazgos(ws, res: Resultado, hojas_banco: dict) -> None:
    ws["A1"] = "Hallazgos de la revisión de lo enviado por el cliente"
    ws["A1"].font = TIT
    _enc(ws, 3, ["#", "Banco", "Filas (del archivo del cliente)", "Tipo", "Detalle", "Acción"],
         [5, 14, 30, 18, 80, 55])
    r = 3
    hall = list(res.lectura.hallazgos)
    for c in res.cuadres:
        if c.saldo_inicial is None:
            hall.append(_h(c.banco, "—", "Falta información", "No se cargó el saldo inicial: no se puede cuadrar.",
                           "Pedir al cliente el saldo al cierre del mes anterior."))
        elif c.saldo_final_cliente is None:
            hall.append(_h(c.banco, "—", "Falta información",
                           f"Falta el saldo final según el banco. Saldo calculado: {c.saldo_calculado}.",
                           "Pedir al cliente el saldo al cierre del mes."))
        elif c.diferencia:
            hall.append(_h(c.banco, "—", "No cuadra", f"Saldo calculado {c.saldo_calculado} vs. banco "
                           f"{c.saldo_final_cliente}: diferencia {c.diferencia}.", "Revisar movimientos faltantes."))
        if c.dias_en_negativo():
            d, v = c.dias_en_negativo()[0]
            hall.append(_h(c.banco, "—", "Revisar", f"El saldo acumulado cierra en negativo desde el {d:%d/%m/%Y} "
                           f"({v}).", "Suele indicar filas repetidas o un saldo inicial errado."))
    for i, h in enumerate(hall, 1):
        r += 1
        _fila(ws, r, [i, h.banco, h.filas, h.tipo, h.detalle, h.accion],
              fill=AMARILLO if h.tipo in ("Posible duplicado", "No cuadra") else None)
        for k in (3, 5, 6):
            ws.cell(r, k).alignment = Alignment(wrap_text=True, vertical="top")
    if not hall:
        ws.cell(4, 1, "Sin hallazgos.").font = B


def _h(*a):
    from .clasificacion_cuentas import Hallazgo
    return Hallazgo(*a)


def _hoja_catalogo(ws, res: Resultado) -> None:
    _enc(ws, 1, ["Cuenta", "Clasificación", "Grupo"], [30, 26, 28])
    for i, c in enumerate(res.catalogo, 2):
        _fila(ws, i, [c.nombre, c.clasificacion, c.grupo])
