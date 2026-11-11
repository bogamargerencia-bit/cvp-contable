"""BBVA Provincial — «ESTADO DE CUENTA CORRIENTE» en PDF (JasperReports).

Formato observado (abril 2026, IMPORTADORA Y COMERCIALIZADORA LA FANTAS, cuenta 0108-0082-01-0100467817):
  - Encabezado: TITULAR, «Nro. de Cuenta: 0108-…», «Situación al: dd-mm-aaaa» (fecha de corte).
  - Detalle: F. OPER. | REF. | CONCEPTO | F. VALOR | CARGOS | ABONOS | SALDO, con el saldo en cada línea.
  - Montos en formato inglés: 1,234,567.89.
  - Primera línea: «SALDO ANTERIOR» (el monto viene bajo ABONOS).
  - Al final: «Saldo a nuestro favor | Saldo a su favor» con el saldo final bajo una de las dos columnas
    (bajo «nuestro favor» = sobregiro, saldo negativo).
  - El banco NO imprime totales de cargos y abonos ni número de operaciones: el control es el saldo de cada
    línea y el saldo final.
  - Cada monto se asigna a la columna (CARGOS / ABONOS / SALDO) cuyo borde derecho está más cerca.
"""
from __future__ import annotations

import datetime as dt
import re
import subprocess
from pathlib import Path
from typing import Optional, Sequence

import pdfplumber

from ..modelo import Extracto, Movimiento, ResultadoLectura, TotalesBanco
from ..montos import CERO, monto_us

BANCO = "PROVINCIAL"
ES_MONTO = re.compile(r"^-?\d{1,3}(?:,\d{3})*\.\d{2}$")
ES_FECHA = re.compile(r"^\d{2}-\d{2}-\d{4}$")


def _texto(ruta: Path) -> str:
    return subprocess.run(["pdftotext", "-layout", str(ruta), "-"], capture_output=True, text=True, check=True).stdout


def _fecha(s: str) -> dt.date:
    d, m, a = s.split("-")
    return dt.date(int(a), int(m), int(d))


def _filas(p) -> list[list[dict]]:
    filas: dict[int, list[dict]] = {}
    for w in p.extract_words(x_tolerance=1.5, y_tolerance=2):
        k = round(w["top"])
        clave = next((f for f in filas if abs(f - k) <= 2), k)
        filas.setdefault(clave, []).append(w)
    return [sorted(filas[t], key=lambda w: w["x0"]) for t in sorted(filas)]


