"""Banesco — estado de cuenta en PDF (PDFium), página apaisada.

Formato observado (agosto 2026, cuenta 0134-0025-33-0251067692):
  - Bloque izquierdo: «SL- …», titular y dirección. Bloque derecho: CHEQUES (cheque | día | monto, dos por
    fila) y DETALLE DE MOVIMIENTOS: DIA | REF. | CONCEPTO | CARGOS | ABONOS | SALDOS.
  - Primera fila del detalle: «SALDO MES ANTERIOR» con el saldo inicial en la columna SALDOS.
  - El día viene solo (dd); mes y año salen de «Período: mm-aaaa» del resumen.
  - Al pie: RESUMEN DE MOVIMIENTOS (Cheques Pagados, Otros Débitos, Depósitos, Otros Créditos: cantidad y
    monto) y RESUMEN DE SALDOS (Inicial, Final, Promedio).
  - Las páginas pueden traer el detalle en dos bloques (izquierda y derecha, cada uno con su encabezado
    DIA | REF. | CONCEPTO | …): se leen ambos, primero el de la izquierda. En la primera página el bloque
    izquierdo es el titular y la dirección.
  - Cada monto se asigna a la columna (CARGOS / ABONOS / SALDOS) cuyo borde derecho está más cerca: no
    depende de los espacios. Si una fila no se puede asignar con seguridad, queda como error de lectura.
"""
from __future__ import annotations

import datetime as dt
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Sequence

import pdfplumber

from ..modelo import Extracto, Movimiento, ResultadoLectura, TotalesBanco
from ..montos import CERO, monto_ve

BANCO = "BANESCO"
AMT = r"\d{1,3}(?:\.\d{3})*,\d{2}"
ES_MONTO = re.compile(r"^-?" + AMT + r"$")


COLUMNAS = ("DIA", "REF.", "CONCEPTO", "CARGOS", "ABONOS", "SALDOS")


@dataclass
class _Region:
    """Un bloque de detalle (DIA | REF. | CONCEPTO | CARGOS | ABONOS | SALDOS) dentro de la página.
    Hay páginas con un solo bloque (a la derecha) y páginas con dos (izquierda y derecha)."""
    x_ini: float
    x_fin: float
    cols: dict[str, float]                       # borde derecho de CARGOS / ABONOS / SALDOS
    x_dia: float

    def contiene(self, x: float) -> bool:
        return self.x_ini <= x < self.x_fin

    def solapa(self, o: "_Region") -> bool:
        return self.x_ini < o.x_fin and o.x_ini < self.x_fin


def _es_encabezado(toks: list[dict]) -> bool:
    return set(COLUMNAS) <= {w["text"] for w in toks}


