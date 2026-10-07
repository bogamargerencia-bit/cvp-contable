"""Pruebas del servicio con un Supabase simulado en memoria y los archivos reales de agosto 2026
(si están en parser/tests/fixtures; si no, las pruebas con datos reales se saltan)."""
import hashlib
import uuid
from decimal import Decimal
from pathlib import Path

import pytest

from servicio.corrida import ErrorCorrida, armar_entrada, procesar_corrida

FIX = Path(__file__).resolve().parents[2] / "parser" / "tests" / "fixtures"
WEI = FIX / "wei_rest_2026_08"
CACAO = FIX / "cacao_2026_08"


class FakeSB:
    """Imita lo que usa procesar_corrida: tablas en memoria, storage en un dict."""

    def __init__(self):
        self.t = {k: [] for k in ("clientes", "periodos", "cuentas", "archivos", "corridas", "partidas")}
        self.storage: dict[str, bytes] = {}

    @staticmethod
    def _ok(fila, filtros):
        for k, v in filtros.items():
            if k == "select":
                continue
            op, _, val = v.partition(".")
            if op == "eq" and str(fila.get(k)) != val:
                return False
            if op == "is" and fila.get(k) is not (val == "true"):
                return False
        return True

    def select(self, tabla, **f):
        filas = [dict(x) for x in self.t[tabla] if self._ok(x, f)]
        if tabla == "archivos":
            for a in filas:
                a["cuenta"] = next((c for c in self.t["cuentas"] if c["id"] == a["cuenta_id"]), None)
        return filas

    def uno(self, tabla, **f):
        r = self.select(tabla, **f)
        return r[0] if r else None

    def update(self, tabla, filtro, datos):
        for x in self.t[tabla]:
            if self._ok(x, filtro):
                x.update(datos)

    def reclamar(self, tabla, filtro, datos):
        n = [x for x in self.t[tabla] if self._ok(x, filtro)]
        for x in n:
            x.update(datos)
        return bool(n)

    def insert(self, tabla, filas):
        self.t[tabla].extend(filas)

    def descargar(self, ruta):
        return self.storage[ruta]

    def subir(self, ruta, contenido, tipo):
        self.storage[ruta] = contenido

    # ---- ayudas para armar casos
    def cliente(self, nombre, clave):
        c = {"id": str(uuid.uuid4()), "nombre": nombre, "clave_config": clave}
        p = {"id": str(uuid.uuid4()), "cliente_id": c["id"], "anio": 2026, "mes": 8, "estado": "abierto"}
        self.t["clientes"].append(c)
        self.t["periodos"].append(p)
        return c, p

    def cuenta(self, c, nombre, tipo="banco", banco=None):
        k = {"id": str(uuid.uuid4()), "cliente_id": c["id"], "nombre": nombre, "tipo": tipo, "banco": banco}
        self.t["cuentas"].append(k)
        return k

    def archivo(self, p, ruta: Path, tipo, cuenta=None, n=[0]):
        n[0] += 1
        datos = ruta.read_bytes()
        a = {"id": str(uuid.uuid4()), "periodo_id": p["id"], "cuenta_id": cuenta["id"] if cuenta else None,
             "tipo": tipo, "storage_path": f"x/{n[0]}-{ruta.name}", "nombre_original": ruta.name,
             "sha256": hashlib.sha256(datos).hexdigest(), "vigente": True, "subido_en": f"2026-10-06T10:{n[0]:02d}"}
        self.storage[a["storage_path"]] = datos
        self.t["archivos"].append(a)
        return a

    def corrida(self, p, numero=1):
        r = {"id": str(uuid.uuid4()), "periodo_id": p["id"], "numero": numero, "estado": "pendiente"}
        self.t["corridas"].append(r)
        return r


def test_falta_un_archivo(tmp_path):
    sb = FakeSB()
    c, p = sb.cliente("X", None)
    k = sb.cuenta(c, "BNC 1800", banco="BNC")
    sb.archivo(p, Path(__file__), "estado_cuenta", k)
    with pytest.raises(ErrorCorrida, match="falta el libro del sistema"):
        armar_entrada(c, p, sb.select("archivos"), sb.descargar, tmp_path)


def test_banco_sin_lector(tmp_path):
    sb = FakeSB()
    c, p = sb.cliente("X", None)
    k = sb.cuenta(c, "Activo", banco="ACTIVO")
    sb.archivo(p, Path(__file__), "estado_cuenta", k)
    with pytest.raises(ErrorCorrida, match="todavía no tiene lector"):
        armar_entrada(c, p, sb.select("archivos"), sb.descargar, tmp_path)


def test_archivo_alterado(tmp_path):
    sb = FakeSB()
    c, p = sb.cliente("X", None)
    k = sb.cuenta(c, "BNC", banco="BNC")
    a = sb.archivo(p, Path(__file__), "estado_cuenta", k)
    sb.archivo(p, Path(__file__), "libro_sistema", k)
    sb.storage[a["storage_path"]] += b"x"
    with pytest.raises(ErrorCorrida, match="SHA-256"):
        armar_entrada(c, p, sb.select("archivos"), sb.descargar, tmp_path)


