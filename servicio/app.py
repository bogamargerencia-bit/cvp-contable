"""Servicio CVP Contable: procesa corridas con el parser.

La web (Vercel) crea la corrida en Supabase y llama a POST /procesar con el token compartido.
El servicio responde de inmediato (202) y procesa en segundo plano; la web consulta el estado en Supabase.
"""
from __future__ import annotations

import hmac
import logging
import os
import threading
import time
import uuid

from fastapi import BackgroundTasks, FastAPI, Header, HTTPException
from pydantic import BaseModel

from .corrida import procesar_corrida
from .supabase_rest import Supabase, diagnostico

log = logging.getLogger("cvp.servicio")
app = FastAPI(title="CVP Contable — servicio", docs_url=None, redoc_url=None, openapi_url=None)
_turno = threading.Semaphore(int(os.environ.get("CORRIDAS_SIMULTANEAS", "2")))


class Pedido(BaseModel):
    corrida_id: uuid.UUID


def _autorizar(authorization: str | None) -> None:
    esperado = os.environ.get("SERVICIO_TOKEN", "")
    if len(esperado) < 32:
        raise HTTPException(500, "SERVICIO_TOKEN no configurado (mínimo 32 caracteres)")
    dado = (authorization or "").removeprefix("Bearer ").strip()
    if not hmac.compare_digest(dado.encode(), esperado.encode()):
        raise HTTPException(401, "No autorizado")


_diag: dict = {"t": 0.0, "d": {}}


def _diagnostico_reciente() -> dict[str, str]:
    """Diagnóstico de Supabase, recalculado como mucho cada 60 s."""
    if time.monotonic() - _diag["t"] > 60 or _diag["d"].get("supabase") != "ok":
        _diag["d"], _diag["t"] = diagnostico(), time.monotonic()
    return _diag["d"]


def _trabajar(corrida_id: str) -> None:
    with _turno:
        try:
            if not procesar_corrida(Supabase(), corrida_id):
                log.warning("corrida %s: no estaba pendiente o no existe; no se procesó", corrida_id)
        except Exception:                          # noqa: BLE001 — ya quedó registrado en la corrida
            log.exception("corrida %s terminó con error interno", corrida_id)


@app.on_event("startup")
def _recuperar() -> None:
    """Si el servicio se reinició a mitad de una corrida, esa corrida no terminará: se marca como error."""
    try:
        Supabase().update("corridas", {"estado": "eq.procesando"},
                          {"estado": "error", "error": "El servicio se reinició durante el proceso. Vuelve a procesar."})
    except Exception:                              # noqa: BLE001
        log.exception("no se pudieron revisar corridas interrumpidas")


@app.get("/salud")
def salud() -> dict[str, str]:
    """Estado del servicio y de su conexión con Supabase (sin revelar claves)."""
    d = _diagnostico_reciente()
    return {"estado": "ok" if d.get("supabase") == "ok" else "con problemas", **d,
            "token": "ok" if len(os.environ.get("SERVICIO_TOKEN", "")) >= 32 else "falta o es corto"}


@app.post("/procesar", status_code=202)
def procesar(pedido: Pedido, tareas: BackgroundTasks, authorization: str | None = Header(default=None)):
    _autorizar(authorization)
    d = _diagnostico_reciente()
    if d.get("supabase") != "ok":
        # Se rechaza aquí para que la web marque la corrida con un error claro (en vez de quedar en cola).
        raise HTTPException(503, f"El servicio no puede acceder a Supabase: clave {d.get('clave')}, "
                                 f"conexión {d.get('supabase')}. Revisa las variables en Railway.")
    tareas.add_task(_trabajar, str(pedido.corrida_id))
    return {"corrida_id": str(pedido.corrida_id), "estado": "en cola"}
