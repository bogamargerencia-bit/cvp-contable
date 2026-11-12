"""Clasificación por cuenta contable de un Excel de movimientos enviado por el cliente (p. ej. Delicateses).

El cliente no envía estados de cuenta: manda una hoja (MOV BANCOS) con los movimientos de todos sus bancos y
cajas, con la descripción que escribe su personal. Aquí:

  1. se lee la hoja (encabezados por nombre: Fecha, CUENTA, CUENTA 2, CLASIFICACIÓN, Descripción, Monto Bs.,
     BCV DÓLAR, Monto $., BANCO);
  2. se clasifica cada movimiento en una cuenta del catálogo del cliente con sus reglas, en este orden:
       a) lo que ya trae el cliente en CUENTA (se respeta);
       b) reglas «igual» (descripción normalizada idéntica, lo aprendido de meses anteriores);
       c) reglas «empieza» / «contiene» / «regex», en el orden de prioridad;
       d) «DIF X», «X DIF», «DIFERENCIA X»: la diferencia pagada va a la misma cuenta que X;
       e) parecido a una descripción conocida (errores de tipeo: FRIGORIDICO ≈ FRIGORIFICO) → SUGERIDO, se
          cuenta en su cuenta pero queda resaltado para confirmar;
       f) si nada aplica → POR CLASIFICAR (resaltado).
     Una regla puede marcar «sin cuenta» (revisar siempre a mano: p. ej. DEV CREDITO INMEDIATO).
  3. se revisa lo que trae el cliente: montos guardados como texto, con más de 2 decimales, sin tasa, fechas
     fuera del mes, movimientos repetidos y bloques de filas copiadas;
  4. se cuadra cada banco/caja con los saldos que informa el cliente (si los hay).

Nada se redondea en silencio: un monto con más de 2 decimales se conserva tal cual y queda como hallazgo.
Las reglas y el catálogo NO viven en el código (son datos del cliente): llegan como parámetros.
"""
from __future__ import annotations

import datetime as dt
import difflib
import re
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Iterable, Optional, Sequence

import openpyxl

from .montos import CENTIMO, CERO, MontoInvalido, monto_excel

# Estados de la clasificación de una fila
CLIENTE, REGLA, DIFERENCIA, SUGERIDO, PENDIENTE, EXCLUIDO = (
    "Viene del cliente", "Regla", "Diferencia a proveedor", "Sugerido (parecido)", "Por clasificar", "Excluido")
POR_CLASIFICAR = "POR CLASIFICAR"
BS, USD = "Bs.", "US$"
UMBRAL_PARECIDO = 0.88


# ---------------------------------------------------------------------------------------------------------------
# Datos de entrada: catálogo y reglas

@dataclass(frozen=True)
class Cuenta:
    nombre: str
    clasificacion: str
    grupo: str                       # encabezado del resumen: INGRESOS, GASTOS, …


@dataclass(frozen=True)
class Regla:
    tipo: str                        # igual / empieza / contiene / regex
    patron: str
    cuenta: Optional[str]            # None = «revisar siempre a mano»
    cuenta2: Optional[str] = None    # p. ej. PÉRDIDA POR DIFERENCIAL CAMBIARIO
    signo: Optional[str] = None      # "+" solo ingresos, "-" solo egresos, None ambos
    nota: str = ""                   # por qué existe la regla (se muestra como criterio)
    bancos: tuple[str, ...] = ()     # vacío = todos

    def aplica(self, norm: str, crudo: str, f: "Fila") -> bool:
        if self.signo == "+" and f.monto < 0 or self.signo == "-" and f.monto > 0:
            return False
        if self.bancos and f.banco not in self.bancos:
            return False
        p = self.patron
        if self.tipo == "igual":
            return norm == p
        if self.tipo == "empieza":
            return norm == p or norm.startswith(p + " ")
        if self.tipo == "contiene":
            return re.search(r"(^| )" + re.escape(p) + r"( |$)", norm) is not None
        if self.tipo == "regex":
            return re.search(p, crudo) is not None
        raise ValueError(f"Tipo de regla desconocido: {self.tipo}")


