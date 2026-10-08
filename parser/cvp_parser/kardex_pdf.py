"""Kardex en PDF (Shiro Alimentos, «KARDEX EFECTIVO / KARDEX ZELLE AGOSTO 2026 SHIRO»).

El cliente lo envía impreso a PDF desde su Excel; no hay acceso al .xlsx. Estructura observada:
  - Dos kardex lado a lado: EFECTIVO (medio DIVISAS) a la izquierda y ZELLE a la derecha. Cada uno con
    dos bloques: ingresos (FECHA | concepto | monto) y pagos (FECHA | concepto | MONTO).
  - Primera fila de ingresos «VIENEN»: saldo inicial. Filas con el nombre del día = ventas del día; con
    otro texto («COMPRA 1500$ DOMENICO») = movimiento de entrada con esa descripción.
  - Los pagos pueden partirse en varias líneas: el concepto sigue abajo y el monto puede quedar en la
    línea siguiente.
  - Fechas «1-ago» (día-mes abreviado); el año sale del título.
  - Al pie, por kardex: «INGRESO MENSUAL», «TOTAL» (VIENEN + ingresos, y total de pagos) y «SALDO :».

Cada bloque se controla contra esos totales impresos: si una línea se leyó mal, el total no cuadra y se
informa en errores (nada se ajusta).
"""
from __future__ import annotations

import datetime as dt
import re
import subprocess
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Optional

from .kardex import DIAS, Kardex, MovKardex
from .montos import CERO, monto_us

MESES = {"ene": 1, "feb": 2, "mar": 3, "abr": 4, "may": 5, "jun": 6, "jul": 7, "ago": 8, "sep": 9, "set": 9,
         "oct": 10, "nov": 11, "dic": 12}
MESES_LARGOS = {"ENERO": 1, "FEBRERO": 2, "MARZO": 3, "ABRIL": 4, "MAYO": 5, "JUNIO": 6, "JULIO": 7, "AGOSTO": 8,
                "SEPTIEMBRE": 9, "SETIEMBRE": 9, "OCTUBRE": 10, "NOVIEMBRE": 11, "DICIEMBRE": 12}
FECHA = re.compile(r"(?<!\S)(\d{1,2})-([a-zA-Z]{3})(?!\S)")
MONTO = re.compile(r"(?<!\S)\$?(-?\d{1,3}(?:,\d{3})*\.\d{2})(?!\S)")
AMT = r"\$?\s*(-?\d{1,3}(?:,\d{3})*\.\d{2})"


@dataclass
class _Linea:
    fecha: Optional[dt.date]
    linea: int = 0
    texto: list[str] = field(default_factory=list)
    monto: Optional[Decimal] = None


def _texto(ruta: Path) -> str:
    return subprocess.run(["pdftotext", "-layout", str(ruta), "-"], capture_output=True, text=True, check=True).stdout


