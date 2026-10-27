"""Banesco — estado de cuenta en PDF (PDFium), página apaisada.

Formato observado (agosto 2026, cuenta 0134-0025-33-0251067692):
  - Bloque izquierdo: «SL- …», titular y dirección. Bloque derecho: CHEQUES (cheque | día | monto, dos por
    fila) y DETALLE DE MOVIMIENTOS: DIA | REF. | CONCEPTO | CARGOS | ABONOS | SALDOS.
  - Primera fila del detalle: «SALDO MES ANTERIOR» con el saldo inicial en la columna SALDOS.
  - El día viene solo (dd); mes y año salen de «Período: mm-aaaa» del resumen.
  - Al pie: RESUMEN DE MOVIMIENTOS (Cheques Pagados, Otros Débitos, Depósitos, Otros Créditos: cantidad y
    monto) y RESUMEN DE SALDOS (Inicial, Final, Promedio).
  - Cada monto se asigna a la columna (CARGOS / ABONOS / SALDOS) cuyo borde derecho está más cerca: no
    depende de los espacios. Si una fila no se puede asignar con seguridad, queda como error de lectura.
"""
from __future__ import annotations

import datetime as dt
import re
import subprocess
from pathlib import Path
from typing import Optional, Sequence

import pdfplumber

from ..modelo import Extracto, Movimiento, ResultadoLectura, TotalesBanco
from ..montos import CERO, monto_ve

BANCO = "BANESCO"
AMT = r"\d{1,3}(?:\.\d{3})*,\d{2}"
ES_MONTO = re.compile(r"^-?" + AMT + r"$")


def _texto(ruta: Path) -> str:
    return subprocess.run(["pdftotext", "-layout", str(ruta), "-"], capture_output=True, text=True, check=True).stdout


