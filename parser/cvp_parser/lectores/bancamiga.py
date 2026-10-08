"""Bancamiga — «Estado de cuenta corriente amiga» en PDF (PDFium).

Formato observado (septiembre 2026, Shiro Alimentos, cuenta 0172-****-**-*****1387):
  - Encabezado: titular, «Código Cuenta:» (enmascarado por el banco), «Saldo Inicial: x».
  - Detalle: Fecha (dd-mm-aaaa) | Referencia | Descripción | Débito | Crédito | Saldo. Montos 1.234,56;
    el banco imprime 0,00 en la columna que no aplica.
  - La descripción puede continuar en la línea siguiente (sin fecha).
  - Al final: «Resumen» con «Total Débitos n x», «Total Créditos n x» y «Saldo Final del Período x».
  - No trae fecha de corte: el período se toma del mes de los movimientos.
"""
from __future__ import annotations

import datetime as dt
import re
import subprocess
from pathlib import Path
from typing import Sequence

from ..modelo import Extracto, Movimiento, ResultadoLectura, TotalesBanco
from ..montos import CERO, monto_ve

BANCO = "BANCAMIGA"
AMT = r"\d{1,3}(?:\.\d{3})*,\d{2}"
FILA = re.compile(r"^\s*(\d{2}-\d{2}-\d{4})\s+(\S+)\s+(.+?)\s{2,}(" + AMT + r")\s+(" + AMT + r")\s+(" + AMT + r")\s*$")
INICIO = re.compile(r"^\s*\d{2}-\d{2}-\d{4}\s")
NO_ES_DETALLE = ("Bancamiga", "servicios y la", "que tu quieras", "Número de Paginas", "Resumen",
                 "Total D", "Total C", "Saldo Final")


def _texto(ruta: Path) -> str:
    return subprocess.run(["pdftotext", "-layout", str(ruta), "-"],
                          capture_output=True, text=True, check=True).stdout


class LectorBancamiga:
    banco = BANCO

    def reconoce(self, ruta: Path) -> bool:
        if Path(ruta).suffix.lower() != ".pdf":
            return False
        t = _texto(ruta)
        return "bancamiga" in t.lower() and "Detalle de Movimientos" in t

    def leer(self, rutas: Sequence[Path]) -> ResultadoLectura:
        return ResultadoLectura(extractos=[self._leer_uno(Path(r)) for r in rutas])

    def _leer_uno(self, ruta: Path) -> Extracto:
        t = _texto(ruta)
        errores: list[str] = []
        titular = (re.search(r"\n\s*(\S.+?)\s*\nCódigo Cuenta", t) or [None, ""])[1].strip()
        cuenta = (re.search(r"Código Cuenta:\s*(\S+)", t) or [None, ""])[1]
        msi = re.search(r"Saldo Inicial:\s*(-?" + AMT + ")", t)
        if not msi:
            raise ValueError(f"{ruta.name}: no se encontró el Saldo Inicial; ¿es un estado de Bancamiga?")
        saldo_ant = monto_ve(msi.group(1))

        movs: list[Movimiento] = []
        ult: Movimiento | None = None
        continua = False
        for pag, texto_pag in enumerate(t.split("\f"), 1):
            for linea in texto_pag.splitlines():
                f = FILA.match(linea)
                if f:
                    fecha = dt.datetime.strptime(f.group(1), "%d-%m-%Y").date()
                    ult = Movimiento(fecha_contable=fecha, fecha_real=fecha, referencia=f.group(2),
                                     descripcion=re.sub(r"\s+", " ", f.group(3)).strip(),
                                     debito=monto_ve(f.group(4)), credito=monto_ve(f.group(5)),
                                     saldo=monto_ve(f.group(6)), pagina=pag)
                    movs.append(ult)
                    continua = True
                elif INICIO.match(linea):
                    errores.append(f"pág. {pag}: no se pudo leer → {linea.strip()}")
                elif (continua and ult is not None and re.match(r"^\s{20,}\S", linea)
                      and not any(k in linea for k in NO_ES_DETALLE)):
                    ult.descripcion = f"{ult.descripcion} {linea.strip()}"
                    continua = False        # una sola línea de continuación
                elif linea.strip():
                    continua = False
        if not movs:
            raise ValueError(f"{ruta.name}: no se encontraron movimientos en el estado de Bancamiga")

        tot = TotalesBanco(saldo_anterior=saldo_ant)
        m = re.search(r"Total Débitos\s+(\d+)\s+(" + AMT + ")", t)
        if m:
            tot.nro_debitos, tot.total_debitos = int(m.group(1)), monto_ve(m.group(2))
        m = re.search(r"Total Créditos\s+(\d+)\s+(" + AMT + ")", t)
        if m:
            tot.nro_creditos, tot.total_creditos = int(m.group(1)), monto_ve(m.group(2))
        m = re.search(r"Saldo Final del Período\s+(-?" + AMT + ")", t)
        if m:
            tot.nuevo_saldo = monto_ve(m.group(1))
        if tot.total_debitos is None or tot.total_creditos is None or tot.nuevo_saldo is None:
            errores.append("No se encontró el Resumen final (Total Débitos / Total Créditos / Saldo Final)")

        meses = {(x.fecha_contable.year, x.fecha_contable.month) for x in movs}
        if len(meses) > 1:
            errores.append(f"El estado trae movimientos de más de un mes: {sorted(meses)}")
        ultimo = max(x.fecha_contable for x in movs)
        hasta = (ultimo.replace(day=28) + dt.timedelta(days=4)).replace(day=1) - dt.timedelta(days=1)
        return Extracto(banco=BANCO, cuenta=cuenta, desde=hasta.replace(day=1), hasta=hasta,
                        saldo_anterior=saldo_ant if saldo_ant is not None else CERO, movimientos=movs,
                        totales_banco=tot, titular=titular, archivo=ruta.name, errores_lectura=errores)