def normalizar(texto: object) -> str:
    """Mayúsculas, sin acentos ni signos, sin números (fechas, facturas, montos) y con espacios simples.
    'Transporte  Einor 11082026' → 'TRANSPORTE EINOR'; 'HOGAR IDELA PANADERÍA' → 'HOGAR IDELA PANADERIA'."""
    t = _sin_acentos(str(texto or "").upper())
    t = re.sub(r"[^A-Z0-9Ñ&]+", " ", t)
    t = " ".join(w for w in t.split() if not re.fullmatch(r"\d+", w))
    return t


def _sin_acentos(t: str) -> str:
    t = t.replace("Ñ", "\0")
    t = "".join(c for c in unicodedata.normalize("NFD", t) if unicodedata.category(c) != "Mn")
    return t.replace("\0", "Ñ")


# ---------------------------------------------------------------------------------------------------------------
# Lectura

@dataclass
class Fila:
    fila: int                        # fila en la hoja del cliente (para ubicarla)
    fecha: Optional[dt.date]
    descripcion: str
    banco: str                       # BANESCO / MERCANTIL / EFECTIVO / ZELLE …
    moneda: str                      # Bs. o US$
    monto: Decimal                   # en la moneda del banco; negativo = egreso
    tasa: Optional[Decimal]          # BCV del día (solo Bs.)
    cuenta_cliente: Optional[str] = None
    cuenta2_cliente: Optional[str] = None
    hallazgos: list[str] = field(default_factory=list)
    # resultado
    cuenta: Optional[str] = None
    cuenta2: Optional[str] = None
    estado: str = PENDIENTE
    criterio: str = ""
    excluida: bool = False

    @property
    def usd(self) -> Optional[Decimal]:
        """Monto en US$: el propio en cajas en dólares; en Bs. al BCV del día, redondeado al centavo."""
        if self.moneda == USD:
            return self.monto
        if not self.tasa:
            return None
        return (self.monto / self.tasa).quantize(CENTIMO, ROUND_HALF_UP)


@dataclass
class Hallazgo:
    banco: str
    filas: str
    tipo: str
    detalle: str
    accion: str


@dataclass
class Lectura:
    archivo: str
    hoja: str
    filas: list[Fila]
    hallazgos: list[Hallazgo] = field(default_factory=list)


ENCABEZADOS = {
    "fecha": ("FECHA",),
    "cuenta": ("CUENTA",),
    "cuenta2": ("CUENTA 2",),
    "clasificacion": ("CLASIFICACION",),
    "descripcion": ("DESCRIPCION",),
    "monto_bs": ("MONTO BS",),
    "tasa": ("BCV DOLAR", "TASA BCV", "BCV"),
    "monto_usd": ("MONTO $", "MONTO USD"),
    "banco": ("BANCO",),
}
MONEDA_USD = {"EFECTIVO", "ZELLE", "USDT", "BINANCE", "DIVISAS"}


def _clave_enc(v: object) -> str:
    t = _sin_acentos(str(v or "").upper()).strip()
    t = re.sub(r"[.:]", "", t)
    return re.sub(r"\s+", " ", t).strip()