class LectorBanesco:
    banco = BANCO

    def reconoce(self, ruta: Path) -> bool:
        if Path(ruta).suffix.lower() != ".pdf":
            return False
        t = _texto(ruta)
        return "DETALLE DE MOVIMIENTOS" in t and "RESUMEN DE MOVIMIENTOS" in t and "0134" in t

    def leer(self, rutas: Sequence[Path]) -> ResultadoLectura:
        return ResultadoLectura(extractos=[self._leer_uno(Path(r)) for r in rutas])

    @staticmethod
    def _resumen(t: str, ruta: Path) -> dict:
        def par(etiqueta: str) -> tuple[Optional[int], Optional[str]]:
            m = re.search(etiqueta + r"\s+(\d+)\s+(" + AMT + ")", t)
            return (int(m.group(1)), m.group(2)) if m else (None, None)

        def uno(etiqueta: str) -> Optional[str]:
            m = re.search(etiqueta + r"\s+(-?" + AMT + ")", t)
            return m.group(1) if m else None
        mp = re.search(r"Per[ií]odo:\s*(\d{2})-(\d{4})", t)
        mc = re.search(r"No\. de Cuenta:\s*(\d{20})", t)
        if not mp or not mc:
            raise ValueError(f"{ruta.name}: no se encontró el número de cuenta o el período; ¿es un estado de Banesco?")
        r = {"mes": int(mp.group(1)), "anio": int(mp.group(2)), "cuenta": mc.group(1),
             "cheques": par(r"Cheques Pagados"), "debitos": par(r"Otros D[eé]bitos"),
             "depositos": par(r"Dep[oó]sitos"), "creditos": par(r"Otros Cr[eé]ditos"),
             "inicial": uno(r"\n\s*Inicial"), "final": uno(r"\n\s*Final")}
        faltan = [k for k in ("debitos", "creditos") if r[k][1] is None] + \
                 [k for k in ("inicial", "final") if r[k] is None]
        if faltan:
            raise ValueError(f"{ruta.name}: no se pudo leer el resumen del banco ({', '.join(faltan)}).")
        return r

    def _leer_uno(self, ruta: Path) -> Extracto:
        res = self._resumen(_texto(ruta), ruta)
        anio, mes = res["anio"], res["mes"]
        errores: list[str] = []
        movs: list[Movimiento] = []
        saldo_ant: Optional[object] = None
        titular = ""
        cheques: list[Movimiento] = []

        with pdfplumber.open(str(ruta)) as pdf:
            for pi, p in enumerate(pdf.pages, 1):
                filas: dict[int, list[dict]] = {}
                for w in p.extract_words(x_tolerance=1.5, y_tolerance=2):
                    k = round(w["top"])
                    clave = next((f for f in filas if abs(f - k) <= 2), k)
                    filas.setdefault(clave, []).append(w)
                orden = sorted(filas)
                enc = None                      # encabezado del detalle: posiciones de columnas
                en_cheques = None
                izquierda: list[str] = []
                for top in orden:
                    toks = sorted(filas[top], key=lambda w: w["x0"])
                    textos = [w["text"] for w in toks]
                    if {"DIA", "REF.", "CONCEPTO", "CARGOS", "ABONOS", "SALDOS"} <= set(textos):
                        enc = {w["text"]: w for w in toks}
                        en_cheques = None
                        continue
                    if "CHEQUE" in textos and "MONTO" in textos:
                        en_cheques = toks[0]["x0"] - 20
                        continue
                    if textos[:3] == ["DETALLE", "DE", "MOVIMIENTOS"] or textos[:1] == ["RESUMEN"]:
                        en_cheques = None
                        if textos[:1] == ["RESUMEN"]:
                            enc = None
                        continue
                    if en_cheques is not None:
                        # cheque | día | monto (dos por fila)
                        der = [w for w in toks if w["x0"] >= en_cheques]
                        for a, b, c in zip(der, der[1:], der[2:]):
                            if re.fullmatch(r"\d{4,}", a["text"]) and re.fullmatch(r"\d{1,2}", b["text"]) \
                                    and ES_MONTO.match(c["text"]):
                                cheques.append(Movimiento(dt.date(anio, mes, int(b["text"])), f"CHEQUE {a['text']}",
                                                          debito=monto_ve(c["text"]), referencia=a["text"], pagina=pi))
                        continue
                    if enc is None:
                        continue
                    x_dia = enc["DIA"]["x0"]
                    izq = [w["text"] for w in toks if w["x1"] < x_dia - 20]
                    if izq and pi == 1:
                        izquierda.append(" ".join(izq))
                    der = [w for w in toks if w["x0"] >= x_dia - 5]
                    if not der:
                        continue
                    montos = [w for w in der if ES_MONTO.match(w["text"])]
                    cols = {c: enc[c]["x1"] for c in ("CARGOS", "ABONOS", "SALDOS")}
                    asign: dict[str, str] = {}
                    for w in montos:
                        col, dist = min(((c, abs(w["x1"] - x)) for c, x in cols.items()), key=lambda t: t[1])
                        if dist > 25 or col in asign:
                            asign = {"?": w["text"]}
                            break
                        asign[col] = w["text"]
                    resto = [w for w in der if w not in montos]
                    texto = " ".join(w["text"] for w in resto)
                    if "SALDO MES ANTERIOR" in texto:
                        if "SALDOS" in asign:
                            saldo_ant = monto_ve(asign["SALDOS"])
                        else:
                            errores.append(f"página {pi}: no se pudo leer el saldo del mes anterior")
                        continue
                    dia = resto[0]["text"] if resto and re.fullmatch(r"\d{2}", resto[0]["text"]) \
                        and abs(resto[0]["x0"] - x_dia) <= 6 else None
                    if dia is None:
                        if montos:
                            errores.append(f"página {pi}: fila con montos sin día: «{texto} {' '.join(asign.values())}»")
                        continue
                    if "?" in asign or ("CARGOS" in asign) == ("ABONOS" in asign):
                        errores.append(f"página {pi}: no se pudo ubicar el monto en CARGOS o ABONOS: «{texto}»")
                        continue
                    ref = resto[1]["text"] if len(resto) > 1 and re.fullmatch(r"\d+", resto[1]["text"]) else ""
                    concepto = " ".join(w["text"] for w in resto[(2 if ref else 1):])
                    movs.append(Movimiento(
                        dt.date(anio, mes, int(dia)), concepto,
                        debito=monto_ve(asign["CARGOS"]) if "CARGOS" in asign else CERO,
                        credito=monto_ve(asign["ABONOS"]) if "ABONOS" in asign else CERO,
                        saldo=monto_ve(asign["SALDOS"]) if "SALDOS" in asign else None,
                        referencia=ref, fecha_real=dt.date(anio, mes, int(dia)), pagina=pi))
                if pi == 1 and izquierda:
                    titular = next((l for l in izquierda if not l.startswith("SL-")), "")

        if saldo_ant is None:
            saldo_ant = monto_ve(res["inicial"])
        n_chq, m_chq = res["cheques"]
        if cheques or (n_chq or 0) > 0:
            errores.append(f"El estado trae {n_chq or len(cheques)} cheque(s) pagado(s): el formato de cheques de "
                           "Banesco todavía no se ha verificado con un estado real. Revisar a mano.")
            movs.extend(cheques)
            movs.sort(key=lambda m: m.fecha_contable)
        cero = lambda v: monto_ve(v) if v else CERO
        n_dep, m_dep = res["depositos"]
        n_deb, m_deb = res["debitos"]
        n_cre, m_cre = res["creditos"]
        tb = TotalesBanco(saldo_anterior=monto_ve(res["inicial"]), nuevo_saldo=monto_ve(res["final"]),
                          total_debitos=cero(m_deb) + cero(m_chq), total_creditos=cero(m_cre) + cero(m_dep),
                          nro_debitos=(n_deb or 0) + (n_chq or 0), nro_creditos=(n_cre or 0) + (n_dep or 0))
        hasta = (dt.date(anio + (mes == 12), mes % 12 + 1, 1) - dt.timedelta(days=1))
        return Extracto(BANCO, res["cuenta"], dt.date(anio, mes, 1), hasta, saldo_ant, movs, tb,
                        titular=titular, archivo=ruta.name, errores_lectura=errores)