class LectorProvincial:
    banco = BANCO

    def reconoce(self, ruta: Path) -> bool:
        if Path(ruta).suffix.lower() != ".pdf":
            return False
        t = _texto(ruta)
        return "Provincial" in t and "F. OPER." in t and re.search(r"Nro\. de Cuenta:\s*0108", t) is not None

    def leer(self, rutas: Sequence[Path]) -> ResultadoLectura:
        return ResultadoLectura(extractos=[self._leer_uno(Path(r)) for r in rutas])

    def _leer_uno(self, ruta: Path) -> Extracto:
        t = _texto(ruta)
        mcta = re.search(r"Nro\. de Cuenta:\s*(0108[-\d]{16,24})", t)
        mcorte = re.search(r"Situaci[oó]n al:\s*(\d{2}-\d{2}-\d{4})", t)
        if not (mcta and mcorte):
            raise ValueError(f"{ruta.name}: no se encontró el número de cuenta o la fecha de corte; "
                             "¿es un estado de BBVA Provincial?")
        cuenta = mcta.group(1).replace("-", "")
        hasta = _fecha(mcorte.group(1))
        titular = ""

        errores: list[str] = []
        movs: list[Movimiento] = []
        saldo_ant: Optional[object] = None
        saldo_fin: Optional[object] = None
        with pdfplumber.open(str(ruta)) as pdf:
            for pi, p in enumerate(pdf.pages, 1):
                cols: Optional[dict[str, float]] = None
                x_valor = x_concepto = None
                favor: Optional[dict[str, float]] = None
                filas_pag = _filas(p)
                for i, toks in enumerate(filas_pag):
                    textos = [w["text"] for w in toks]
                    if not titular and "TITULAR:" in textos:
                        # El nombre va en la misma fila o en la siguiente, alineado a la izquierda (a la derecha
                        # hay un aviso del banco en la página 1).
                        x = toks[textos.index("TITULAR:")]["x0"]
                        mismo = [w for w in toks if w["x0"] > x and w["x0"] < x + 300]
                        sig = filas_pag[i + 1] if i + 1 < len(filas_pag) else []
                        nombre = mismo or [w for w in sig if abs(w["x0"] - x) < 30 or x < w["x0"] < x + 260]
                        nombre = [w for w in nombre if w["x0"] < x + 300]
                        titular = " ".join(w["text"] for w in nombre).strip()
                    if {"CARGOS", "ABONOS", "SALDO", "CONCEPTO", "REF."} <= set(textos):
                        g = {w["text"]: w for w in toks}
                        cols = {c: g[c]["x1"] for c in ("CARGOS", "ABONOS", "SALDO")}
                        x_concepto = g["CONCEPTO"]["x0"] - 5
                        x_valor = next(w["x0"] for w in toks if w["text"] == "F." and w["x0"] > x_concepto) - 5
                        continue
                    linea = " ".join(textos)
                    if "nuestro favor" in linea and "su favor" in linea:
                        i_n = textos.index("nuestro")
                        i_s = max(i for i, x in enumerate(textos) if x == "su")
                        favor = {"nuestro": toks[i_n + 1]["x1"], "su": toks[i_s + 1]["x1"]}
                        cols = None                       # se acabó el detalle
                        continue
                    if favor is not None:
                        montos = [w for w in toks if ES_MONTO.match(w["text"])]
                        if montos:
                            w = montos[-1]
                            lado = min(favor, key=lambda k: abs(favor[k] - w["x1"]))
                            v = monto_us(w["text"])
                            saldo_fin = -v if lado == "nuestro" else v
                            favor = None
                        continue
                    if cols is None:
                        continue
                    montos = [w for w in toks if ES_MONTO.match(w["text"])]
                    asign: dict[str, str] = {}
                    for w in montos:
                        col, dist = min(((c, abs(w["x1"] - x)) for c, x in cols.items()), key=lambda z: z[1])
                        if dist > 15:
                            continue                      # p. ej. la marca de impresión al margen
                        if col in asign:
                            asign = {"?": w["text"]}
                            break
                        asign[col] = w["text"]
                    if "SALDO ANTERIOR" in linea and not ES_FECHA.match(textos[0]):
                        v = asign.get("ABONOS") or asign.get("SALDO") or asign.get("CARGOS")
                        if v is None:
                            errores.append(f"página {pi}: no se pudo leer el saldo anterior")
                        else:
                            saldo_ant = monto_us(v)
                        continue
                    if not ES_FECHA.match(textos[0]):
                        if asign:
                            errores.append(f"página {pi}: fila con montos sin fecha: «{linea}»")
                        continue
                    if "?" in asign or ("CARGOS" in asign) == ("ABONOS" in asign) or "SALDO" not in asign:
                        errores.append(f"página {pi}: no se pudo ubicar el monto en CARGOS / ABONOS / SALDO: «{linea}»")
                        continue
                    f_oper = _fecha(textos[0])
                    ref = toks[1]["text"] if len(toks) > 1 and re.fullmatch(r"\d+", toks[1]["text"]) \
                        and toks[1]["x1"] < x_concepto + 5 else ""
                    concepto = " ".join(w["text"] for w in toks
                                        if x_concepto <= w["x0"] < x_valor and not ES_MONTO.match(w["text"]))
                    f_valor = next((_fecha(w["text"]) for w in toks
                                    if w["x0"] >= x_valor and ES_FECHA.match(w["text"])), None)
                    movs.append(Movimiento(
                        f_valor or f_oper, concepto,
                        debito=monto_us(asign["CARGOS"]) if "CARGOS" in asign else CERO,
                        credito=monto_us(asign["ABONOS"]) if "ABONOS" in asign else CERO,
                        saldo=monto_us(asign["SALDO"]), referencia=ref, fecha_real=f_oper, pagina=pi))

        if saldo_ant is None:
            raise ValueError(f"{ruta.name}: no se encontró la línea «SALDO ANTERIOR».")
        if saldo_fin is None:
            errores.append("No se encontró el saldo final («Saldo a su favor / a nuestro favor»).")
        lineas = [("Saldo anterior", None, saldo_ant)] + \
            ([("Saldo final" + (" (a nuestro favor)" if saldo_fin < 0 else " (a su favor)"), None, saldo_fin)]
             if saldo_fin is not None else [])
        tb = TotalesBanco(saldo_anterior=saldo_ant, nuevo_saldo=saldo_fin, lineas=lineas)
        return Extracto(BANCO, cuenta, hasta.replace(day=1), hasta, saldo_ant, movs, tb,
                        titular=titular, archivo=ruta.name, errores_lectura=errores)
