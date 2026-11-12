"""Clasificación por cuenta contable a partir del Excel de movimientos que envía el cliente (Delicateses).

El cliente no manda estados de cuenta: manda una hoja «MOV BANCOS» con todos los movimientos del mes
(Banesco, Mercantil en Bs.; Efectivo y Zelle en US$), con las columnas
    Fecha | CUENTA | CUENTA 2 | CLASIFICACIÓN | Descripción | Monto Bs. | BCV DÓLAR | Monto $. | BANCO
(la columna BANCO puede venir repetida; se usa la que trae datos).

Cada movimiento se clasifica en una CUENTA y su CLASIFICACIÓN con las reglas del cliente (en la base de
datos, editables por los analistas). Lo que ninguna regla reconoce queda POR CLASIFICAR y resaltado.
No se ajusta nada: los montos con más de 2 decimales, los montos guardados como texto, las filas
incompletas, las fechas fuera del período y los bloques de filas repetidas se informan como hallazgos.

Signo: positivo = ingreso, negativo = egreso (como lo envía el cliente).
"""
from __future__ import annotations

import datetime as dt
import re
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Iterable, Optional

from .montos import CENTIMO, CERO, MontoInvalido, monto_excel

POR_CLASIFICAR = "POR CLASIFICAR"
TIPOS_REGLA = ("exacta", "empieza", "contiene")

# Orden y título de los grupos del resumen, por CLASIFICACIÓN (como el resumen de julio/agosto 2026).
GRUPOS = [
    ("VENTAS", "INGRESOS"),
    ("OTROS INGRESOS", "OTROS INGRESOS"),
    ("INVENTARIO", "COMPRAS DE INVENTARIO"),
    ("GASTO", "GASTOS"),
    ("CAMBIO", "CAMBIO DE DIVISAS"),
    ("CXC SOCIOS", "CXC SOCIOS"),
    ("CUENTAS POR COBRAR", "PRÉSTAMOS / CXC"),
    ("OTRAS CUENTAS POR COBRAR", "OTRAS CUENTAS POR COBRAR"),
    ("IMPUESTOS", "IMPUESTOS"),
    ("TRASLADO ENTRE CUENTAS", "TRASLADOS ENTRE CUENTAS"),
]


def normalizar(texto: object) -> str:
    """Mayúsculas, sin acentos, espacios simples y sin puntuación suelta en los extremos."""
    t = unicodedata.normalize("NFD", str(texto or "").upper())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    t = re.sub(r"\s+", " ", t)
    return t.strip(" .,;:-_/")


# ---------------------------------------------------------------------------------------------- reglas
@dataclass(frozen=True)
class Regla:
    patron: str                         # se compara normalizado
    cuenta: str
    clasificacion: str
    tipo: str = "exacta"                # exacta / empieza / contiene
    banco: Optional[str] = None         # solo para ese banco (normalizado), o None = todos
    sentido: Optional[str] = None       # "ingreso" / "egreso" / None = ambos
    id: Optional[str] = None            # id en la base (para la trazabilidad)

    def __post_init__(self) -> None:
        if self.tipo not in TIPOS_REGLA:
            raise ValueError(f"Tipo de regla desconocido: {self.tipo!r}")
        if self.sentido not in (None, "ingreso", "egreso"):
            raise ValueError(f"Sentido desconocido: {self.sentido!r}")
        if not normalizar(self.patron):
            raise ValueError("Regla sin patrón")

    def aplica(self, desc_norm: str, banco_norm: str, sentido: str) -> bool:
        if self.banco and normalizar(self.banco) != banco_norm:
            return False
        if self.sentido and self.sentido != sentido:
            return False
        p = normalizar(self.patron)
        if self.tipo == "exacta":
            return desc_norm == p
        if self.tipo == "empieza":
            return desc_norm == p or desc_norm.startswith(p + " ")
        return re.search(r"(?<![A-Z0-9])" + re.escape(p) + r"(?![A-Z0-9])", desc_norm) is not None

    def prioridad(self) -> tuple:
        """Menor = se aplica primero: exacta, empieza, contiene; las específicas (banco/sentido) antes."""
        return (TIPOS_REGLA.index(self.tipo), self.banco is None, self.sentido is None)

    def describir(self) -> str:
        extra = "".join([f", {self.banco}" if self.banco else "", f", solo {self.sentido}s" if self.sentido else ""])
        return f"Regla «{self.patron}» ({self.tipo}{extra})"


@dataclass
class Asignacion:
    cuenta: Optional[str]
    clasificacion: Optional[str]
    regla: Optional[Regla] = None
    criterio: str = ""


