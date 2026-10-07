"""Acceso mínimo a Supabase (PostgREST + Storage) con la clave secreta. Solo se usa en el servidor."""
from __future__ import annotations

import base64
import json
import os
from typing import Any, Optional

import httpx

BUCKET = "archivos"


def tipo_clave(clave: str) -> str:
    """Qué clase de clave es, sin revelarla: secreta, publicable, JWT service_role/anon."""
    clave = clave.strip()
    if not clave:
        return "falta"
    if clave.startswith("sb_secret_"):
        return "secreta"
    if clave.startswith("sb_publishable_"):
        return "publicable (incorrecta: se necesita la secreta)"
    try:
        carga = clave.split(".")[1]
        rol = json.loads(base64.urlsafe_b64decode(carga + "=" * (-len(carga) % 4))).get("role")
        return "jwt service_role" if rol == "service_role" else f"jwt {rol} (incorrecta: se necesita la secreta)"
    except Exception:                              # noqa: BLE001
        return "formato desconocido"


def diagnostico() -> dict[str, str]:
    """Comprueba la configuración y que la clave tenga acceso de servicio (lee el bucket privado)."""
    url = os.environ.get("SUPABASE_URL", "").strip()
    clave = os.environ.get("SUPABASE_SECRET_KEY", "")
    d = {"url": "ok" if url.startswith("https://") else "falta o inválida", "clave": tipo_clave(clave)}
    if d["url"] != "ok" or d["clave"] == "falta":
        d["supabase"] = "sin configurar"
        return d
    if clave != clave.strip():
        d["clave"] += " (tiene espacios al inicio o al final)"
    try:
        r = Supabase(url, clave.strip(), timeout=10).http.get(f"{url.rstrip('/')}/storage/v1/bucket/{BUCKET}")
        d["supabase"] = "ok" if r.status_code == 200 else f"sin acceso de servicio (HTTP {r.status_code})"
    except Exception as ex:                        # noqa: BLE001
        d["supabase"] = f"no se pudo conectar ({type(ex).__name__})"
    return d


class Supabase:
    def __init__(self, url: Optional[str] = None, clave: Optional[str] = None, timeout: float = 60.0):
        self.url = (url or os.environ["SUPABASE_URL"]).rstrip("/")
        clave = (clave or os.environ["SUPABASE_SECRET_KEY"]).strip()
        h = {"apikey": clave}
        if not clave.startswith("sb_"):          # clave service_role antigua (JWT)
            h["Authorization"] = f"Bearer {clave}"
        self.http = httpx.Client(headers=h, timeout=timeout)

    # ------------------------------------------------------------ base de datos
    def select(self, tabla: str, **params: str) -> list[dict[str, Any]]:
        r = self.http.get(f"{self.url}/rest/v1/{tabla}", params=params)
        r.raise_for_status()
        return r.json()

    def uno(self, tabla: str, **params: str) -> Optional[dict[str, Any]]:
        filas = self.select(tabla, **params)
        return filas[0] if filas else None

    def update(self, tabla: str, filtro: dict[str, str], datos: dict[str, Any]) -> None:
        r = self.http.patch(f"{self.url}/rest/v1/{tabla}", params=filtro, json=datos,
                            headers={"Prefer": "return=minimal"})
        r.raise_for_status()

    def reclamar(self, tabla: str, filtro: dict[str, str], datos: dict[str, Any]) -> bool:
        """UPDATE condicional: True solo si esta llamada cambió alguna fila (evita procesar dos veces)."""
        r = self.http.patch(f"{self.url}/rest/v1/{tabla}", params=filtro, json=datos,
                            headers={"Prefer": "return=representation"})
        r.raise_for_status()
        return bool(r.json())

    def insert(self, tabla: str, filas: list[dict[str, Any]]) -> None:
        for i in range(0, len(filas), 500):
            r = self.http.post(f"{self.url}/rest/v1/{tabla}", json=filas[i:i + 500],
                               headers={"Prefer": "return=minimal"})
            r.raise_for_status()

    # ------------------------------------------------------------ storage
    def descargar(self, ruta: str) -> bytes:
        r = self.http.get(f"{self.url}/storage/v1/object/{BUCKET}/{ruta}")
        r.raise_for_status()
        return r.content

    def subir(self, ruta: str, contenido: bytes, tipo: str) -> None:
        r = self.http.post(f"{self.url}/storage/v1/object/{BUCKET}/{ruta}", content=contenido,
                           headers={"Content-Type": tipo, "x-upsert": "true"})
        r.raise_for_status()
