"""Banco Activo — «ESTADO DE CUENTA» en PDF (FPDF).

Formato observado (agosto 2026, Pistazie, cuenta 6002185098):
  - Encabezado en cada página: FECHA (de corte, dd/mm/aaaa), No. DE CLIENTE y titular, NUMERO DE CUENTA,
    TIPO DE MONEDA, SALDO INICIAL.
  - Detalle: FECHA REAL TRANSACCION | FECHA CONTABLE | REFERENCIA (puede faltar) | DESCRIPCION | DEBITOS |
    CREDITOS | SALDO. El banco imprime 0,00 en la columna que no aplica y el saldo en cada línea.
  - Primera línea del detalle: «SALDO INICIAL» con el saldo.
  - Al final: «No. DE OPERACIONES | TOTAL DEBITOS | TOTAL CREDITOS | SALDO FINAL».
  - Un PDF con varios meses unidos (varios bloques de totales) todavía no se separa: se avisa.
"""
from __future__ import annotations

import datetime as dt
import re
import subprocess
from pathlib import Path
from typing import Sequence

from ..modelo import Extracto, Movimiento, ResultadoLectura, TotalesBanco
from ..montos import CERO, monto_ve

BANCO = "ACTIVO"
AMT = r"-?\d{1,3}(?:\.\d{3})*,\d{2}"
FECHA = r"\d{2}/\d{2}/\d{4}"
FILA = re.compile(r"^\s*(" + FECHA + r")\s+(" + FECHA + r")\s+(.+?)\s+(" + AMT + r")\s+(" + AMT + r")\s+(" + AMT + r")\s*$")
TOTALES = re.compile(r"No\. DE OPERACIONES.*?\n\s*(\d+)\s+(" + AMT + r")\s+(" + AMT + r")\s+(" + AMT + r")", re.S)


def _texto(ruta: Path) -> str:
    return subprocess.run(["pdftotext", "-layout", str(ruta), "-"], capture_output=True, text=True, check=True).stdout


def _fecha(s: str) -> dt.date:
    d, m, a = s.split("/")
    return dt.date(int(a), int(m), int(d))


class LectorActivo:
    banco = BANCO

    def reconoce(self, ruta: Path) -> bool:
        if Path(ruta).suffix.lower() != ".pdf":
            return False
        t = _texto(ruta)
        return "Centro de Atención Activo" in t or ("FECHA REAL" in t and "No. DE OPERACIONES" in t and "Activo" in t)

    def leer(self, rutas: Sequence[Path]) -> ResultadoLectura:
        return ResultadoLectura(extractos=[self._leer_uno(Path(r)) for r in rutas])

    def _leer_uno(self, ruta: Path) -> Extracto:
        t = _texto(ruta)
        errores: list[str] = []
        mcta = re.search(r"NUMERO DE CUENTA\s+(\d{6,20})", t)
        mcorte = re.search(r"FECHA\s*\n\s*(" + FECHA + r")", t)
        msi = re.search(r"SALDO INICIAL\s*\n\s*(" + AMT + r")", t)
        tot = TOTALES.findall(t)
        if not (mcta and mcorte and msi):
            raise ValueError(f"{ruta.name}: no se encontró el número de cuenta, la fecha de corte o el saldo inicial; "
                             "¿es un estado de Banco Activo?")
        if len(tot) != 1:
            raise ValueError(f"{ruta.name}: se esperaba un solo bloque de totales (un mes) y hay {len(tot)}. "
                             "Si el PDF trae varios meses unidos, súbelos por separado.")
        hasta = _fecha(mcorte.group(1))
        mtit = re.search(r"No\. DE CLIENTE\s*\n\s*\d+\s+(.+?)\s{2,}", t)
        titular = mtit.group(1).strip() if mtit else ""

        movs: list[Movimiento] = []
        for pag, texto_pag in enumerate(t.split("\f"), 1):
            for linea in texto_pag.splitlines():
                m = FILA.match(linea)
                if not m:
                    if re.match(r"^\s*" + FECHA + r"\s", linea):
                        errores.append(f"página {pag}: línea no reconocida «{linea.strip()}»")
                    continue
                f_real, f_cont, medio, deb, cre, saldo = m.groups()
                partes = re.split(r"\s{2,}", medio.strip())
                ref = partes[0] if re.fullmatch(r"\d+", partes[0]) and len(partes) > 1 else ""
                desc = " ".join(partes[1:] if ref else partes)
                desc = re.sub(r"\s+", " ", desc).strip()
                d, c = monto_ve(deb), monto_ve(cre)
                if d and c:
                    errores.append(f"página {pag}: débito y crédito a la vez en «{linea.strip()}»")
                movs.append(Movimiento(_fecha(f_cont), desc, debito=d, credito=c, saldo=monto_ve(saldo),
                                       fecha_real=_fecha(f_real), referencia=ref, pagina=pag))
        n_ops, t_deb, t_cre, s_fin = tot[0]
        tb = TotalesBanco(saldo_anterior=monto_ve(msi.group(1)), nuevo_saldo=monto_ve(s_fin),
                          total_debitos=monto_ve(t_deb), total_creditos=monto_ve(t_cre), nro_operaciones=int(n_ops))
        return Extracto(BANCO, mcta.group(1), hasta.replace(day=1), hasta, monto_ve(msi.group(1)), movs, tb,
                        titular=titular, archivo=ruta.name, errores_lectura=errores)