def leer_movimientos(ruta: Path, hoja: Optional[str] = None, periodo: Optional[tuple[int, int]] = None) -> Lectura:
    """Lee la hoja de movimientos del cliente. periodo=(año, mes) para avisar fechas fuera del mes."""
    ruta = Path(ruta)
    wb = openpyxl.load_workbook(ruta, data_only=True)
    if hoja is None:
        hoja = next((n for n in wb.sheetnames if _clave_enc(n) == "MOV BANCOS"), None) or wb.sheetnames[0]
    ws = wb[hoja]
    fila_enc, cols = None, {}
    for r in range(1, min(ws.max_row, 30) + 1):
        vals = [_clave_enc(c.value) for c in ws[r]]
        if "DESCRIPCION" in vals and "BANCO" in vals:
            fila_enc = r
            for i, v in enumerate(vals):
                for k, nombres in ENCABEZADOS.items():
                    if v in nombres and k != "banco":
                        cols.setdefault(k, i)
            # Puede haber dos columnas BANCO (una vacía): se usa la que tiene datos.
            bancos = [i for i, v in enumerate(vals) if v == "BANCO"]
            cols["banco"] = max(bancos, key=lambda i: sum(1 for x in ws.iter_rows(min_row=r + 1, min_col=i + 1,
                                                                                  max_col=i + 1, values_only=True)
                                                           if x[0] not in (None, "")))
            break
    faltan = [k for k in ("fecha", "descripcion", "monto_bs", "banco") if k not in cols]
    if fila_enc is None or faltan:
        raise ValueError(f"{ruta.name}: no se encontró el encabezado de movimientos en la hoja «{hoja}» "
                         f"(faltan: {', '.join(faltan) or 'Descripción y BANCO'}).")

    lect = Lectura(ruta.name, hoja, [])
    for r, row in enumerate(ws.iter_rows(min_row=fila_enc + 1, values_only=True), fila_enc + 1):
        g = lambda k: row[cols[k]] if k in cols and cols[k] < len(row) else None
        banco = str(g("banco") or "").strip().upper()
        desc = str(g("descripcion") or "").strip()
        if not banco and not desc and g("monto_bs") in (None, "", 0) and g("fecha") is None:
            continue
        hall: list[str] = []
        moneda = USD if banco in MONEDA_USD else BS
        bruto = g("monto_usd") if moneda == USD else g("monto_bs")
        if moneda == USD and g("monto_bs") not in (None, 0, "") and bruto in (None, 0, ""):
            bruto = g("monto_bs")
        monto = _monto(bruto, hall)
        tasa = _tasa(g("tasa")) if moneda == BS else None
        if moneda == BS and not tasa:
            hall.append("Sin tasa BCV: no se puede calcular el monto en US$.")
        fecha = g("fecha")
        if isinstance(fecha, dt.datetime):
            fecha = fecha.date()
        elif not isinstance(fecha, dt.date):
            hall.append(f"Fecha no reconocida: {fecha!r}.")
            fecha = None
        if fecha and periodo and (fecha.year, fecha.month) != periodo:
            hall.append(f"Fecha {fecha:%d/%m/%Y} fuera del período.")
        if not normalizar(desc):
            hall.append("Sin descripción.")
        if not banco:
            hall.append("Sin banco.")
        lect.filas.append(Fila(r, fecha, desc, banco or "SIN BANCO", moneda, monto, tasa,
                               _texto(g("cuenta")), _texto(g("cuenta2")), hall))
    lect.hallazgos = _revisar(lect.filas)
    return lect


def _texto(v: object) -> Optional[str]:
    t = str(v or "").strip()
    return t or None


def _monto(v: object, hall: list[str]) -> Decimal:
    if v in (None, ""):
        hall.append("Sin monto.")
        return CERO
    if isinstance(v, str):
        hall.append(f"Monto guardado como texto ({v!r}): en el Excel del cliente no suma.")
    try:
        return monto_excel(v)
    except MontoInvalido:
        try:
            d = Decimal(repr(v)) if isinstance(v, float) else Decimal(str(v).strip().replace(",", "."))
        except Exception:
            hall.append(f"Monto no reconocido: {v!r}.")
            return CERO
        hall.append(f"Monto con más de 2 decimales ({d}): el banco solo maneja céntimos; se deja tal cual.")
        return d


def _tasa(v: object) -> Optional[Decimal]:
    if v in (None, "", 0):
        return None
    try:
        d = Decimal(repr(v)) if isinstance(v, float) else Decimal(str(v))
    except Exception:
        return None
    return d if d > 0 else None


# ---------------------------------------------------------------------------------------------------------------
# Revisión de lo que envía el cliente

def _rangos(nums: Sequence[int]) -> str:
    nums = sorted(nums)
    out, ini = [], None
    for i, n in enumerate(nums):
        if ini is None:
            ini = n
        if i + 1 == len(nums) or nums[i + 1] != n + 1:
            out.append(f"{ini}" if ini == n else f"{ini}–{n}")
            ini = None
    return ", ".join(out)


