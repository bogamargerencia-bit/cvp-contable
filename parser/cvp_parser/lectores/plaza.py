"""Banco Plaza — estado de cuenta en PDF.

Formato observado (agosto 2026, cuenta personal 0138****7448):
  - Encabezado: titular, "Fecha de corte: dd/mm/aaaa", "Cuenta: 0138****nnnn", "SALDO ANTERIOR Bs. x".
  - Detalle: Fecha (dd/mm/aaaa) | Descripción | Débito (en negativo) | Crédito | Saldo. Montos 1.234,56.
  - Al final: "Nro DB: n  Nro CR: n  Total DB: -x  Total CR: x  Saldo: x".
  - Las líneas POS traen la fecha de la venta al final: "POS MAE 88046439 001 0003 1908" = venta del 19/08.
"""
from __future__ import annotations

import datetime as dt
import re
import subprocess
from pathlib import Path
from typing import Sequence

from ..modelo import Extracto, Movimiento, ResultadoLectura, TotalesBanco
from ..montos import CERO, monto_ve

BANCO = "PLAZA"
AMT = r"-?\d{1,3}(?:\.\d{3})*,\d{2}"
FILA = re.compile(r"^\s*(\d{2}/\d{2}/\d{4})\s+(.+?)\s{2,}(" + AMT + r")\s+(" + AMT + r")\s+(" + AMT + r")\s*$")
INICIO = re.compile(r"^\s*\d{2}/\d{2}/\d{4}\s")


def _texto(ruta: Path) -> str:
    # El PDF de Plaza puede traer un flujo comprimido con error ("Bad block header"); pdftotext lo
    # reporta en stderr pero extrae el texto. La completitud se verifica con Nro DB / Nro CR.
    return subprocess.run(["pdftotext", "-layout", str(ruta), "-"], capture_output=True, text=True).stdout


class LectorPlaza:
    banco = BANCO

    def reconoce(self, ruta: Path) -> bool:
        return Path(ruta).suffix.lower() == ".pdf" and "Banco Plaza" in _texto(ruta)

    def leer(self, rutas: Sequence[Path]) -> ResultadoLectura:
        return ResultadoLectura(extractos=[self._leer_uno(Path(r)) for r in rutas])

    def _leer_uno(self, ruta: Path) -> Extracto:
        t = _texto(ruta)
        errores: list[str] = []
        mc = re.search(r"Fecha de corte:\s*(\d{2}/\d{2}/\d{4})", t)
        if not mc:
            raise ValueError(f"{ruta.name}: no se encontró la fecha de corte; ¿es un estado de Banco Plaza?")
        hasta = dt.datetime.strptime(mc.group(1), "%d/%m/%Y").date()
        cuenta = (re.search(r"Cuenta:\s*(\S+)", t) or [None, ""])[1]
        titular = (re.search(r"^\s*(\S.*?)\s{3,}Fecha de corte", t, re.M) or [None, ""])[1].strip()
        msa = re.search(r"SALDO ANTERIOR\s+Bs\.\s*(" + AMT + ")", t)
        saldo_ant = monto_ve(msa.group(1)) if msa else None
        if saldo_ant is None:
            errores.append("No se encontró el SALDO ANTERIOR")

        movs: list[Movimiento] = []
        for linea in t.splitlines():
            if not INICIO.match(linea):
                continue
            f = FILA.match(linea)
            if not f:
                errores.append(f"no se pudo leer → {linea.strip()}")
                continue
            deb, cre = abs(monto_ve(f.group(3))), monto_ve(f.group(4))
            fecha = dt.datetime.strptime(f.group(1), "%d/%m/%Y").date()
            desc = re.sub(r"\s+", " ", f.group(2)).strip()
            ref = (re.search(r"(\d{6,})", desc) or [None, ""])[1]
            movs.append(Movimiento(fecha_contable=fecha, fecha_real=fecha, descripcion=desc, referencia=ref,
                                   debito=deb, credito=cre, saldo=monto_ve(f.group(5))))

        tot = TotalesBanco(saldo_anterior=saldo_ant)
        m = re.search(r"Nro DB:\s*(\d+)\s+Nro CR:\s*(\d+)\s+Total DB:\s*(" + AMT + ")", t)
        if m:
            tot.nro_debitos, tot.nro_creditos = int(m.group(1)), int(m.group(2))
            tot.total_debitos = abs(monto_ve(m.group(3)))
        m = re.search(r"Total CR:\s*(" + AMT + ")", t)
        if m:
            tot.total_creditos = monto_ve(m.group(1))
        m = re.search(r"^\s*Saldo:\s*(" + AMT + ")", t, re.M)
        if m:
            tot.nuevo_saldo = monto_ve(m.group(1))
        if tot.total_debitos is None or tot.total_creditos is None:
            errores.append("No se encontró el resumen final (Nro DB / Total DB / Total CR)")
        fechas = [x.fecha_contable for x in movs]
        return Extracto(banco=BANCO, cuenta=cuenta, desde=hasta.replace(day=1), hasta=hasta,
                        saldo_anterior=saldo_ant if saldo_ant is not None else CERO, movimientos=movs,
                        totales_banco=tot, titular=titular, archivo=ruta.name, errores_lectura=errores)