def test_error_queda_en_la_corrida():
    sb = FakeSB()
    c, p = sb.cliente("X", None)
    r = sb.corrida(p)
    procesar_corrida(sb, r["id"])
    assert r["estado"] == "error" and "No hay ninguna cuenta bancaria" in r["error"]
    procesar_corrida(sb, r["id"])                      # ya no está pendiente: no hace nada
    assert r["estado"] == "error"


def test_periodo_cerrado():
    sb = FakeSB()
    c, p = sb.cliente("X", None)
    p["estado"] = "cerrado"
    r = sb.corrida(p)
    procesar_corrida(sb, r["id"])
    assert r["estado"] == "error" and "cerrado" in r["error"]


@pytest.mark.skipif(not (WEI / "kardex.xlsx").exists(), reason="faltan los archivos reales de WEI REST")
def test_wei_completo():
    sb = FakeSB()
    c, p = sb.cliente("ALIMENTOS SIERRA DEL SOL, C.A.", "WEI REST")
    for banco, edo, libro in [("100_BANCO", "edo_100_banco.pdf", "sistema_100_banco.xls"),
                              ("BNC", "edo_bnc.xls", "sistema_bnc.xls"),
                              ("BANPLUS", "edo_banplus.xlsx", "sistema_banplus.xls")]:
        k = sb.cuenta(c, banco, banco=banco)
        sb.archivo(p, WEI / edo, "estado_cuenta", k)
        sb.archivo(p, WEI / libro, "libro_sistema", k)
    for nombre, f in [("Efectivo $", "sistema_efectivo.xls"), ("Zelle", "sistema_zelle.xls"),
                      ("USDT", "sistema_usdt.xls"), ("Fondo de efectivo", "sistema_fondo_efectivo.xls")]:
        sb.archivo(p, WEI / f, "libro_sistema", sb.cuenta(c, nombre, tipo="divisa"))
    sb.archivo(p, WEI / "ventas.xlsx", "cierre_caja")
    sb.archivo(p, WEI / "kardex.xlsx", "kardex")
    r = sb.corrida(p)
    procesar_corrida(sb, r["id"])
    assert r["estado"] == "lista", r.get("error")
    assert (r["etapa"], r["avance"]) == ("Terminada", 100)
    res = r["resumen"]
    assert [b["banco"] for b in res["bancos"]] == ["100_BANCO", "BANPLUS", "BNC"]
    assert len(res["divisas"]) == 4 and all(d["ventas_ok"] for d in res["divisas"])
    assert res["uso"] == {"bancos": ["100_BANCO", "BANPLUS", "BNC"],
                          "divisas": ["Efectivo $", "Fondo de efectivo", "USDT", "Zelle"],
                          "cierre_caja": True, "kardex": True, "revision": False}
    assert r["ok_general"] is False and res["abiertas"] == len(sb.t["partidas"]) > 0
    assert len(r["archivos"]) == 12
    assert r["excel_path"].endswith("corridas/WEI_REST_2026-08_corrida01.xlsx")
    assert sb.storage[r["excel_path"]][:2] == b"PK"
    # Montos como texto exacto (nunca float).
    for x in sb.t["partidas"]:
        for m in ("monto_bs", "monto_usd"):
            assert x[m] is None or (isinstance(x[m], str) and Decimal(x[m]) == Decimal(x[m]).quantize(Decimal("0.01")))


@pytest.mark.skipif(not (CACAO / "ventas.xlsx").exists(), reason="faltan los archivos reales de CACAO")
def test_cacao_con_revision_anterior(tmp_path):
    """Corrida 1 → el Excel emitido se reintroduce como «revision» → corrida 2 lo reconoce."""
    sb = FakeSB()
    c, p = sb.cliente("CACAO COFFEE NG, C.A.", "CACAO")
    for banco, edo, libro in [("BANPLUS", "edo_banplus.xls", "sistema_banplus.xls"),
                              ("PLAZA", "edo_plaza.pdf", "sistema_plaza.xls")]:
        k = sb.cuenta(c, banco, banco=banco)
        sb.archivo(p, CACAO / edo, "estado_cuenta", k)
        sb.archivo(p, CACAO / libro, "libro_sistema", k)
    sb.archivo(p, CACAO / "ventas.xlsx", "cierre_caja")
    r1 = sb.corrida(p, 1)
    procesar_corrida(sb, r1["id"])
    assert r1["estado"] == "lista", r1.get("error")
    assert r1["resumen"]["corrida_revision"] == 1
    devuelto = tmp_path / "revision.xlsx"
    devuelto.write_bytes(sb.storage[r1["excel_path"]])
    sb.archivo(p, devuelto, "revision")
    r2 = sb.corrida(p, 2)
    procesar_corrida(sb, r2["id"])
    assert r2["estado"] == "lista", r2.get("error")
    assert r2["resumen"]["corrida_revision"] == 2 and r2["resumen"]["uso"]["revision"] is True
    # Sin decisiones en el Excel: todo sigue abierto como «Sin decisión».
    assert set(r2["resumen"]["situaciones"]) == {"Sin decisión"}