def _bloques_copiados(a: list[Decimal], usadas: set[int], minimo: int = 8, margen: int = 4
                      ) -> list[tuple[list[int], list[int]]]:
    """Zonas copiadas: filas seguidas (A) cuyos montos aparecen otra vez a una distancia casi constante (B),
    aunque dentro de la copia el orden cambie un poco (±`margen` filas) o falten algunos montos.
    Devuelve [(filas de A, sus gemelas en B)], con A y B sin solaparse."""
    n = len(a)
    pos: dict[Decimal, list[int]] = defaultdict(list)
    for k, v in enumerate(a):
        if v != 0:
            pos[v].append(k)
    out = []
    i = 0
    while i < n:
        mejor: list[tuple[int, int]] = []
        if a[i] != 0 and i not in usadas:
            for j0 in pos[a[i]]:
                if j0 == i or j0 in usadas:
                    continue
                d = j0 - i
                par, k, seguidos, tomadas = [(i, j0)], i + 1, 0, {j0}
                while k < n and seguidos <= 3:
                    t = next((t for t in pos.get(a[k], ()) if abs(t - k - d) <= margen and t not in tomadas
                              and t not in usadas), None) if a[k] != 0 else None
                    if t is None:
                        seguidos += 1
                    else:
                        par.append((k, t))
                        tomadas.add(t)
                        seguidos = 0
                    k += 1
                A, B = [x for x, _ in par], [y for _, y in par]
                distintos = len({a[x] for x in A}) >= 0.75 * len(A)     # nóminas iguales no son una copia
                if len(par) > len(mejor) and distintos and (max(A) < min(B) or max(B) < min(A)):
                    mejor = par
        if len(mejor) >= minimo:
            A, B = [x for x, _ in mejor], [y for _, y in mejor]
            out.append((A, B))
            usadas.update(range(min(A), max(A) + 1))
            usadas.update(range(min(B), max(B) + 1))
            i = max(A) + 1
        else:
            i += 1
    return out


def _grupos_repetidos(a: list[Decimal], usadas: set[int], tam: int = 4, grande: Decimal = Decimal("1000")
                      ) -> list[tuple[list[int], list[int]]]:
    """Grupos de `tam` filas seguidas con los mismos montos (en cualquier orden) que otro grupo, con al menos
    dos montos de 1.000 o más (para no marcar comisiones pequeñas que se repiten)."""
    n, out, vistos = len(a), [], set()
    firmas: dict[tuple, list[int]] = defaultdict(list)
    for i in range(n - tam + 1):
        v = range(i, i + tam)
        if any(k in usadas for k in v) or sum(1 for k in v if abs(a[k]) >= grande) < 2:
            continue
        firmas[tuple(sorted(a[k] for k in v))].append(i)
    ocupadas: set[int] = set()
    for inicios in sorted(firmas.values()):
        for x, y in zip(inicios, inicios[1:]):
            A, B = range(x, x + tam), range(y, y + tam)
            if y - x >= tam and not ocupadas.intersection(A) and not ocupadas.intersection(B):
                ocupadas.update(A)
                ocupadas.update(B)
                out.append((list(A), list(B)))
    return out


def _unir_zonas(zonas: list[tuple[list[int], list[int]]], hueco: int = 6) -> list[tuple[list[int], list[int]]]:
    """Une zonas repetidas contiguas (la copia de un bloque suele detectarse en trozos)."""
    out: list[tuple[list[int], list[int]]] = []
    for A, B in sorted(zonas, key=lambda z: min(z[0])):
        if out:
            pa, pb = out[-1]
            mismo_lado = (min(B) > max(A)) == (min(pb) > max(pa))
            # un grupo suelto de 4 solo se suma a una copia grande que viene antes (no al revés)
            if mismo_lado and (len(pa) >= 8 or len(A) < 8) and min(A) - max(pa) <= hueco and not set(A) & set(pb) and not set(B) & set(pa):
                out[-1] = (pa + A, pb + B)
                continue
        out.append((list(A), list(B)))
    return out


