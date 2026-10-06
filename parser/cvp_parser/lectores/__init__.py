"""Lectores por banco. Todos devuelven el modelo común (ResultadoLectura)."""
from .banco_100 import LectorBanco100
from .banplus import LectorBanplus
from .bnc import LectorBNC
from .plaza import LectorPlaza

LECTORES = {
    "100_BANCO": LectorBanco100(),
    "BNC": LectorBNC(),
    "BANPLUS": LectorBanplus(),
    "PLAZA": LectorPlaza(),
}

__all__ = ["LECTORES", "LectorBanco100", "LectorBNC", "LectorBanplus", "LectorPlaza"]
