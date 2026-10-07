"""Banco Plaza — estado de cuenta en PDF.

Formato observado (agosto 2026, cuenta personal 0138****7448):
  - Encabezado: titular, "Fecha de corte: dd/mm/aaaa", "Cuenta: 0138****nnnn", "SALDO ANTERIOR Bs. x".
  - Detalle: Fecha (dd/mm/aaaa) | Descripción | Débito (en negativo) | Crédito | Saldo. Montos 1.234,56.
  - Al final: "Nro DB: n  Nro CR: n  Total DB: -x  Total CR: x  Saldo: x".
  - Las líneas POS traen la fecha de la venta al final: "POS MAE 88046439 001 0003 1908" = venta del 19/08.

Formato nuevo (septiembre 2026, «ESTADO DE CUENTAS», emitido desde la banca en línea):
  - Encabezado repetido en cada página: TITULAR, CUENTA 0138************7448, «PÁGINA n de m»,
    «SALDO ANTERIOR:» con el monto en la línea siguiente (junto a la fecha/hora de emisión).
  - Detalle: FECHA (dd-mm-aaaa) | REFERENCIA | TRANSACCIÓN | DÉBITOS (negativo) | CRÉDITOS | SALDOS.
  - No trae fecha de corte ni resumen final: el período se toma del mes de los movimientos y el cuadre
    se verifica línea a línea con el saldo corrido (los totales del banco quedan «no verificables»).
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
# Formato nuevo: fecha con guiones y referencia en su propia columna.
FILA2 = re.compile(r"^\s*(\d{2}-\d{2}-\d{4})\s+(\d+)\s+(.+?)\s{2,}(" + AMT + r")\s+(" + AMT + r")\s+(" + AMT + r")\s*$")
INICIO2 = re.compile(r"^\s*\d{2}-\d{2}-\d{4}\s")


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
        if "Fecha de corte" not in t and "ESTADO DE CUENTAS" in t and re.search(INICIO2.pattern, t, re.M):
            return self._leer_nuevo(ruta, t)
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

    def _leer_nuevo(self, ruta: Path, t: str) -> Extracto:
        errores: list[str] = []
        lineas = t.splitlines()
        cuenta = (re.search(r"(\d{4}\*{4,}\d{4})", t) or [None, ""])[1]
        titular = ""
        for i, l in enumerate(lineas):
            if l.strip().startswith("TITULAR:"):
                titular = next((x.strip() for x in lineas[i + 1:i + 6] if x.strip()), "")
                break
        # «SALDO ANTERIOR:» con el monto al final de la línea siguiente; se repite en cada página.
        saldos_ant = {monto_ve(m.group(1)) for m in re.finditer(r"SALDO ANTERIOR:\s*\n[^\n]*?(" + AMT + r")\s*$", t, re.M)}
        saldo_ant = None
        if len(saldos_ant) == 1:
            saldo_ant = saldos_ant.pop()
        elif saldos_ant:
            errores.append(f"El SALDO ANTERIOR no es el mismo en todas las páginas: {sorted(saldos_ant)}")
        else:
            errores.append("No se encontró el SALDO ANTERIOR")
        m = re.search(r"PÁGINA:\s*\d+\s+de\s+(\d+)", t)
        paginas = int(m.group(1)) if m else None
        vistas = len(re.findall(r"PÁGINA:\s*\d+\s+de\s+\d+", t))
        if paginas is not None and vistas != paginas:
            errores.append(f"El PDF dice {paginas} páginas pero se leyeron {vistas}")

        movs: list[Movimiento] = []
        for linea in lineas:
            if not INICIO2.match(linea):
                continue
            f = FILA2.match(linea)
            if not f:
                errores.append(f"no se pudo leer → {linea.strip()}")
                continue
            fecha = dt.datetime.strptime(f.group(1), "%d-%m-%Y").date()
            movs.append(Movimiento(fecha_contable=fecha, fecha_real=fecha,
                                   descripcion=re.sub(r"\s+", " ", f.group(3)).strip(), referencia=f.group(2),
                                   debito=abs(monto_ve(f.group(4))), credito=monto_ve(f.group(5)),
                                   saldo=monto_ve(f.group(6))))
        if not movs:
            raise ValueError(f"{ruta.name}: no se encontraron movimientos en el estado de cuenta de Plaza")
        meses = {(x.fecha_contable.year, x.fecha_contable.month) for x in movs}
        if len(meses) > 1:
            errores.append(f"El estado trae movimientos de más de un mes: {sorted(meses)}")
        ultimo = max(x.fecha_contable for x in movs)
        sig = (ultimo.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
        hasta = sig - dt.timedelta(days=1)
        tot = TotalesBanco(saldo_anterior=saldo_ant)       # sin resumen final: totales no verificables
        return Extracto(banco=BANCO, cuenta=cuenta, desde=hasta.replace(day=1), hasta=hasta,
                        saldo_anterior=saldo_ant if saldo_ant is not None else CERO, movimientos=movs,
                        totales_banco=tot, titular=titular, archivo=ruta.name, errores_lectura=errores)