def clasificar_descripcion(desc: str, banco: str, sentido: str, reglas: Iterable[Regla]) -> Asignacion:
    d, b = normalizar(desc), normalizar(banco)
    if not d:
        return Asignacion(None, None, criterio="Sin descripción: clasificar a mano")
    cands = sorted((r for r in reglas if r.aplica(d, b, sentido)), key=Regla.prioridad)
    if not cands:
        return Asignacion(None, None, criterio="Ninguna regla la reconoce")
    mejor = [r for r in cands if r.prioridad() == cands[0].prioridad()]
    # Si un patrón está contenido en otro («NOMINA» en «PAGO NOMINA»), gana el más específico. Si reconocen
    # palabras distintas («ALQUILER» y «LOCAL») y van a cuentas distintas, decide el analista.
    pats = [normalizar(r.patron) for r in mejor]
    mejor = [r for r, p in zip(mejor, pats) if not any(p != q and p in q for q in pats)]
    destinos = {(r.cuenta, r.clasificacion) for r in mejor}
    if len(destinos) > 1:
        return Asignacion(None, None, criterio="Reglas en conflicto: " + " / ".join(
            f"{r.patron} → {r.cuenta}" for r in mejor))
    r = mejor[0]
    return Asignacion(r.cuenta, r.clasificacion, r, r.describir())


# ------------------------------------------------------------------------------------------- lectura
@dataclass
class MovCuenta:
    fila: int                           # fila en la hoja del cliente
    fecha: Optional[dt.date]
    descripcion: str
    banco: str                          # como viene (BANESCO, MERCANTIL, EFECTIVO, zelle…)
    moneda: str                         # "Bs" / "USD"
    monto: Decimal                      # en la moneda del banco; + ingreso, − egreso
    tasa: Optional[Decimal]             # BCV DÓLAR (solo Bs.)
    cuenta_2: Optional[str] = None
    cuenta_cliente: Optional[str] = None
    clasif_cliente: Optional[str] = None
    cuenta: Optional[str] = None
    clasificacion: Optional[str] = None
    criterio: str = ""
    regla_id: Optional[str] = None
    origen: str = "regla"               # regla / decision / pendiente

    @property
    def sentido(self) -> str:
        return "ingreso" if self.monto > 0 else "egreso"

    @property
    def por_clasificar(self) -> bool:
        return not self.cuenta

    @property
    def usd(self) -> Optional[Decimal]:
        """Equivalente en US$: el monto si el banco es en US$; si es en Bs., monto / tasa BCV a 2 decimales."""
        if self.moneda == "USD":
            return self.monto
        if not self.tasa:
            return None
        return (self.monto / self.tasa).quantize(CENTIMO, ROUND_HALF_UP)


@dataclass
class Hallazgo:
    tipo: str                           # Error / Revisar / Aviso
    banco: str
    filas: str
    detalle: str
    accion: str


@dataclass
class CuadreBanco:
    banco: str
    moneda: str
    movimientos: int
    ingresos: Decimal
    egresos: Decimal                    # en positivo
    saldo_inicial: Optional[Decimal] = None
    saldo_final_banco: Optional[Decimal] = None

    @property
    def neto(self) -> Decimal:
        return self.ingresos - self.egresos

    @property
    def saldo_final_calculado(self) -> Optional[Decimal]:
        return None if self.saldo_inicial is None else self.saldo_inicial + self.neto

    @property
    def diferencia(self) -> Optional[Decimal]:
        if self.saldo_final_calculado is None or self.saldo_final_banco is None:
            return None
        return self.saldo_final_calculado - self.saldo_final_banco


@dataclass
class ResultadoCuenta:
    cliente: str
    periodo: str                        # aaaa-mm
    archivo: str
    movimientos: list[MovCuenta] = field(default_factory=list)
    hallazgos: list[Hallazgo] = field(default_factory=list)
    cuadres: list[CuadreBanco] = field(default_factory=list)

    @property
    def pendientes(self) -> list[MovCuenta]:
        return [m for m in self.movimientos if m.por_clasificar]

    def bancos(self) -> list[tuple[str, str]]:
        """(banco, moneda) en el orden en que aparecen."""
        vistos: dict[str, str] = {}
        for m in self.movimientos:
            vistos.setdefault(m.banco, m.moneda)
        return list(vistos.items())


ENCABEZADOS = {
    "FECHA": "fecha", "CUENTA": "cuenta", "CUENTA 2": "cuenta_2", "CLASIFICACION": "clasif",
    "DESCRIPCION": "desc", "MONTO BS": "bs", "BCV DOLAR": "tasa", "MONTO $": "usd", "BANCO": "banco",
}


def _clave_enc(v: object) -> Optional[str]:
    t = normalizar(v).replace(".", "").strip()
    return ENCABEZADOS.get(t)


def _hoja(wb):
    for ws in wb.worksheets:
        for r in ws.iter_rows(min_row=1, max_row=10, values_only=True):
            claves = {_clave_enc(v) for v in r}
            if {"fecha", "desc", "bs", "banco"} <= claves:
                return ws
    raise ValueError("No se encontró la hoja de movimientos (encabezados Fecha, Descripción, Monto Bs., BANCO).")


