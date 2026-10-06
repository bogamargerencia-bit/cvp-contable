"""100% Banco — estado de cuenta corriente en PDF.

Formato observado (agosto 2026, Alimentos Sierra del Sol, C.A.):
  - Montos en formato US: 1,536,892.55
  - Resumen en la página 1: saldo inicial, depósitos, intereses, otros créditos (con
    cantidad), cheques, ITF, otros débitos (con cantidad), saldo final.
  - Detalle: Fecha Ingreso (dd/mm), Fecha Efectiva (dd/mm), Nro. Docum., Descripción,
    Cargos, Abonos, Saldo. Saldo en cada línea.
  - La columna (cargo o abono) se decide por la POSICIÓN del monto bajo el encabezado,
    nunca por la variación del saldo (eso dejaría sin sentido la validación línea a línea).
"""
from __future__ import annotations

import datetime as dt
import re
import subprocess
from pathlib import Path
from typing import Sequence

from ..modelo import Extracto, Movimiento, ResultadoLectura, TotalesBanco
from ..montos import CERO, monto_us

BANCO = "100_BANCO"
AMT = r"\d[\d,]*\.\d{2}"
FILA = re.compile(r"^\s+(\d{2}/\d{2})\s+(\d{2}/\d{2})\s+(\S+)\s+(.+?)\s{2,}(" + AMT + r")\s+(" + AMT + r")\s*$")
INICIO_FILA = re.compile(r"^\s+\d{2}/\d{2}\s+\d{2}/\d{2}\s")


def _texto(ruta: Path) -> str:
    return subprocess.run(["pdftotext", "-layout", str(ruta), "-"],
                          capture_output=True, text=True, check=True).stdout


def _fecha(ddmm: str, hasta: dt.date) -> dt.date:
    d, m = (int(x) for x in ddmm.split("/"))
    anio = hasta.year if m <= hasta.month else hasta.year - 1  # períodos que cruzan año
    return dt.date(anio, m, d)


class LectorBanco100:
    banco = BANCO

    def reconoce(self, ruta: Path) -> bool:
        if Path(ruta).suffix.lower() != ".pdf":
            return False
        t = _texto(ruta)
        return "100%PagoMovil" in t or ("0156" in t and "DETALLE DE MOVIMIENTOS" in t)

    def leer(self, rutas: Sequence[Path]) -> ResultadoLectura:
        return ResultadoLectura(extractos=[self._leer_uno(Path(r)) for r in rutas])

    def _leer_uno(self, ruta: Path) -> Extracto:
        texto = _texto(ruta)
        errores: list[str] = []

        m = re.search(r"PERIODO\s+(\d{2}/\d{2}/\d{4})\s+AL\s+(\d{2}/\d{2}/\d{4})", texto)
        if not m:
            raise ValueError(f"{ruta.name}: no se encontró el PERIODO; ¿es un estado de 100% Banco?")
        desde = dt.datetime.strptime(m.group(1), "%d/%m/%Y").date()
        hasta = dt.datetime.strptime(m.group(2), "%d/%m/%Y").date()
        mc = re.search(r"(\d{4})\s+(\d{4})\s+(\d{2})\s+(\d{3}-\d{6}-\d)", texto)
        cuenta = "-".join(mc.groups()).replace("-", "") if mc else ""
        lineas = texto.splitlines()
        mt = re.search(r"^(\S[^\n]*?,\s*C\.?\s?A\.?)(?=\s{2,}|$)", texto, re.M)
        titular = mt.group(1).strip() if mt else ""

        def resumen(etiqueta: str, con_cantidad: bool):
            patron = etiqueta + (r"\s+(\d+)\s+(" + AMT + ")" if con_cantidad else r".*?(" + AMT + ")")
            r = re.search(patron, texto)
            if not r:
                errores.append(f"Resumen: no se encontró '{etiqueta}'")
                return (0, CERO) if con_cantidad else None
            return (int(r.group(1)), monto_us(r.group(2))) if con_cantidad else monto_us(r.group(1))

        saldo_ini = resumen(r"Saldo al\s+" + re.escape(m.group(1)) + r"\s*\.+", False)
        saldo_fin = resumen(r"Saldo al\s+" + re.escape(m.group(2)) + r"\s*\.+", False)
        dep = resumen(r"Depósitos Efectuados", True)
        intr = resumen(r"Intereses", True)
        ocr = resumen(r"Otros\s+Créditos a su Cuenta", True)
        chq = resumen(r"Cheques Pagados", True)
        itf = resumen(r"Impuesto Transacciones Financieras", True)
        odb = resumen(r"Otros\s+Débitos a su Cuenta", True)

        totales = TotalesBanco(
            saldo_anterior=saldo_ini,
            nuevo_saldo=saldo_fin,
            total_creditos=dep[1] + intr[1] + ocr[1],
            total_debitos=chq[1] + itf[1] + odb[1],
            nro_creditos=dep[0] + intr[0] + ocr[0],
            nro_debitos=chq[0] + itf[0] + odb[0],
        )

        movs: list[Movimiento] = []
        pagina = 1
        corte_cargo_abono = None  # posición (columna de texto) que separa Cargos de Abonos
        for linea in lineas:
            if "\f" in linea:
                pagina += linea.count("\f")
            if "Cargos" in linea and "Abonos" in linea:
                fin_cargos = linea.index("Cargos") + len("Cargos")
                fin_abonos = linea.index("Abonos") + len("Abonos")
                corte_cargo_abono = (fin_cargos + fin_abonos) // 2
                continue
            if not INICIO_FILA.match(linea):
                continue
            f = FILA.match(linea)
            if not f or corte_cargo_abono is None:
                errores.append(f"pág. {pagina}: no se pudo leer → {linea.strip()}")
                continue
            monto = monto_us(f.group(5))
            es_cargo = f.end(5) <= corte_cargo_abono
            movs.append(Movimiento(
                fecha_real=_fecha(f.group(1), hasta),
                fecha_contable=_fecha(f.group(2), hasta),
                referencia="" if f.group(3) == "0" else f.group(3),
                descripcion=re.sub(r"\s+", " ", f.group(4).strip()),
                debito=monto if es_cargo else CERO,
                credito=CERO if es_cargo else monto,
                saldo=monto_us(f.group(6)),
                pagina=pagina,
            ))

        return Extracto(
            banco=BANCO, cuenta=cuenta, desde=desde, hasta=hasta,
            saldo_anterior=saldo_ini if saldo_ini is not None else CERO,
            movimientos=movs, totales_banco=totales, titular=titular,
            archivo=ruta.name, errores_lectura=errores,
        )