def _regiones(toks: list[dict], ancho: float) -> list[_Region]:
    """Un bloque por cada «DIA» del encabezado, hasta el siguiente «DIA» (o el borde de la página)."""
    dias = sorted((w for w in toks if w["text"] == "DIA"), key=lambda w: w["x0"])
    out = []
    for i, d in enumerate(dias):
        x_ini = d["x0"] - 5
        x_fin = dias[i + 1]["x0"] - 5 if i + 1 < len(dias) else ancho + 1
        g = {w["text"]: w for w in toks if x_ini <= w["x0"] < x_fin}
        if set(COLUMNAS) <= set(g):
            out.append(_Region(x_ini, x_fin, {c: g[c]["x1"] for c in ("CARGOS", "ABONOS", "SALDOS")}, d["x0"]))
    return out


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

    @staticmethod
    def _fila(der: list[dict], r: "_Region", anio: int, mes: int, pi: int):
        """Una fila dentro de un bloque de detalle: Movimiento, ("saldo", monto), texto de error o None."""
        montos = [w for w in der if ES_MONTO.match(w["text"])]
        asign: dict[str, str] = {}
        for w in montos:
            col, dist = min(((c, abs(w["x1"] - x)) for c, x in r.cols.items()), key=lambda t: t[1])
            if dist > 25 or col in asign:
                asign = {"?": w["text"]}
                break
            asign[col] = w["text"]
        resto = [w for w in der if w not in montos]
        texto = " ".join(w["text"] for w in resto)
        if "SALDO MES ANTERIOR" in texto:
            if "SALDOS" in asign:
                return ("saldo", monto_ve(asign["SALDOS"]))
            return f"página {pi}: no se pudo leer el saldo del mes anterior"
        dia = resto[0]["text"] if resto and re.fullmatch(r"\d{2}", resto[0]["text"]) \
            and abs(resto[0]["x0"] - r.x_dia) <= 6 else None
        if dia is None:
            if montos:
                return f"página {pi}: fila con montos sin día: «{texto} {' '.join(asign.values())}»"
            return None
        if "?" in asign or ("CARGOS" in asign) == ("ABONOS" in asign):
            return f"página {pi}: no se pudo ubicar el monto en CARGOS o ABONOS: «{texto}»"
        ref = resto[1]["text"] if len(resto) > 1 and re.fullmatch(r"\d+", resto[1]["text"]) else ""
        concepto = " ".join(w["text"] for w in resto[(2 if ref else 1):])
        f = dt.date(anio, mes, int(dia))
        return Movimiento(
            f, concepto,
            debito=monto_ve(asign["CARGOS"]) if "CARGOS" in asign else CERO,
            credito=monto_ve(asign["ABONOS"]) if "ABONOS" in asign else CERO,
            saldo=monto_ve(asign["SALDOS"]) if "SALDOS" in asign else None,
            referencia=ref, fecha_real=f, pagina=pi)

    def _leer_uno(self, ruta: Path) -> Extracto:
        res = self._resumen(_texto(ruta), ruta)
        anio, mes = res["anio"], res["mes"]
        errores: list[str] = []
        movs: list[Movimiento] = []
        saldo_ant: Optional[object] = None
        titular = ""
        cheques: list[Movimiento] = []

        regiones: list[_Region] = []           # bloques de detalle de la página anterior
        with pdfplumber.open(str(ruta)) as pdf:
            for pi, p in enumerate(pdf.pages, 1):
                filas: dict[int, list[dict]] = {}
                for w in p.extract_words(x_tolerance=1.5, y_tolerance=2):
                    k = round(w["top"])
                    clave = next((f for f in filas if abs(f - k) <= 2), k)
                    filas.setdefault(clave, []).append(w)
                orden = sorted(filas)
                hay_encabezado = any(_es_encabezado(filas[t]) for t in orden)
                # Si la página no repite el encabezado, se siguen usando los bloques de la anterior.
                activas: list[_Region] = [] if hay_encabezado else [_Region(r.x_ini, r.x_fin, r.cols, r.x_dia)
                                                                      for r in regiones]
                por_region: dict[float, list[Movimiento]] = {}
                en_cheques = None
                izquierda: list[str] = []
                for top in orden:
                    toks = sorted(filas[top], key=lambda w: w["x0"])
                    textos = [w["text"] for w in toks]
                    if _es_encabezado(toks):
                        nuevas = _regiones(toks, p.width)
                        activas = [r for r in activas if not any(r.solapa(n) for n in nuevas)] + nuevas
                        activas.sort(key=lambda r: r.x_ini)
                        en_cheques = None
                        continue
                    if "CHEQUE" in textos and "MONTO" in textos:
                        en_cheques = toks[0]["x0"] - 20
                        continue
                    if textos[:3] == ["DETALLE", "DE", "MOVIMIENTOS"]:
                        en_cheques = None
                        continue
                    if "RESUMEN" in textos:
                        # Cierra el bloque donde aparece (o todos, si el resumen empieza a su izquierda).
                        x = toks[textos.index("RESUMEN")]["x0"]
                        en_cheques = None
                        activas = [] if not activas or x < activas[0].x_ini else \
                            [r for r in activas if not r.contiene(x)]
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
                    if not activas:
                        continue
                    izq = [w["text"] for w in toks if w["x1"] < activas[0].x_ini - 15]
                    if izq and pi == 1:
                        izquierda.append(" ".join(izq))
                    for r in activas:
                        der = [w for w in toks if r.contiene(w["x0"])]
                        if not der:
                            continue
                        res_fila = self._fila(der, r, anio, mes, pi)
                        if isinstance(res_fila, str):
                            errores.append(res_fila)
                        elif isinstance(res_fila, Movimiento):
                            por_region.setdefault(r.x_ini, []).append(res_fila)
                        elif res_fila is not None:              # saldo del mes anterior
                            saldo_ant = res_fila[1]
                # Orden de lectura: el bloque de la izquierda completo y luego el de la derecha.
                for x in sorted(por_region):
                    movs.extend(por_region[x])
                regiones = activas or regiones
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