def _fecha(v: object) -> Optional[dt.date]:
    if isinstance(v, dt.datetime):
        return v.date()
    if isinstance(v, dt.date):
        return v
    if isinstance(v, str):
        m = re.fullmatch(r"\s*(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})\s*", v)
        if m:
            d, mm, a = map(int, m.groups())
            return dt.date(a + 2000 if a < 100 else a, mm, d)
    return None


def _monto(v: object) -> tuple[Optional[Decimal], Optional[str]]:
    """(monto exacto, problema). Nunca redondea: si trae más de 2 decimales se devuelve tal cual y se avisa."""
    if v is None or (isinstance(v, str) and not v.strip()):
        return None, None
    try:
        d = monto_excel(v)
        return d, ("texto" if isinstance(v, str) else None)
    except MontoInvalido:
        pass
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        d = Decimal(repr(v)).normalize()
        return d, "decimales"
    if isinstance(v, str):
        t = v.strip().replace(" ", "")
        try:
            d = Decimal(t.replace(".", "").replace(",", ".") if "," in t else t)
            return d, "decimales" if d != d.quantize(CENTIMO) else "texto"
        except Exception:
            return None, "ilegible"
    return None, "ilegible"


def _tasa(v: object) -> Optional[Decimal]:
    if isinstance(v, (int, float)) and not isinstance(v, bool) and v:
        return Decimal(repr(v)) if isinstance(v, float) else Decimal(v)
    if isinstance(v, str) and v.strip():
        try:
            return Decimal(v.strip().replace(",", "."))
        except Exception:
            return None
    return None


def leer_movimientos(ruta: Path) -> tuple[list[MovCuenta], list[Hallazgo]]:
    import openpyxl

    wb = openpyxl.load_workbook(ruta, data_only=True, read_only=False)
    ws = _hoja(wb)
    enc_fila, cols = None, {}
    for i, r in enumerate(ws.iter_rows(min_row=1, max_row=10, values_only=True), 1):
        claves = [_clave_enc(v) for v in r]
        if {"fecha", "desc", "bs", "banco"} <= set(claves):
            enc_fila = i
            for j, k in enumerate(claves):
                if k:
                    cols.setdefault(k, []).append(j)
            break
    filas = list(ws.iter_rows(min_row=enc_fila + 1, values_only=True))
    # Si una columna viene repetida (BANCO), se usa la que más datos trae.
    col = {k: max(js, key=lambda j: sum(1 for r in filas if j < len(r) and r[j] not in (None, "")))
           for k, js in cols.items()}
    val = lambda r, k: r[col[k]] if k in col and col[k] < len(r) else None

    movs: list[MovCuenta] = []
    hall: list[Hallazgo] = []
    por_problema: dict[tuple[str, str], list[int]] = defaultdict(list)
    for n, r in enumerate(filas, enc_fila + 1):
        fecha_v, desc_v, banco_v = val(r, "fecha"), val(r, "desc"), val(r, "banco")
        bs, p_bs = _monto(val(r, "bs"))
        usd, p_usd = _monto(val(r, "usd")) if "usd" in col else (None, None)
        tiene_monto = bool(bs) or bool(usd)
        if not any(v not in (None, "", "-") for v in (fecha_v, desc_v, banco_v)) and not tiene_monto:
            continue                                            # fila vacía (o con un «-» suelto)
        banco = str(banco_v or "").strip().upper()
        fecha = _fecha(fecha_v)
        if not banco or fecha is None or not tiene_monto:
            falta = ", ".join(x for x, ok in (("banco", banco), ("fecha", fecha), ("monto", tiene_monto)) if not ok)
            hall.append(Hallazgo("Error", banco or "—", str(n), f"Fila incompleta (falta {falta}): "
                                 f"«{desc_v or ''}». No se incluye en la clasificación.",
                                 "Completar la fila en el archivo del cliente y volver a procesar."))
            continue
        if bs:
            moneda, monto, problema = "Bs", bs, p_bs
        else:
            moneda, monto, problema = "USD", usd, p_usd
        if problema:
            por_problema[(problema, banco)].append(n)
        movs.append(MovCuenta(
            n, fecha, str(desc_v or "").strip(), banco, moneda, monto,
            _tasa(val(r, "tasa")) if moneda == "Bs" else None,
            cuenta_2=(str(val(r, "cuenta_2")).strip() or None) if val(r, "cuenta_2") else None,
            cuenta_cliente=(str(val(r, "cuenta")).strip() or None) if val(r, "cuenta") else None,
            clasif_cliente=(str(val(r, "clasif")).strip() or None) if val(r, "clasif") else None))

    textos = {"texto": ("Revisar", "Monto guardado como texto: se leyó como número.",
                        "Verificar el monto; conviene que el cliente lo envíe como número."),
              "decimales": ("Revisar", "Monto con más de 2 decimales. El banco solo maneja céntimos: no se redondea.",
                            "Ajustar al monto exacto del estado de cuenta."),
              "ilegible": ("Error", "Monto ilegible.", "Corregir el monto en el archivo.")}
    for (prob, banco), ns in sorted(por_problema.items()):
        t, det, acc = textos[prob]
        hall.append(Hallazgo(t, banco, _rangos(ns), f"{det} ({len(ns)} fila{'s' if len(ns) > 1 else ''})", acc))
    return movs, hall


