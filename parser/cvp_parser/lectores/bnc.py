"""BNC (Banco Nacional de Crédito) — export .xls "rpt_TransactionsCustom_List".

Formato observado (agosto 2026, cuenta corriente ***1800):
  - Encabezado: "MOVIMIENTOS ENTRE FECHAS DEL d/m/aaaa AL d/m/aaaa", número de cuenta enmascarado.
  - Columnas: Fecha, Código Transacción, Tipo Transacción, Tipo Operación, Descripción,
    Referencia, Debe, Haber, Saldo. Orden cronológico. Saldo en cada línea.
  - Fila final "Totales": total Debe, total Haber y saldo final.
  - El banco NO imprime saldo anterior ni número de operaciones: el saldo anterior se
    deduce de la primera línea y el cuadre lo marca como no verificable.
"""
from __future__ import annotations

import datetime as dt
import re
from pathlib import Path
from typing import Sequence

import xlrd

from ..modelo import Extracto, Movimiento, ResultadoLectura, TotalesBanco
from ..montos import CERO, MontoInvalido, monto_excel

BANCO = "BNC"


def _ref(v: object) -> str:
    if isinstance(v, float):
        return str(int(v)) if v == int(v) else repr(v)
    return str(v).strip()


def _col(encabezado: list[str], nombre: str) -> int:
    for i, t in enumerate(encabezado):
        if re.sub(r"\s+", " ", str(t)).strip().lower() == nombre.lower():
            return i
    raise ValueError(f"BNC: no se encontró la columna '{nombre}'")


class LectorBNC:
    banco = BANCO

    def reconoce(self, ruta: Path) -> bool:
        if Path(ruta).suffix.lower() != ".xls":
            return False
        try:
            sh = xlrd.open_workbook(str(ruta)).sheet_by_index(0)
        except Exception:
            return False
        return sh.name.startswith("rpt_Transactions")

    def leer(self, rutas: Sequence[Path]) -> ResultadoLectura:
        return ResultadoLectura(extractos=[self._leer_uno(Path(r)) for r in rutas])

    def _leer_uno(self, ruta: Path) -> Extracto:
        sh = xlrd.open_workbook(str(ruta)).sheet_by_index(0)
        filas = [sh.row_values(r) for r in range(sh.nrows)]
        errores: list[str] = []

        texto = " ".join(str(c) for f in filas[:20] for c in f if c != "")
        m = re.search(r"DEL (\d{1,2}/\d{1,2}/\d{4}) AL (\d{1,2}/\d{1,2}/\d{4})", texto)
        if not m:
            raise ValueError(f"{ruta.name}: no se encontró el período")
        desde, hasta = (dt.datetime.strptime(x, "%d/%m/%Y").date() for x in m.groups())
        cuenta = titular = ""
        for f in filas[:30]:
            vals = [str(c).strip() for c in f if str(c).strip()]
            if vals and re.match(r"CUENTA \w+ \*+\d+$", vals[0]):
                cuenta = "***" + re.sub(r"\D", "", vals[0])[-4:]
                titular = vals[1] if len(vals) > 1 else ""
                break

        i_enc = next(i for i, f in enumerate(filas) if "Fecha" in [str(c).strip() for c in f]
                     and any("Debe" == str(c).strip() for c in f))
        enc = [str(c) for c in filas[i_enc]]
        c_fecha, c_cod, c_tipo = _col(enc, "Fecha"), _col(enc, "Código Transacción"), _col(enc, "Tipo Transacción")
        c_op, c_desc, c_ref = _col(enc, "Tipo Operación"), _col(enc, "Descripción"), _col(enc, "Referencia")
        c_debe, c_haber, c_saldo = _col(enc, "Debe"), _col(enc, "Haber"), _col(enc, "Saldo")

        movs: list[Movimiento] = []
        totales = None
        for n, f in enumerate(filas[i_enc + 1:], i_enc + 2):
            if str(f[c_fecha]).strip() == "Totales":
                totales = TotalesBanco(
                    total_debitos=monto_excel(f[c_debe]),
                    total_creditos=monto_excel(f[c_haber]),
                    nuevo_saldo=monto_excel(f[c_saldo]),
                )
                continue
            if not re.match(r"\d{2}/\d{2}/\d{4}$", str(f[c_fecha]).strip()):
                if any(str(c).strip() for c in f):
                    errores.append(f"fila {n}: no reconocida → {[c for c in f if c != '']}")
                continue
            try:
                fecha = dt.datetime.strptime(f[c_fecha].strip(), "%d/%m/%Y").date()
                movs.append(Movimiento(
                    fecha_contable=fecha, fecha_real=fecha,
                    referencia=_ref(f[c_ref]),
                    descripcion=str(f[c_op]).strip(),
                    detalle=re.sub(r"\s+", " ", str(f[c_desc])).strip(),
                    debito=monto_excel(f[c_debe] or 0), credito=monto_excel(f[c_haber] or 0),
                    saldo=monto_excel(f[c_saldo]),
                    nota=f"{str(f[c_cod]).strip()} {str(f[c_tipo]).strip()}".strip(),
                ))
            except (MontoInvalido, ValueError) as e:
                errores.append(f"fila {n}: {e}")

        saldo_ant = CERO
        if movs:
            p = movs[0]
            saldo_ant = p.saldo + p.debito - p.credito
        return Extracto(
            banco=BANCO, cuenta=cuenta, desde=desde, hasta=hasta, saldo_anterior=saldo_ant,
            movimientos=movs, totales_banco=totales, titular=titular,
            archivo=ruta.name, errores_lectura=errores,
        )