def _revisar(filas: list[Fila]) -> list[Hallazgo]:
    out: list[Hallazgo] = []
    por_banco: dict[str, list[Fila]] = defaultdict(list)
    for f in filas:
        por_banco[f.banco].append(f)
    # Hallazgos por fila (agrupados por tipo)
    tipos: dict[tuple[str, str], list[Fila]] = defaultdict(list)
    for f in filas:
        for h in f.hallazgos:
            tipos[(f.banco, re.sub(r"\(.*?\)|\d{2}/\d{2}/\d{4}", "…", h))].append(f)
    for (banco, tipo), fs in tipos.items():
        accion = ("Ajustar al monto exacto del banco." if "decimales" in tipo else
                  "Convertir a número." if "texto" in tipo else
                  "Confirmar la fecha con el cliente." if "Fecha" in tipo else
                  "Pedir la tasa o completarla." if "tasa" in tipo else "Revisar con el cliente.")
        out.append(Hallazgo(banco, _rangos([f.fila for f in fs]), "Revisar", f"{len(fs)} fila(s): {tipo}", accion))

    for banco, fs in por_banco.items():
        a = [f.monto for f in fs]
        usadas: set[int] = set()
        zonas = [(A, B) for A, B in _bloques_copiados(a, usadas)] + _grupos_repetidos(a, usadas)
        for A, B in _unir_zonas(zonas):
            if len(A) >= 8:
                vacias = lambda Z: sum(1 for k in range(min(Z), max(Z) + 1) if not normalizar(fs[k].descripcion))
                if vacias(B) > vacias(A):           # la zona sin descripción es la probable copia: va primero
                    A, B = B, A
                ia, ib = (fs[min(A)].fila, fs[max(A)].fila), (fs[min(B)].fila, fs[max(B)].fila)
                total, sin_desc = max(A) - min(A) + 1, vacias(A)
                out.append(Hallazgo(
                    banco, f"{ia[0]}–{ia[1]} y {ib[0]}–{ib[1]}", "Posible duplicado",
                    f"De las {total} filas {ia[0]}–{ia[1]}, {len(A)} se repiten con el mismo monto (casi en el mismo "
                    f"orden) en las filas {ib[0]}–{ib[1]}"
                    + (f"; {sin_desc} vienen sin descripción (probablemente son la copia)" if sin_desc else "") + ".",
                    "Confirmar con el estado de cuenta y el saldo; si es una copia, marcar esas filas para excluir."))
            else:
                fa, fb = [fs[k].fila for k in A], [fs[k].fila for k in B]
                fe = (fs[A[0]].fecha, fs[B[0]].fecha)
                out.append(Hallazgo(
                    banco, f"{_rangos(fa)} y {_rangos(fb)}", "Revisar",
                    f"{len(A)} movimientos seguidos con los mismos montos ({', '.join(str(a[k]) for k in A)})"
                    + (f", el {fe[0]:%d/%m} y el {fe[1]:%d/%m}." if all(fe) else "."),
                    "Confirmar con el estado de cuenta si se cobraron dos veces."))
    return out


# ---------------------------------------------------------------------------------------------------------------
# Clasificación