def _rangos(ns: list[int]) -> str:
    ns = sorted(ns)
    out, ini, prev = [], ns[0], ns[0]
    for x in ns[1:] + [None]:
        if x is not None and x == prev + 1:
            prev = x
            continue
        out.append(f"{ini}" if ini == prev else f"{ini}–{prev}")
        if x is not None:
            ini = prev = x
    return ", ".join(out)


# ------------------------------------------------------------------------------------------- controles
def _bloques_repetidos(movs: list[MovCuenta], minimo: int = 5) -> list[Hallazgo]:
    """Tramos de ≥ `minimo` filas seguidas de un banco cuyos montos repiten, en el mismo orden, otro tramo."""
    out: list[Hallazgo] = []
    por_banco: dict[str, list[MovCuenta]] = defaultdict(list)
    for m in movs:
        por_banco[m.banco].append(m)
    for banco, ms in por_banco.items():
        montos = [m.monto for m in ms]
        idx: dict[tuple, list[int]] = defaultdict(list)
        for i in range(len(montos) - minimo + 1):
            idx[tuple(montos[i:i + minimo])].append(i)
        usados: set[int] = set()
        for i in range(len(montos) - minimo + 1):
            if i in usados:
                continue
            for j in idx[tuple(montos[i:i + minimo])]:
                if j <= i or j in usados or j < i + minimo:
                    continue
                k = minimo
                while j + k < len(montos) and i + k < j and montos[i + k] == montos[j + k]:
                    k += 1
                if len(set(montos[i:i + k])) < 3:
                    continue                          # p. ej. comisiones iguales seguidas: no es un bloque
                a, b = ms[i:i + k], ms[j:j + k]
                usados.update(range(i, i + k))
                usados.update(range(j, j + k))
                out.append(Hallazgo(
                    "Revisar", banco, f"{a[0].fila}–{a[-1].fila} y {b[0].fila}–{b[-1].fila}",
                    f"Posible bloque duplicado: {k} filas seguidas con los mismos montos y en el mismo orden "
                    f"({a[0].fecha:%d/%m} – {a[-1].fecha:%d/%m} y {b[0].fecha:%d/%m} – {b[-1].fecha:%d/%m}).",
                    "Confirmar con el estado de cuenta; si está repetido, pedir al cliente que lo corrija."))
                break
    return out


def _controles(res: ResultadoCuenta, anio: int, mes: int) -> None:
    fuera = defaultdict(list)
    for m in res.movimientos:
        if (m.fecha.year, m.fecha.month) != (anio, mes):
            fuera[m.banco].append(m.fila)
    for banco, ns in fuera.items():
        res.hallazgos.append(Hallazgo("Revisar", banco, _rangos(ns), f"{len(ns)} fila(s) con fecha fuera del período "
                                      f"{mes:02d}/{anio}.", "Confirmar a qué mes corresponden."))
    sin_tasa = [m.fila for m in res.movimientos if m.moneda == "Bs" and not m.tasa]
    if sin_tasa:
        res.hallazgos.append(Hallazgo("Revisar", "Bs.", _rangos(sin_tasa), f"{len(sin_tasa)} fila(s) en Bs. sin tasa "
                                      "BCV DÓLAR: no tienen equivalente en US$.", "Completar la tasa del día."))
    c2 = [m.fila for m in res.movimientos if m.cuenta_2]
    if c2:
        res.hallazgos.append(Hallazgo(
            "Aviso", "—", _rangos(c2), f"{len(c2)} fila(s) traen CUENTA 2 (diferencial cambiario). Desde septiembre "
            "2026 el cliente compra y vende a tasa BCV y no debería haber diferencial: se muestra, pero no se calcula.",
            "Confirmar con el cliente."))
    mezcla = defaultdict(set)
    for m in res.movimientos:
        mezcla[m.banco].add(m.moneda)
    for banco, ms in mezcla.items():
        if len(ms) > 1:
            res.hallazgos.append(Hallazgo("Error", banco, "—", f"El banco {banco} trae filas en Bs. y en US$.",
                                          "Revisar la columna de monto de esas filas."))
    res.hallazgos.extend(_bloques_repetidos(res.movimientos))


