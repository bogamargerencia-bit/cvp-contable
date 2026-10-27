"""Lectores por banco. Todos devuelven el modelo común (ResultadoLectura)."""
from .banco_100 import LectorBanco100
from .banplus import LectorBanplus
from .bancamiga import LectorBancamiga
from .bnc import LectorBNC
from .plaza import LectorPlaza
from .venezolano import LectorVenezolano
from .mercantil import LectorMercantil
from .banesco import LectorBanesco
from .activo import LectorActivo

LECTORES = {
    "100_BANCO": LectorBanco100(),
    "BNC": LectorBNC(),
    "BANPLUS": LectorBanplus(),
    "PLAZA": LectorPlaza(),
    "VENEZOLANO": LectorVenezolano(),
    "BANCAMIGA": LectorBancamiga(),
    "MERCANTIL": LectorMercantil(),
    "BANESCO": LectorBanesco(),
    "ACTIVO": LectorActivo(),
}

__all__ = ["LECTORES", "LectorBanco100", "LectorBNC", "LectorBanplus", "LectorPlaza", "LectorVenezolano",
           "LectorBancamiga", "LectorMercantil", "LectorBanesco", "LectorActivo", "leer_estado"]


NOMBRES = {"100_BANCO": "100% Banco", "BNC": "BNC", "BANPLUS": "Banplus", "PLAZA": "Banco Plaza",
           "VENEZOLANO": "Venezolano de Crédito", "BANCAMIGA": "Bancamiga", "MERCANTIL": "Mercantil",
           "BANESCO": "Banesco", "ACTIVO": "Banco Activo"}


def _reconocen(ruta) -> list[str]:
    out = []
    for k, lector in LECTORES.items():
        try:
            if lector.reconoce(ruta):
                out.append(k)
        except Exception:                      # noqa: BLE001 — reconocer nunca debe tumbar la lectura
            pass
    return out


def leer_estado(banco: str, ruta, cuenta: str = ""):
    """Lee un estado de cuenta con el lector del banco de la cuenta. Si falla, explica en lenguaje claro si el
    archivo parece de otro banco (p. ej. un PDF de Banco Activo subido en una cuenta de Banplus)."""
    from pathlib import Path as _P
    ruta = _P(ruta)
    quien = f"«{cuenta}» ({NOMBRES.get(banco, banco)})" if cuenta else NOMBRES.get(banco, banco)
    if banco not in LECTORES:
        raise ValueError(f"{quien}: ese banco todavía no tiene lector en la app.")
    try:
        res = LECTORES[banco].leer([ruta])
    except Exception as ex:
        otros = [k for k in _reconocen(ruta) if k != banco]
        nombre = ruta.name.split("-", 5)[-1] if ruta.name.count("-") >= 5 else ruta.name
        if otros:
            raise ValueError(f"El archivo «{nombre}» se subió en la cuenta {quien}, pero parece un estado de cuenta de "
                             f"{' o '.join(NOMBRES.get(o, o) for o in otros)}. Súbelo en la cuenta de ese banco.") from ex
        texto = ruta.read_bytes()[:5] if ruta.exists() else b""
        tipo = "PDF" if texto.startswith(b"%PDF") else "Excel" if texto[:2] in (b"PK", b"\xd0\xcf") else "otro formato"
        raise ValueError(f"El archivo «{nombre}» ({tipo}) no se pudo leer como estado de cuenta de {quien}: "
                         f"¿es de otro banco, o es otro formato del mismo banco? Detalle: {ex}") from ex
    if len(res.extractos) != 1:
        raise ValueError(f"{quien}: se esperaba un estado de cuenta en {ruta.name}, se encontraron {len(res.extractos)}.")
    return res.extractos[0]
