"""Mercantil — «Estado de Cuenta Corriente» en PDF (FOP), dos columnas por página.

Formato observado (septiembre 2026, cuenta 0105-0014-17-1014675855):
  - Página 1: resumen del banco: saldo al inicio, depósitos, «n OTROS CREDITOS A SU CUENTA POR x», cheques,
    «n OTROS DEBITOS A SU CUENTA POR x», impuesto al IGTF y saldo al final; código cuenta cliente y período
    (DESDE/HASTA dd-mm-aa).
  - Desde la página 2, cada página tiene DOS columnas (mitad izquierda y derecha) que se leen en orden:
    izquierda, luego derecha. Primero «OPERACIONES DEBITADAS» (OTROS DEBITOS), luego «OPERACIONES
    ACREDITADAS» (OTROS CREDITOS).
  - Cada operación: fecha dd/mm | número | descripción (primera línea) y un monto alineado a la derecha.
    La descripción sigue en 3-7 líneas sin fecha. En los créditos el banco pega al monto un número de
    control de 6 dígitos («15.379,61103176») y repite números de control sueltos en cada línea: se ignoran.
  - No hay saldo por operación: al final viene «SALDOS AL FINAL DEL DIA» (día | monto). Se usa para
    verificar el saldo al cierre de cada día con movimientos (se asigna al último movimiento del día).
  - Las operaciones de un mismo día no traen hora de registro comparable, así que dentro del día el orden
    es: créditos y luego débitos (solo importa el saldo al cierre del día).
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

BANCO = "MERCANTIL"
AMT = r"\d{1,3}(?:\.\d{3})*,\d{2}"
MONTO_COL = re.compile(r"^(" + AMT + r")(\d{6})?$")     # monto, con o sin el nº de control pegado
FECHA = re.compile(r"^\d{2}/\d{2}$")
CONTROL = re.compile(r"^\d{6}$")


def _texto(ruta: Path, pagina: Optional[int] = None) -> str:
    args = ["pdftotext", "-layout"] + (["-f", str(pagina), "-l", str(pagina)] if pagina else []) + [str(ruta), "-"]
    return subprocess.run(args, capture_output=True, text=True, check=True).stdout


def _fecha_aa(s: str) -> dt.date:
    d, m, a = s.split("-")
    return dt.date(2000 + int(a), int(m), int(d))


class LectorMercantil:
    banco = BANCO

    def reconoce(self, ruta: Path) -> bool:
        if Path(ruta).suffix.lower() != ".pdf":
            return False
        t = _texto(ruta, 1)
        return "Mercantil" in t and "ESTADO DE CUENTA CORRIENTE" in t.upper() and "OTROS DEBITOS A SU CUENTA" in t

    def leer(self, rutas: Sequence[Path]) -> ResultadoLectura:
        return ResultadoLectura(extractos=[self._leer_uno(Path(r)) for r in rutas])

    # ------------------------------------------------------------ página 1
    def _resumen(self, ruta: Path) -> dict:
        t = _texto(ruta, 1)

        def uno(patron: str, grupo: int = 1) -> Optional[str]:
            m = re.search(patron, t, re.S)
            return m.group(grupo) if m else None
        mcta = re.search(r"(\d{4})\s+(\d{4})\s+(\d{2})\s+(\d{10})\s+(\d{2}-\d{2}-\d{2})\s+(\d{2}-\d{2}-\d{2})", t)
        if not mcta:
            raise ValueError(f"{ruta.name}: no se encontró el código de cuenta ni el período; ¿es un estado de Mercantil?")
        r = {
            "cuenta": "-".join(mcta.groups()[:4]),
            "desde": _fecha_aa(mcta.group(5)), "hasta": _fecha_aa(mcta.group(6)),
            "inicio": uno(r"SALDO AL INICIO DEL PERIODO:\s*\d{2}-\d{2}-\d{2}\s+(-?" + AMT + ")"),
            "depositos": uno(r"DEPOSITOS EFECTUADOS POR\s+(" + AMT + ")"),
            "n_cre": uno(r"(\d+)\s+OTROS CREDITOS A SU CUENTA POR"),
            "creditos": uno(r"OTROS CREDITOS A SU CUENTA POR\s+(" + AMT + ")"),
            "cheques": uno(r"CHEQUES DEBITADOS POR\s+(" + AMT + ")"),
            "n_deb": uno(r"(\d+)\s+OTROS DEBITOS A SU CUENTA POR"),
            "debitos": uno(r"OTROS DEBITOS A SU CUENTA POR\s+(" + AMT + ")"),
            "igtf": uno(r"IMPUESTO AL IGTF\s+(" + AMT + ")"),
            "final": uno(r"SALDO AL FINAL DEL PERIODO:\s*\d{2}-\d{2}-\d{2}\s+(-?" + AMT + ")"),
        }
        faltan = [k for k in ("inicio", "creditos", "debitos", "final") if r[k] is None]
        if faltan:
            raise ValueError(f"{ruta.name}: no se pudo leer el resumen de la página 1 ({', '.join(faltan)}).")
        r["titular"] = next((l.strip() for l in t.splitlines()
                             if re.fullmatch(r"[A-ZÁÉÍÓÚÑ0-9 .,&'()-]{6,}", l.strip()) and len(l.split()) >= 2
                             and not re.search(r"ESTADO|RESUMEN|CODIGO|BANCO|URB|AV\.|RUTA|SALDO|OESTE|PARROQUIA|"
                                               r"MUNICIPIO|EDF|CALLE|PISO|LOCAL", l)), "")
        return r

    # ------------------------------------------------------------ detalle
    def _leer_uno(self, ruta: Path) -> Extracto:
        res = self._resumen(ruta)
        hasta: dt.date = res["hasta"]

        def fecha(ddmm: str) -> dt.date:
            d, m = (int(x) for x in ddmm.split("/"))
            return dt.date(hasta.year - (1 if m > hasta.month else 0), m, d)

        errores: list[str] = []
        avisos: list[str] = []
        ops: list[dict] = []                 # {sentido, fecha, numero, desc, detalle[], monto, impuesto, pag}
        saldos_dia: dict[dt.date, object] = {}
        seccion: Optional[str] = None        # "D" débitos / "C" créditos
        fin_detalle = False
        totales_detalle: dict[str, str] = {}

        with pdfplumber.open(str(ruta)) as pdf:
            for pi, p in enumerate(pdf.pages[1:], 2):
                mitad = p.width / 2
                palabras = p.extract_words(x_tolerance=1.2, y_tolerance=2)
                for lado in (0, 1):
                    off = 0 if lado == 0 else mitad - 8
                    filas: dict[int, list[dict]] = {}
                    for w in palabras:
                        if (w["x0"] < mitad) != (lado == 0):
                            continue
                        k = round(w["top"])
                        clave = next((f for f in filas if abs(f - k) <= 2), k)
                        filas.setdefault(clave, []).append({"t": w["text"], "x0": w["x0"] - off, "x1": w["x1"] - off})
                    for top in sorted(filas):
                        toks = sorted(filas[top], key=lambda t: t["x0"])
                        txt = " ".join(t["t"] for t in toks)
                        # Saldos al final del día: pares «dd/mm monto» hasta el final del documento.
                        if "SALDOS AL FINAL DEL DIA" in txt:
                            fin_detalle = True
                            continue
                        if fin_detalle:
                            for a, b in zip(toks, toks[1:]):
                                if FECHA.match(a["t"]) and re.fullmatch(AMT, b["t"]):
                                    saldos_dia[fecha(a["t"])] = monto_ve(b["t"])
                            continue
                        up = txt.upper()
                        mt = re.match(r"TOTAL OTROS (DEBITOS|CREDITOS)\s+(\d+)\s+POR\s+(" + AMT + ")", up)
                        if mt:
                            totales_detalle[mt.group(1)] = mt.group(3)
                            continue
                        if up.startswith(("OPERACIONES DEBITADAS", "OTROS DEBITOS")):
                            seccion = "D"
                            continue
                        if up.startswith(("OPERACIONES ACREDITADAS", "OTROS CREDITOS")):
                            seccion = "C"
                            continue
                        if up.startswith(("DEPOSITOS", "CHEQUES")) and seccion is not None:
                            errores.append(f"página {pi}: sección «{txt}» (cheques o depósitos) aún no soportada")
                            continue
                        if up.startswith("FECHA ") or seccion is None:
                            continue
                        f = [t for t in toks if t["x0"] < 27 and FECHA.match(t["t"])]
                        num = [t for t in toks if 27 <= t["x0"] < 55]
                        montos = [t for t in toks if t["x0"] >= 230 and t["x1"] <= 290 and MONTO_COL.match(t["t"])]
                        impuestos = [t for t in toks if 290 < t["x0"] < 340 and re.fullmatch(AMT, t["t"])]
                        desc = " ".join(t["t"] for t in toks if 55 <= t["x0"] < 230)
                        if f:
                            if len(montos) != 1:
                                errores.append(f"página {pi}: operación del {f[0]['t']} sin un monto claro: «{txt}»")
                                continue
                            ops.append({"sentido": seccion, "fecha": fecha(f[0]["t"]),
                                        "numero": " ".join(t["t"] for t in num), "desc": desc, "detalle": [],
                                        "monto": monto_ve(MONTO_COL.match(montos[0]["t"]).group(1)),
                                        "impuesto": monto_ve(impuestos[0]["t"]) if impuestos else CERO, "pag": pi})
                        elif desc and ops:
                            ops[-1]["detalle"].append(desc)

        movs: list[Movimiento] = []
        for o in ops:
            detalle = " ".join(o["detalle"])
            if o["impuesto"]:
                avisos.append(f"{o['fecha']:%d/%m} {o['desc']}: impuesto (IGTF) {o['impuesto']} cargado aparte")
            m = Movimiento(o["fecha"], o["desc"], debito=o["monto"] if o["sentido"] == "D" else CERO,
                           credito=o["monto"] if o["sentido"] == "C" else CERO, referencia=o["numero"],
                           detalle=detalle, fecha_real=o["fecha"], pagina=o["pag"])
            movs.append(m)
            if o["impuesto"]:
                movs.append(Movimiento(o["fecha"], f"IMPUESTO IGTF {o['desc']}", debito=o["impuesto"],
                                       referencia=o["numero"], fecha_real=o["fecha"], pagina=o["pag"]))
        # Orden cronológico; dentro del día, créditos antes que débitos (orden estable del banco).
        movs.sort(key=lambda m: (m.fecha_contable, 0 if m.credito else 1))
        # Saldo al cierre de cada día en el último movimiento del día.
        ultimos: dict[dt.date, int] = {m.fecha_contable: i for i, m in enumerate(movs)}
        for dia, i in ultimos.items():
            if dia in saldos_dia:
                movs[i].saldo = saldos_dia[dia]
        if not saldos_dia:
            avisos.append("No se encontró la tabla «SALDOS AL FINAL DEL DIA»: solo se verifican los totales.")
        else:
            sin_saldo = sorted(d for d in ultimos if d not in saldos_dia)
            if sin_saldo:
                avisos.append("Días con movimientos sin saldo al final del día en el PDF: "
                              + ", ".join(f"{d:%d/%m}" for d in sin_saldo))

        # Totales impresos al pie de cada sección (deben coincidir con el resumen de la página 1).
        for sec, clave in (("DEBITOS", "debitos"), ("CREDITOS", "creditos")):
            if sec in totales_detalle and totales_detalle[sec] != res[clave]:
                errores.append(f"El total de OTROS {sec} al pie del detalle ({totales_detalle[sec]}) no coincide "
                               f"con el de la página 1 ({res[clave]}).")

        cero = lambda k: monto_ve(res[k]) if res.get(k) else CERO
        tb = TotalesBanco(
            saldo_anterior=monto_ve(res["inicio"]), nuevo_saldo=monto_ve(res["final"]),
            total_debitos=monto_ve(res["debitos"]) + cero("cheques") + cero("igtf"),
            total_creditos=monto_ve(res["creditos"]) + cero("depositos"),
            nro_debitos=int(res["n_deb"]) if res.get("n_deb") else None,
            nro_creditos=int(res["n_cre"]) if res.get("n_cre") else None,
        )
        if cero("igtf") or any(o["impuesto"] for o in ops):
            tb.nro_debitos = None      # el IGTF se carga como línea aparte: el conteo del banco no lo incluye
        return Extracto(BANCO, res["cuenta"], res["desde"], hasta, monto_ve(res["inicio"]), movs, tb,
                        titular=res["titular"], archivo=ruta.name, errores_lectura=errores, avisos_lectura=avisos)