def _cuadres(res: ResultadoCuenta, saldos: dict[str, tuple[Optional[Decimal], Optional[Decimal]]]) -> None:
    sal = {normalizar(k): v for k, v in (saldos or {}).items()}
    for banco, moneda in res.bancos():
        ms = [m for m in res.movimientos if m.banco == banco]
        ini, fin = sal.get(normalizar(banco), (None, None))
        c = CuadreBanco(banco, moneda, len(ms), sum((m.monto for m in ms if m.monto > 0), CERO),
                        -sum((m.monto for m in ms if m.monto < 0), CERO), ini, fin)
        res.cuadres.append(c)
        if ini is not None:
            saldo, primera, minimo = ini, None, (ini, None)
            for m in ms:
                saldo += m.monto
                if saldo < 0 and primera is None:
                    primera = m
                if saldo < minimo[0]:
                    minimo = (saldo, m)
            if primera is not None:
                sim = "Bs." if moneda == "Bs" else "US$"
                res.hallazgos.append(Hallazgo(
                    "Error", banco, f"desde {primera.fila}",
                    f"Con el saldo inicial de {sim} {_ve(ini)}, el saldo acumulado queda negativo desde la fila "
                    f"{primera.fila} ({primera.fecha:%d/%m}) y llega a {sim} {_ve(minimo[0])} (fila {minimo[1].fila}). "
                    f"Saldo final calculado: {sim} {_ve(c.saldo_final_calculado)}. Una cuenta no puede quedar en "
                    "negativo: faltan ingresos, sobran egresos o el saldo inicial no es correcto.",
                    "Comparar con el estado de cuenta del banco y pedir al cliente lo que falte."))
        if c.diferencia:
            sim = "Bs." if moneda == "Bs" else "US$"
            res.hallazgos.append(Hallazgo("Error", banco, "—", f"El saldo final calculado ({sim} "
                                          f"{_ve(c.saldo_final_calculado)}) no coincide con el del banco ({sim} "
                                          f"{_ve(c.saldo_final_banco)}): diferencia {sim} {_ve(c.diferencia)}.",
                                          "Buscar los movimientos que faltan o sobran en el archivo del cliente."))


def _ve(d: Decimal) -> str:
    """Formato venezolano sin redondear (puede traer más de 2 decimales si el cliente los envió)."""
    neg = d < 0
    e, _, f = f"{abs(d):f}".partition(".")
    f = (f + "00")[:max(2, len(f.rstrip("0")))]
    e = f"{int(e):,}".replace(",", ".")
    return ("-" if neg else "") + e + "," + f


# --------------------------------------------------------------------------------------------- proceso
def clasificar_archivo(cliente: str, periodo: str, ruta: Path, reglas: Iterable[Regla],
                       decisiones: Optional[dict[str, tuple[str, str]]] = None,
                       saldos: Optional[dict[str, tuple[Optional[Decimal], Optional[Decimal]]]] = None
                       ) -> ResultadoCuenta:
    """decisiones: clave_movimiento(m) -> (cuenta, clasificación) que el analista asignó a mano este mes.
    saldos: banco -> (saldo inicial, saldo final según banco), si se conocen."""
    anio, mes = map(int, periodo.split("-"))
    movs, hall = leer_movimientos(Path(ruta))
    reglas = list(reglas)
    decisiones = decisiones or {}
    for m in movs:
        dec = decisiones.get(clave_movimiento(m))
        if dec:
            m.cuenta, m.clasificacion = dec
            m.origen, m.criterio = "decision", "Asignado por el analista"
            continue
        a = clasificar_descripcion(m.descripcion, m.banco, m.sentido, reglas)
        m.cuenta, m.clasificacion, m.criterio = a.cuenta, a.clasificacion, a.criterio
        m.regla_id = a.regla.id if a.regla else None
        m.origen = "regla" if a.cuenta else "pendiente"
    res = ResultadoCuenta(cliente, periodo, Path(ruta).name, movs, hall)
    _controles(res, anio, mes)
    _cuadres(res, saldos or {})
    return res


def clave_movimiento(m: MovCuenta) -> str:
    """Identifica un movimiento del mes aunque el archivo se vuelva a subir: banco, fecha, monto, descripción
    y ocurrencia (si hay varios iguales, se numeran en orden). La ocurrencia la añade `claves()`."""
    return f"{normalizar(m.banco)}|{m.fecha:%Y-%m-%d}|{m.monto}|{normalizar(m.descripcion)}"


def claves(movs: list[MovCuenta]) -> dict[int, str]:
    """fila -> clave única del movimiento dentro del mes (clave_movimiento + #ocurrencia)."""
    vistos: Counter = Counter()
    out = {}
    for m in movs:
        k = clave_movimiento(m)
        vistos[k] += 1
        out[m.fila] = f"{k}#{vistos[k]}"
    return out


# --------------------------------------------------------------------------------------------- resumen
@dataclass
class LineaResumen:
    clasificacion: str
    cuenta: str
    movimientos: int = 0
    por_banco: dict[str, Decimal] = field(default_factory=dict)
    usd: Decimal = CERO                  # equivalente total en US$ (Bs. a tasa BCV + US$)
    usd_incompleto: bool = False


