"""Conversión de montos a Decimal exacto con 2 decimales.

Regla del proyecto: ningún monto pasa nunca por float. Cualquier valor que
tenga más de 2 decimales o que llegue como float es un error, no se redondea.
"""
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

CENTIMO = Decimal("0.01")
CERO = Decimal("0.00")

# Formato venezolano de los bancos: 1.234.567,89  (punto de miles, coma decimal)
_VE = re.compile(r"^-?\d{1,3}(\.\d{3})*,\d{2}$|^-?\d*,\d{2}$")   # ",50" = 0,50 (Banplus .xls)
# Formato del sistema contable (Mayor Analítico): 1,234,567.89
_US = re.compile(r"^-?\d{1,3}(,\d{3})*\.\d{2}$|^-?\d+\.\d{2}$")


class MontoInvalido(ValueError):
    """El texto o valor no es un monto válido con exactamente 2 decimales."""


def _normalizar_signo(texto: str) -> str:
    t = texto.strip()
    # Algunos bancos imprimen el signo al final: 1.234,56-
    if t.endswith("-") and not t.startswith("-"):
        t = "-" + t[:-1]
    return t


def monto_ve(texto: str) -> Decimal:
    """'1.234.567,89' -> Decimal('1234567.89'). Formato de los bancos venezolanos."""
    t = _normalizar_signo(texto)
    if not _VE.match(t):
        raise MontoInvalido(f"Monto con formato venezolano no reconocido: {texto!r}")
    t = t.replace(".", "").replace(",", ".")
    return Decimal(t.replace("-.", "-0.") if t.startswith("-.") else ("0" + t if t.startswith(".") else t))


def monto_us(texto: str) -> Decimal:
    """'1,234,567.89' -> Decimal('1234567.89'). Formato del Mayor Analítico."""
    t = _normalizar_signo(texto)
    if not _US.match(t):
        raise MontoInvalido(f"Monto con formato US no reconocido: {texto!r}")
    return Decimal(t.replace(",", ""))


def a_monto(valor: object) -> Decimal:
    """Valida que un valor ya numérico sea un monto exacto de 2 decimales.

    Acepta Decimal, int o str en notación simple ('123.45').
    Rechaza float: si un float llega aquí, el error está antes y hay que corregirlo allí.
    """
    if isinstance(valor, bool):
        raise MontoInvalido(f"Un booleano no es un monto: {valor!r}")
    if isinstance(valor, float):
        raise MontoInvalido(
            f"Se recibió un float ({valor!r}). Los montos deben llegar como Decimal o texto."
        )
    try:
        d = valor if isinstance(valor, Decimal) else Decimal(str(valor))
    except (InvalidOperation, ValueError) as e:
        raise MontoInvalido(f"No es un monto: {valor!r}") from e
    if not d.is_finite():
        raise MontoInvalido(f"No es un monto finito: {valor!r}")
    q = d.quantize(CENTIMO)
    if q != d:
        raise MontoInvalido(f"El monto {valor!r} tiene más de 2 decimales; no se redondea.")
    return q


def monto_excel(valor: object) -> Decimal:
    """Monto leído de una celda de Excel (.xls/.xlsx).

    Excel guarda los números como binario de punto flotante, así que aquí sí llega
    un float. Única excepción a la regla: se acepta solo si está a menos de una
    millonésima de un valor exacto de 2 decimales (p. ej. 50363951.109999955 →
    50363951.11). Si la celda trae más decimales de verdad, es un error.
    """
    if isinstance(valor, bool):
        raise MontoInvalido(f"Un booleano no es un monto: {valor!r}")
    if isinstance(valor, (int, Decimal)):
        return a_monto(valor)
    if isinstance(valor, float):
        d = Decimal(repr(valor))
        q = d.quantize(CENTIMO)
        if abs(d - q) > Decimal("0.000001"):
            raise MontoInvalido(f"La celda {valor!r} no es un monto de 2 decimales.")
        return q
    if isinstance(valor, str):
        t = valor.strip().lstrip("'")
        for f in (monto_ve, monto_us):
            try:
                return f(t)
            except MontoInvalido:
                pass
        return a_monto(t)
    raise MontoInvalido(f"No es un monto: {valor!r}")


def formato_ve(d: Decimal) -> str:
    """Decimal('1234567.89') -> '1.234.567,89' (para mensajes al analista)."""
    s = f"{a_monto(d):,.2f}"
    return s.replace(",", "_").replace(".", ",").replace("_", ".")
