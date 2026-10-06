"""Acceso mínimo a Supabase (PostgREST + Storage) con la clave secreta. Solo se usa en el servidor."""
from __future__ import annotations

import os
from typing import Any, Optional

import httpx

BUCKET = "archivos"


class Supabase:
    def __init__(self, url: Optional[str] = None, clave: Optional[str] = None, timeout: float = 60.0):
        self.url = (url or os.environ["SUPABASE_URL"]).rstrip("/")
        clave = clave or os.environ["SUPABASE_SECRET_KEY"]
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