def resumen(res: ResultadoCuenta) -> list[tuple[str, list[LineaResumen]]]:
    """[(título del grupo, líneas)] en el orden de GRUPOS; clasificaciones desconocidas al final y POR CLASIFICAR
    de último."""
    lineas: dict[tuple[str, str], LineaResumen] = {}
    for m in res.movimientos:
        clasif = m.clasificacion or POR_CLASIFICAR
        cuenta = m.cuenta or POR_CLASIFICAR
        l = lineas.setdefault((clasif, cuenta), LineaResumen(clasif, cuenta))
        l.movimientos += 1
        l.por_banco[m.banco] = l.por_banco.get(m.banco, CERO) + m.monto
        if m.usd is None:
            l.usd_incompleto = True
        else:
            l.usd += m.usd
    titulos = dict(GRUPOS)
    orden = [c for c, _ in GRUPOS]
    clasifs = sorted({c for c, _ in lineas}, key=lambda c: (c == POR_CLASIFICAR, orden.index(c) if c in orden
                                                            else len(orden), c))
    out = []
    for c in clasifs:
        ls = sorted((l for (cl, _), l in lineas.items() if cl == c), key=lambda l: -abs(l.usd))
        out.append((titulos.get(c, c) if c != POR_CLASIFICAR else "POR CLASIFICAR (resaltados)", ls))
    return out


def reglas_desde_clasificado(movs: list[MovCuenta]) -> tuple[list[Regla], list[str]]:
    """Reglas «exactas» a partir de un mes ya clasificado (cuenta del archivo): una por descripción con una sola
    cuenta; si la cuenta depende del sentido (ingreso/egreso), una por sentido. Devuelve también las descripciones
    que no se pueden convertir en regla (van a distintas cuentas en el mismo sentido)."""
    por: dict[str, Counter] = defaultdict(Counter)
    original: dict[str, str] = {}
    for m in movs:
        d = normalizar(m.descripcion)
        if not d or not m.cuenta_cliente:
            continue
        por[d][(m.cuenta_cliente, m.clasif_cliente or "", m.sentido)] += 1
        original.setdefault(d, m.descripcion.strip())
    reglas, ambiguas = [], []
    for d, c in sorted(por.items()):
        destinos = {(cu, cl) for cu, cl, _ in c}
        if len(destinos) == 1:
            cu, cl = destinos.pop()
            reglas.append(Regla(original[d], cu, cl))
            continue
        ok = True
        nuevas = []
        for sentido in ("ingreso", "egreso"):
            ds = {(cu, cl) for cu, cl, s in c if s == sentido}
            if len(ds) > 1:
                ok = False
            elif ds:
                cu, cl = ds.pop()
                nuevas.append(Regla(original[d], cu, cl, sentido=sentido))
        if ok:
            reglas.extend(nuevas)
        else:
            ambiguas.append(original[d])
    return reglas, ambiguas


# ----------------------------------------------------------------------------------------------- Excel
def _nombre_hoja(nombre: str, usados: set[str]) -> str:
    base = re.sub(r"[\[\]:*?/\\']", "-", nombre).strip()[:31] or "Hoja"
    n, k = base, 2
    while n.upper() in {u.upper() for u in usados}:
        suf = f" ({k})"
        n, k = base[:31 - len(suf)] + suf, k + 1
    usados.add(n)
    return n


