"""La API rechaza con un mensaje claro cuando falta configuración (en vez de dejar la corrida en cola)."""
from fastapi.testclient import TestClient

from servicio import app as modulo

TOKEN = "t" * 40


def cliente(monkeypatch, **env):
    for k in ("SUPABASE_URL", "SUPABASE_SECRET_KEY", "SERVICIO_TOKEN"):
        monkeypatch.delenv(k, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    modulo._diag.update(t=0.0, d={})
    return TestClient(modulo.app)


def test_salud_sin_configurar(monkeypatch):
    r = cliente(monkeypatch).get("/salud").json()
    assert r["estado"] == "con problemas" and r["supabase"] == "sin configurar" and r["token"] == "falta o es corto"


def test_clave_publicable_se_detecta(monkeypatch):
    r = cliente(monkeypatch, SUPABASE_URL="https://x.supabase.co", SUPABASE_SECRET_KEY="sb_publishable_abc",
                SERVICIO_TOKEN=TOKEN).get("/salud").json()
    assert r["clave"].startswith("publicable")


def test_procesar_sin_token(monkeypatch):
    c = cliente(monkeypatch, SERVICIO_TOKEN=TOKEN)
    assert c.post("/procesar", json={"corrida_id": "00000000-0000-0000-0000-000000000000"}).status_code == 401


def test_procesar_sin_supabase_responde_503(monkeypatch):
    c = cliente(monkeypatch, SERVICIO_TOKEN=TOKEN)
    r = c.post("/procesar", json={"corrida_id": "00000000-0000-0000-0000-000000000000"},
               headers={"Authorization": f"Bearer {TOKEN}"})
    assert r.status_code == 503 and "Revisa las variables en Railway" in r.json()["detail"]
