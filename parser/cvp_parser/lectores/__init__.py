"""Lectores por banco. Todos devuelven el modelo común (ResultadoLectura)."""
from .banco_100 import LectorBanco100
from .banplus import LectorBanplus
from .bancamiga import LectorBancamiga
from .bnc import LectorBNC
from .plaza import LectorPlaza
from .venezolano import LectorVenezolano
from .mercantil import LectorMercantil

LECTORES = {
    "100_BANCO": LectorBanco100(),
    "BNC": LectorBNC(),
    "BANPLUS": LectorBanplus(),
    "PLAZA": LectorPlaza(),
    "VENEZOLANO": LectorVenezolano(),
    "BANCAMIGA": LectorBancamiga(),
    "MERCANTIL": LectorMercantil(),
}

__all__ = ["LECTORES", "LectorBanco100", "LectorBNC", "LectorBanplus", "LectorPlaza", "LectorVenezolano",
           "LectorBancamiga", "LectorMercantil"]