def leer_kardex_pdf(ruta: Path) -> Kardex:
    ruta = Path(ruta)
    t = _texto(ruta)
    lineas = t.splitlines()
    errores: list[str] = []
    m = re.search(r"KARDEX\s+EFECTIVO\s+([A-ZÁÉÍÓÚ]+)\s+(\d{4})", t)
    if not m or "KARDEX ZELLE" not in t:
        raise ValueError(f"{ruta.name}: no es un Kardex de efectivo y Zelle en PDF con el formato conocido")
    anio = int(m.group(2))

    # Bloques por la posición de los cuatro «FECHA» del encabezado.
    i_enc = next(i for i, l in enumerate(lineas) if l.lstrip().startswith("FECHA") and l.count("FECHA") == 4)
    inicios = [mm.start() for mm in re.finditer(r"FECHA", lineas[i_enc])]
    bloques = [("DIVISAS", "ingreso"), ("DIVISAS", "pago"), ("ZELLE", "ingreso"), ("ZELLE", "pago")]
    limites = [(inicios[k] - (2 if k else 0), inicios[k + 1] - 2 if k + 1 < 4 else 10_000) for k in range(4)]

    def fecha(d: str, mes: str) -> Optional[dt.date]:
        try:
            return dt.date(anio, MESES[mes.lower()], int(d))
        except (KeyError, ValueError):
            return None

    registros: list[list[_Linea]] = [[] for _ in range(4)]
    i_pie = next((i for i in range(i_enc + 1, len(lineas)) if "INGRESO MENSUAL" in lineas[i]), len(lineas))
    for n in range(i_enc + 1, i_pie):
        linea = lineas[n]
        for k, (a, b) in enumerate(limites):
            # Trozos de texto (separados por 2+ espacios) que EMPIEZAN dentro del bloque k. Un concepto largo
            # puede invadir la columna de al lado; por eso se asigna el trozo entero, no palabra por palabra.
            palabras = [(w.start(), w.group(0)) for w in re.finditer(r"\S+(?: \S+)*", linea) if a <= w.start() < b]
            if not palabras:
                continue
            seg = " ".join(p for _, p in palabras)
            regs = registros[k]
            mf = FECHA.match(seg)
            if mf:
                f = fecha(mf.group(1), mf.group(2))
                if f is None:
                    errores.append(f"línea {n + 1}: fecha no válida «{mf.group(0)}»")
                    continue
                regs.append(_Linea(f, n + 1))
                seg = seg[mf.end():].strip()
            elif not regs:
                errores.append(f"línea {n + 1}: texto sin fecha antes del primer registro → {seg}")
                continue
            r = regs[-1]
            mm = MONTO.search(seg)
            if mm and mm.end() == len(seg):
                if r.monto is not None:
                    errores.append(f"línea {n + 1}: segundo monto para el mismo registro ({r.fecha:%d/%m}) → {seg}")
                    continue
                r.monto = monto_us(mm.group(1))
                seg = seg[:mm.start()].strip()
            if seg:
                r.texto.append(seg)

    movs: list[MovKardex] = []
    saldo_ini: dict[str, Decimal] = {}
    for k, (medio, clase) in enumerate(bloques):
        for r in registros[k]:
            desc = re.sub(r"\s+", " ", " ".join(r.texto)).strip()
            if r.monto is None:
                errores.append(f"Kardex {medio.title()}, {clase} del {r.fecha:%d/%m} sin monto → {desc}")
                continue
            if clase == "ingreso":
                if desc.upper() == "VIENEN":
                    saldo_ini[medio] = r.monto
                elif r.monto == 0:
                    continue
                elif desc.upper() in DIAS:
                    movs.append(MovKardex(r.linea, r.fecha, medio, r.monto, "Ventas del día", "venta_dia"))
                else:
                    movs.append(MovKardex(r.linea, r.fecha, medio, r.monto, desc.title(), "evento"))
            else:
                movs.append(MovKardex(r.linea, r.fecha, medio, -r.monto, desc, "pago_divisas"))

    # Pie: un valor por kardex (EFECTIVO primero, luego ZELLE).
    pie = "\n".join(lineas[i_pie:])
    ing = [monto_us(x) for x in re.findall(r"INGRESO MENSUAL\s+" + AMT, pie)]
    tot = re.findall(r"TOTAL\s+" + AMT + r"\s+" + AMT, pie)
    sal = [monto_us(x) for x in re.findall(r"SALDO\s*:\s*" + AMT, pie)]
    disponible: dict[str, Decimal] = {}
    for k, medio in enumerate(("DIVISAS", "ZELLE")):
        nombre = "Efectivo" if medio == "DIVISAS" else "Zelle"
        if k >= len(ing) or k >= len(tot) or k >= len(sal):
            errores.append(f"Kardex {nombre}: no se encontraron INGRESO MENSUAL / TOTAL / SALDO al pie")
            continue
        disponible[medio] = sal[k]
        ingresos = sum((x.monto for x in movs if x.medio == medio and x.monto > 0), CERO)
        pagos = -sum((x.monto for x in movs if x.medio == medio and x.monto < 0), CERO)
        t_total, t_pagos = monto_us(tot[k][0]), monto_us(tot[k][1])
        vienen = saldo_ini.get(medio)
        if vienen is None:
            errores.append(f"Kardex {nombre}: falta la fila VIENEN (saldo inicial)")
            continue
        for etiqueta, leido, impreso in (("ingresos del mes (INGRESO MENSUAL)", ingresos, ing[k]),
                                         ("VIENEN + ingresos (TOTAL)", vienen + ingresos, t_total),
                                         ("pagos (TOTAL)", pagos, t_pagos),
                                         ("saldo (TOTAL − pagos)", t_total - t_pagos, sal[k])):
            if leido != impreso:
                errores.append(f"Kardex {nombre}: {etiqueta} leído {leido} vs. impreso {impreso} "
                               f"(diferencia {impreso - leido}); alguna línea no se leyó bien.")
    return Kardex(ruta.name, f"PDF {m.group(1).title()} {anio}", movs, saldo_ini, disponible, errores)
