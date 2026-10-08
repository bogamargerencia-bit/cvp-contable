"""Venezolano de Crédito — estado de cuenta corriente en PDF (Crystal Reports).

Formato observado (agosto y septiembre 2026, Shiro Alimentos, cuenta 0104-0107-15-…):
  - Encabezado repetido en cada página: RIF, titular, «Código Cuenta Cliente» y fecha de corte.
  - Resumen repetido en cada página: Saldo Anterior | Cant. y total de Cheques y otros cargos |
    Total IGTF | Cant. y total de Depósitos y otros abonos | Saldo Actual. Montos 1.234,56.
  - Detalle: Día (solo dd; mes y año salen de la fecha de corte) | Concepto | Referencia (opcional) |
    Cargos | I.G.T.F. | Abonos | Saldo. Cargos/IGTF/Abonos en formato 1.234,56; el SALDO en formato
    1,234.56 seguido de «*» (a favor del cliente) o «CR» (sobregiro: saldo negativo).
  - Las líneas siguientes sin día son el detalle (beneficiario u ordenante de la transferencia).
  - La columna (cargo, IGTF o abono) se decide por la POSICIÓN del monto bajo el encabezado, nunca por
    la variación del saldo. El IGTF se suma al cargo de la misma línea.
"""
from __future__ import annotations

import datetime as dt
import re
import subprocess
from pathlib import Path
from typing import Sequence

from ..modelo import Extracto, Movimiento, ResultadoLectura, TotalesBanco
from ..montos import CERO, monto_us, monto_ve

BANCO = "VENEZOLANO"
AMT_VE = r"\d{1,3}(?:\.\d{3})*,\d{2}"
AMT_US = r"\d{1,3}(?:,\d{3})*\.\d{2}"
INICIO = re.compile(r"^\s{1,8}(\d{2})\s+\S")
FILA = re.compile(r"^\s{1,8}(\d{2})\s+(.+?)\s{2,}(?:(\d{6,})\s+)?((?:" + AMT_VE + r"\s+){1,2})(" + AMT_US + r")\s+(\*|CR)\s*$")
RESUMEN = re.compile(r"Saldo Actual\s*\n\s*\n?\s+(" + AMT_VE + r")\s+(\*|CR)?\s*(\d+)\s+(" + AMT_VE + r")\s+(" + AMT_VE
                     + r")\s+(\d+)\s+(" + AMT_VE + r")\s+(" + AMT_VE + r")\s+(\*|CR)")


def _texto(ruta: Path) -> str:
    return subprocess.run(["pdftotext", "-layout", str(ruta), "-"],
                          capture_output=True, text=True, check=True).stdout


def _signo(marca: str) -> int:
    return -1 if marca == "CR" else 1