def clasificar(filas: Iterable[Fila], reglas: Sequence[Regla], catalogo: Sequence[Cuenta],
               excluir: Iterable[int] = ()) -> None:
    """Asigna cuenta, cuenta 2, estado y criterio a cada fila (en el lugar)."""
    nombres = {c.nombre for c in catalogo}
    excl = set(excluir)
    iguales = [r for r in reglas if r.tipo == "igual"]
    otras = [r for r in reglas if r.tipo != "igual"]
    conocidas = {r.patron: r for r in iguales if r.cuenta}

    def buscar(norm: str, crudo: str, f: Fila) -> Optional[Regla]:
        for r in iguales:
            if r.aplica(norm, crudo, f):
                return r
        for r in otras:
            if r.aplica(norm, crudo, f):
                return r
        return None

    for f in filas:
        f.cuenta = f.cuenta2 = None
        f.excluida = f.fila in excl
        norm = normalizar(f.descripcion)
        crudo = _sin_acentos(f.descripcion.upper())
        if f.cuenta_cliente:
            f.cuenta, f.cuenta2, f.estado, f.criterio = f.cuenta_cliente, f.cuenta2_cliente, CLIENTE, \
                "Cuenta indicada por el cliente"
        elif (r := buscar(norm, crudo, f)) is not None:
            _aplicar(f, r, REGLA, r.nota or f"Regla: {r.tipo} «{r.patron}»")
        elif (m := re.fullmatch(r"(?:DIF|DIFERENCIA) (.+)|(.+) DIF", norm)) and \
                (r := buscar(m.group(1) or m.group(2), crudo, f)) is not None and r.cuenta:
            _aplicar(f, r, DIFERENCIA, f"Diferencia pagada a «{m.group(1) or m.group(2)}»: misma cuenta")
        elif norm and (p := difflib.get_close_matches(norm, conocidas, n=1, cutoff=UMBRAL_PARECIDO)):
            _aplicar(f, conocidas[p[0]], SUGERIDO, f"Parecido a «{p[0]}»: confirmar")
        else:
            f.estado, f.criterio = PENDIENTE, "Ninguna regla reconoce la descripción"
        if f.cuenta and f.cuenta not in nombres:
            f.criterio += f" · OJO: la cuenta «{f.cuenta}» no está en el catálogo"
        if f.excluida:
            f.estado = EXCLUIDO
            f.criterio = "Excluida por el analista" + (f" (cuenta: {f.cuenta})" if f.cuenta else "")
        if not f.cuenta2:
            f.cuenta2 = f.cuenta2_cliente


def _aplicar(f: Fila, r: Regla, estado: str, criterio: str) -> None:
    f.estado, f.criterio = estado, criterio
    if r.cuenta is None:
        f.estado = PENDIENTE
        f.criterio = r.nota or "Esta descripción se revisa siempre a mano"
        return
    f.cuenta, f.cuenta2 = r.cuenta, r.cuenta2


def aprender(filas: Iterable[Fila], ya: Sequence[Regla] = ()) -> list[Regla]:
    """Reglas «igual» a partir de filas ya clasificadas (p. ej. un mes cerrado). Una descripción que fue a
    cuentas distintas no se aprende (queda para revisión a mano). Se omite lo que las reglas `ya` resuelven igual."""
    vistas: dict[str, Counter] = defaultdict(Counter)
    for f in filas:
        n = normalizar(f.descripcion)
        if n and f.cuenta_cliente:
            vistas[n][(f.cuenta_cliente, f.cuenta2_cliente if f.cuenta_cliente in ("ALQUILER", "CAMBIO") else None)] += 1
    out = []
    for n, c in sorted(vistas.items()):
        if len(c) != 1:
            continue
        (cuenta, cuenta2), _ = c.most_common(1)[0]
        prueba = Fila(0, None, n, "", BS, Decimal("-1"), None)
        r_ya = next((r for r in ya if r.aplica(n, n, prueba)), None)
        if r_ya and r_ya.cuenta == cuenta:
            continue
        out.append(Regla("igual", n, cuenta, cuenta2, nota="Igual que en meses anteriores"))
    return out


def claves(filas: Iterable[Fila]) -> dict[int, str]:
    """fila -> clave del movimiento dentro del mes, estable aunque el archivo se vuelva a subir:
    banco|fecha|monto|descripción normalizada#ocurrencia (si hay varios iguales, se numeran en orden).
    Es la clave de public.asignaciones_cuenta (cuenta elegida a mano por el analista)."""
    vistos: Counter = Counter()
    out = {}
    for f in filas:
        k = f"{normalizar(f.banco)}|{f.fecha:%Y-%m-%d}|{f.monto}|{normalizar(f.descripcion)}" if f.fecha else \
            f"{normalizar(f.banco)}|sin-fecha|{f.monto}|{normalizar(f.descripcion)}"
        vistos[k] += 1
        out[f.fila] = f"{k}#{vistos[k]}"
    return out