def excel_clasificacion(res: ResultadoCuenta, salida: Path) -> Path:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter as L

    from .exportar import B, F, FECHA, NOTA, NUM, ROJA, SUB, TIT, TOT, _enc, _fila

    AMARILLO_INPUT = PatternFill("solid", start_color="FFFF00")

    PEND = PatternFill("solid", start_color="FFF2CC")
    GRUPO = PatternFill("solid", start_color="E2EFDA")
    wb = Workbook()
    ws_res = wb.active
    ws_res.title = "Resumen"
    ws_hal = wb.create_sheet("Hallazgos")
    ws = wb.create_sheet("MOV BANCOS")
    usados = {"Resumen", "Hallazgos", "MOV BANCOS"}
    bancos = res.bancos()
    mon = lambda m: "Bs." if m == "Bs" else "US$"

    # MOV BANCOS (mismas columnas que envía el cliente + criterio y fila original)
    _enc(ws, 1, ["Fecha", "CUENTA", "CUENTA 2", "CLASIFICACIÓN", "Descripción", "Monto Bs.", "BCV DÓLAR", "Monto $.",
                 "BANCO", "Moneda", "Criterio de clasificación", "Fila del cliente"],
         [11, 26, 18, 22, 40, 15, 11, 13, 12, 8, 46, 9])
    for i, m in enumerate(res.movimientos, 2):
        usd = f"=IF(N(G{i})=0,\"\",ROUND(F{i}/G{i},2))" if m.moneda == "Bs" else m.monto
        _fila(ws, i, [m.fecha, m.cuenta or POR_CLASIFICAR, m.cuenta_2, m.clasificacion or POR_CLASIFICAR, m.descripcion,
                      m.monto if m.moneda == "Bs" else 0, m.tasa, usd, m.banco, mon(m.moneda), m.criterio, m.fila],
              {1: FECHA, 6: NUM, 7: "#,##0.00##", 8: NUM}, fill=PEND if m.por_clasificar else None)
    ult = len(res.movimientos) + 1
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = f"A1:L{max(ult, 1)}"
    rng = lambda c: f"'MOV BANCOS'!${c}$2:${c}${max(ult, 2)}"

    # Hojas por banco: cuadre por saldo + movimientos con saldo acumulado
    hoja_banco = {}
    for c in res.cuadres:
        wb_ = wb.create_sheet(_nombre_hoja(f"{c.banco.upper()} ({mon(c.moneda)})", usados))
        hoja_banco[c.banco] = wb_.title
        col = "F" if c.moneda == "Bs" else "H"
        wb_["A1"] = f"{c.banco.upper()} ({mon(c.moneda)}) — cuadre de lo enviado por el cliente · {res.periodo}"
        wb_["A1"].font = TIT
        filas = [("Saldo inicial (dato del cliente o del mes anterior)", c.saldo_inicial, True),
                 ("(+) Ingresos", f"=SUMIFS({rng(col)},{rng('I')},\"{c.banco}\",{rng(col)},\">0\")", False),
                 ("(−) Egresos", f"=-SUMIFS({rng(col)},{rng('I')},\"{c.banco}\",{rng(col)},\"<0\")", False),
                 ("Saldo final calculado", "=IF(B3=\"\",\"Falta el saldo inicial\",ROUND(B3+B4-B5,2))", False),
                 ("Saldo final según el banco", c.saldo_final_banco, True),
                 ("Diferencia (debe ser 0)", "=IF(OR(B3=\"\",B7=\"\"),\"Faltan saldos\",ROUND(B6-B7,2))", False)]
        for k, (et, v, entrada) in enumerate(filas, 3):
            wb_.cell(k, 1, et).font = B if k in (6, 8) else F
            x = wb_.cell(k, 2, v)
            x.number_format = NUM
            if entrada:
                x.fill = AMARILLO_INPUT
        wb_["B8"].font = ROJA
        wb_["D3"] = "Movimientos"
        wb_["E3"] = c.movimientos
        wb_["D4"] = "Neto del mes"
        wb_["E4"] = c.neto
        wb_["E4"].number_format = NUM
        wb_["A9"] = "Celdas amarillas: completar con el estado de cuenta. Los totales se recalculan con MOV BANCOS."
        wb_["A9"].font = NOTA
        _enc(wb_, 11, ["Fila del cliente", "Fecha", "Descripción", "Cuenta", "Egreso", "Ingreso", "Saldo acumulado"],
             [52, 11, 40, 26, 15, 15, 16])
        r = 12
        for m in res.movimientos:
            if m.banco != c.banco:
                continue
            ant = "$B$3" if r == 12 else f"G{r - 1}"
            _fila(wb_, r, [m.fila, m.fecha, m.descripcion, m.cuenta or POR_CLASIFICAR,
                           -m.monto if m.monto < 0 else None, m.monto if m.monto > 0 else None,
                           f"=IF({ant}=\"\",\"\",{ant}+N(F{r})-N(E{r}))"],
                  {2: FECHA, 5: NUM, 6: NUM, 7: NUM}, fill=PEND if m.por_clasificar else None)
            r += 1
        wb_.freeze_panes = "A12"

    # Hojas por cuenta
    grupos = resumen(res)
    hoja_cuenta: dict[tuple[str, str], str] = {}
    for _, lineas in grupos:
        for l in lineas:
            wc = wb.create_sheet(_nombre_hoja(l.cuenta, usados))
            hoja_cuenta[(l.clasificacion, l.cuenta)] = wc.title
            wc["A1"] = l.cuenta
            wc["A1"].font = TIT
            wc["A2"] = f"Clasificación: {l.clasificacion} · {l.movimientos} movimiento(s) · {res.periodo}"
            wc["A2"].font = NOTA
            _enc(wc, 4, ["Fila del cliente", "Fecha", "Descripción", "Banco", "Monto", "Moneda", "BCV DÓLAR",
                         "Equivalente US$"], [9, 11, 40, 12, 15, 8, 11, 14])
            r = 5
            for m in res.movimientos:
                if (m.clasificacion or POR_CLASIFICAR, m.cuenta or POR_CLASIFICAR) != (l.clasificacion, l.cuenta):
                    continue
                _fila(wc, r, [m.fila, m.fecha, m.descripcion, m.banco, m.monto, mon(m.moneda), m.tasa, m.usd],
                      {2: FECHA, 5: NUM, 7: "#,##0.00##", 8: NUM})
                r += 1
            for k, (banco, moneda) in enumerate(bancos):
                fr = r + 1 + k
                wc.cell(fr, 3, f"Total {banco} ({mon(moneda)})").font = B
                x = wc.cell(fr, 5, f"=SUMIFS(E5:E{r - 1},D5:D{r - 1},\"{banco}\")" if r > 5 else 0)
                x.number_format, x.font = NUM, B
            fr = r + 1 + len(bancos)
            wc.cell(fr, 3, "Total equivalente US$").font = B
            x = wc.cell(fr, 8, f"=SUM(H5:H{r - 1})" if r > 5 else 0)
            x.number_format, x.font = NUM, B
            wc.freeze_panes = "A5"

    # Resumen por cuenta (fórmulas sobre MOV BANCOS)
    ws_res["A1"] = f"{res.cliente} — RESUMEN POR CUENTA · {res.periodo}"
    ws_res["A1"].font = TIT
    ws_res["A2"] = ("Fuente: MOV BANCOS. Negativo = egreso, positivo = ingreso. Cada banco en su moneda; el total en "
                    "US$ convierte los Bs. a la tasa BCV de cada día. Clic en la cuenta para ver su detalle.")
    ws_res["A2"].font = NOTA
    tit = ["Cuenta", "Clasificación", "N° Movs"] + [f"{b} ({mon(mo)})" for b, mo in bancos] + ["Total US$"]
    _enc(ws_res, 4, tit, [30, 24, 9] + [16] * len(bancos) + [15])
    nb = len(bancos)
    c_tot = 4 + nb
    r = 5
    subtotales = []
    for titulo, lineas in grupos:
        ws_res.cell(r, 1, titulo).font = SUB
        for k in range(1, c_tot + 1):
            ws_res.cell(r, k).fill = GRUPO
        r += 1
        ini = r
        for l in lineas:
            crit = f"{rng('B')},$A{r},{rng('D')},$B{r}"
            vals = [l.cuenta, l.clasificacion, f"=COUNTIFS({crit})"]
            for b, mo in bancos:
                vals.append(f"=SUMIFS({rng('F' if mo == 'Bs' else 'H')},{crit},{rng('I')},\"{b}\")")
            vals.append(f"=SUMIFS({rng('H')},{crit})")
            _fila(ws_res, r, vals, {k: NUM for k in range(4, c_tot + 1)},
                  fill=PEND if l.cuenta == POR_CLASIFICAR else None)
            h = hoja_cuenta[(l.clasificacion, l.cuenta)]
            ws_res.cell(r, 1).hyperlink = f"#'{h}'!A1"
            ws_res.cell(r, 1).font = Font(name="Arial", size=10, color="0563C1", underline="single")
            r += 1
        vals = [f"Total {titulo}", None, f"=SUM(C{ini}:C{r - 1})"] + \
               [f"=SUM({L(k)}{ini}:{L(k)}{r - 1})" for k in range(4, c_tot + 1)]
        _fila(ws_res, r, vals, {k: NUM for k in range(4, c_tot + 1)}, fill=TOT, font=B)
        subtotales.append(r)
        r += 2
    vals = ["TOTAL GENERAL (flujo neto del mes)", None, "=" + "+".join(f"C{s}" for s in subtotales)] + \
           ["=" + "+".join(f"{L(k)}{s}" for s in subtotales) for k in range(4, c_tot + 1)]
    _fila(ws_res, r, vals, {k: NUM for k in range(4, c_tot + 1)}, fill=TOT, font=B)
    tg = r
    r += 2
    ws_res.cell(r, 1, "Controles (deben dar 0)").font = SUB
    r += 1
    ws_res.cell(r, 1, "Movimientos resumidos − filas de MOV BANCOS")
    x = ws_res.cell(r, 3, f"=C{tg}-COUNTA({rng('E')})")
    x.font = ROJA
    r += 1
    for k, (b, mo) in enumerate(bancos):
        col = "F" if mo == "Bs" else "H"
        ws_res.cell(r, 1, f"{b}: total del resumen − total de MOV BANCOS")
        x = ws_res.cell(r, 4 + k, f"=ROUND({L(4 + k)}{tg}-SUMIFS({rng(col)},{rng('I')},\"{b}\"),2)")
        x.number_format, x.font = NUM, ROJA
        r += 1
    ws_res.freeze_panes = "A5"

    # Hallazgos
    ws_hal["A1"] = f"Hallazgos de la revisión del archivo del cliente · {res.periodo}"
    ws_hal["A1"].font = TIT
    _enc(ws_hal, 3, ["#", "Tipo", "Banco", "Filas del cliente", "Detalle", "Acción"], [4, 9, 12, 22, 80, 50])
    fila = 4
    pend = res.pendientes
    if pend:
        _fila(ws_hal, fila, [1, "Revisar", "Todos", f"{len(pend)} movimiento(s)",
                             f"{len(pend)} movimiento(s) quedaron POR CLASIFICAR (resaltados en amarillo).",
                             "Asignar la cuenta en la app (con «recordar» para crear la regla)."])
        fila += 1
    for h in res.hallazgos:
        _fila(ws_hal, fila, [fila - 3, h.tipo, h.banco, h.filas, h.detalle, h.accion])
        fila += 1
    if fila == 4:
        ws_hal.cell(4, 5, "Sin hallazgos.")
    for row in ws_hal.iter_rows(min_row=4, max_row=fila):
        for c in row:
            c.alignment = Alignment(wrap_text=True, vertical="top")

    wb.save(salida)
    return Path(salida)