class LectorVenezolano:
    banco = BANCO

    def reconoce(self, ruta: Path) -> bool:
        if Path(ruta).suffix.lower() != ".pdf":
            return False
        t = _texto(ruta)
        return "VENEZOLANO.COM" in t.upper() and "Saldo CR" in t

    def leer(self, rutas: Sequence[Path]) -> ResultadoLectura:
        return ResultadoLectura(extractos=[self._leer_uno(Path(r)) for r in rutas])

    def _leer_uno(self, ruta: Path) -> Extracto:
        t = _texto(ruta)
        errores: list[str] = []
        cab = re.search(r"(\d{4}-\d{4}-\d{2}-\d{10})\s+(\d{2}/\d{2}/\d{4})", t)
        if not cab:
            raise ValueError(f"{ruta.name}: no se encontró la cuenta ni la fecha; ¿es un estado del Venezolano de Crédito?")
        cuenta = cab.group(1)
        hasta = dt.datetime.strptime(cab.group(2), "%d/%m/%Y").date()
        titular = (re.search(r"RIF [\w-]+.*\n\s+(.+?)\s*\n", t) or [None, ""])[1].strip()

        res = RESUMEN.search(t)
        if not res:
            raise ValueError(f"{ruta.name}: no se encontró el resumen (Saldo Anterior / cargos / abonos / Saldo Actual)")
        saldo_ant = monto_ve(res.group(1)) * _signo(res.group(2) or "*")
        igtf_total = monto_ve(res.group(5))
        tot = TotalesBanco(
            saldo_anterior=saldo_ant,
            nro_debitos=int(res.group(3)), total_debitos=monto_ve(res.group(4)) + igtf_total,
            nro_creditos=int(res.group(6)), total_creditos=monto_ve(res.group(7)),
            nuevo_saldo=monto_ve(res.group(8)) * _signo(res.group(9)),
        )
        resumenes = {m.groups() for m in RESUMEN.finditer(t)}
        if len(resumenes) > 1:
            errores.append("El resumen del banco no es igual en todas las páginas")

        movs: list[Movimiento] = []
        ult: Movimiento | None = None
        cols: dict[str, int] = {}
        en_detalle = arrastre = False
        for pag, texto_pag in enumerate(t.split("\f"), 1):
            en_detalle = False
            for linea in texto_pag.splitlines():
                enc = re.search(r"Día\s+Concepto.*Cargos.*I\.G\.T\.F\..*Abonos", linea)
                if enc:
                    # fin (borde derecho) de cada encabezado de columna
                    cols = {k: linea.index(k) + len(k) for k in ("Cargos", "I.G.T.F.", "Abonos")}
                    en_detalle = True
                    arrastre = True
                    continue
                if not en_detalle:
                    continue
                if "SIN IMPORTAR EL BANCO" in linea or linea.startswith("Los saldos con"):
                    en_detalle = False
                    continue
                if not linea.strip() or "SALDO INICIAL" in linea:
                    continue
                f = FILA.match(linea)
                if f:
                    arrastre = False
                    cargo = igtf = abono = CERO
                    inicio_montos = f.start(4)
                    for m in re.finditer(AMT_VE, f.group(4)):
                        fin = inicio_montos + m.end()
                        col = min(cols, key=lambda k: abs(cols[k] - fin))
                        v = monto_ve(m.group(0))
                        if col == "Cargos":
                            cargo += v
                        elif col == "I.G.T.F.":
                            igtf += v
                        else:
                            abono += v
                    if (cargo or igtf) and abono:
                        errores.append(f"pág. {pag}: cargo y abono en la misma línea → {linea.strip()}")
                        continue
                    ult = Movimiento(fecha_contable=hasta.replace(day=int(f.group(1))), descripcion=re.sub(r"\s+", " ", f.group(2)).strip(),
                                     referencia=f.group(3) or "", debito=cargo + igtf, credito=abono,
                                     saldo=monto_us(f.group(5)) * _signo(f.group(6)), pagina=pag,
                                     nota=f"incluye IGTF {igtf}" if igtf else "")
                    ult.fecha_real = ult.fecha_contable
                    movs.append(ult)
                elif INICIO.match(linea) and re.search(AMT_US + r"\s+(\*|CR)\s*$", linea):
                    errores.append(f"pág. {pag}: no se pudo leer → {linea.strip()}")
                elif ult is not None and arrastre:
                    # Arriba de cada página, antes del primer movimiento, el banco repite la referencia y el
                    # saldo del último movimiento de la página anterior, partidos con su detalle en una o
                    # varias líneas. Se aceptan solo si coinciden con ese movimiento; el texto va al detalle.
                    resto = linea
                    ms = re.search(r"(" + AMT_US + r")\s+(\*|CR)\s*$", resto)
                    if ms:
                        if monto_us(ms.group(1)) * _signo(ms.group(2)) != ult.saldo:
                            errores.append(f"pág. {pag}: saldo que no corresponde al movimiento anterior → {linea.strip()}")
                            continue
                        resto = resto[:ms.start()]
                    refs = re.findall(r"(?<!\S)\d{6,}(?!\S)", resto)
                    if any(x != ult.referencia for x in refs):
                        errores.append(f"pág. {pag}: referencia que no corresponde al movimiento anterior → {linea.strip()}")
                        continue
                    texto = re.sub(r"(?<!\S)" + re.escape(ult.referencia) + r"(?!\S)", " ", resto) if ult.referencia else resto
                    if texto.strip() and texto.strip() not in ult.detalle:   # el PDF a veces repite un pedazo
                        ult.detalle = (ult.detalle + " " + re.sub(r"\s+", " ", texto).strip()).strip()
                elif ult is not None and re.match(r"^\s{6,}\S", linea) and not re.search(AMT_US + r"\s+(\*|CR)\s*$", linea):
                    if linea.strip() not in ult.detalle:
                        ult.detalle = (ult.detalle + " " + linea.strip()).strip()
                else:
                    errores.append(f"pág. {pag}: línea no reconocida → {linea.strip()}")
        if not movs:
            raise ValueError(f"{ruta.name}: no se encontraron movimientos")
        return Extracto(banco=BANCO, cuenta=cuenta, desde=hasta.replace(day=1), hasta=hasta,
                        saldo_anterior=saldo_ant, movimientos=movs, totales_banco=tot, titular=titular,
                        archivo=ruta.name, errores_lectura=errores)