# ---------------------------------------------------------------------------------------------------------------
# Cuadre por banco / caja

@dataclass
class CuadreBanco:
    banco: str
    moneda: str
    filas: list[Fila]
    saldo_inicial: Optional[Decimal] = None
    saldo_final_cliente: Optional[Decimal] = None

    @property
    def validas(self) -> list[Fila]:
        return [f for f in self.filas if not f.excluida]

    @property
    def creditos(self) -> Decimal:
        return sum((f.monto for f in self.validas if f.monto > 0), CERO)

    @property
    def debitos(self) -> Decimal:
        return sum((-f.monto for f in self.validas if f.monto < 0), CERO)

    @property
    def saldo_calculado(self) -> Optional[Decimal]:
        return None if self.saldo_inicial is None else self.saldo_inicial + self.creditos - self.debitos

    @property
    def diferencia(self) -> Optional[Decimal]:
        if self.saldo_calculado is None or self.saldo_final_cliente is None:
            return None
        return self.saldo_calculado - self.saldo_final_cliente

    def dias_en_negativo(self) -> list[tuple[dt.date, Decimal]]:
        if self.saldo_inicial is None:
            return []
        s, por_dia = self.saldo_inicial, {}
        for f in self.validas:
            s += f.monto
            if f.fecha:
                por_dia[f.fecha] = s
        return [(d, v) for d, v in sorted(por_dia.items()) if v < 0]


def cuadres(filas: Sequence[Fila], saldos: dict[str, tuple[Optional[Decimal], Optional[Decimal]]] | None = None
            ) -> list[CuadreBanco]:
    saldos = {k.upper(): v for k, v in (saldos or {}).items()}
    por: dict[str, list[Fila]] = defaultdict(list)
    for f in filas:
        por[f.banco].append(f)
    out = []
    for banco, fs in por.items():
        ini, fin = saldos.get(banco, (None, None))
        out.append(CuadreBanco(banco, fs[0].moneda, fs, ini, fin))
    return out


# ---------------------------------------------------------------------------------------------------------------
# Resultado

@dataclass
class Resultado:
    cliente: str
    periodo: str
    lectura: Lectura
    catalogo: list[Cuenta]
    cuadres: list[CuadreBanco]

    @property
    def filas(self) -> list[Fila]:
        return self.lectura.filas

    def por_cuenta(self) -> dict[str, list[Fila]]:
        out: dict[str, list[Fila]] = defaultdict(list)
        for f in self.filas:
            if not f.excluida:
                out[f.cuenta or POR_CLASIFICAR].append(f)
        return out

    @property
    def pendientes(self) -> list[Fila]:
        return [f for f in self.filas if not f.excluida and f.estado in (PENDIENTE, SUGERIDO)]

    def control(self) -> dict[str, tuple[Decimal, Decimal]]:
        """Por moneda: (suma de lo clasificado en cuentas + por clasificar, suma de los movimientos válidos).
        Deben ser iguales."""
        out = {}
        for mon in (BS, USD):
            validas = [f for f in self.filas if not f.excluida and f.moneda == mon]
            por = sum((f.monto for fs in self.por_cuenta().values() for f in fs if f.moneda == mon), CERO)
            out[mon] = (por, sum((f.monto for f in validas), CERO))
        return out


def procesar(cliente: str, periodo: str, ruta: Path, reglas: Sequence[Regla], catalogo: Sequence[Cuenta],
             excluir: Iterable[int] = (), saldos: dict | None = None, hoja: Optional[str] = None) -> Resultado:
    anio, mes = (int(x) for x in periodo.split("-"))
    lect = leer_movimientos(ruta, hoja, (anio, mes))
    clasificar(lect.filas, reglas, catalogo, excluir)
    return Resultado(cliente, periodo, lect, list(catalogo), cuadres(lect.filas, saldos))
