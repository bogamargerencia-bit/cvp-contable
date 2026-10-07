"""Una corrida: archivos vigentes del período → parser → Excel de revisión + resumen + partidas.

Nada se ajusta: si falta un archivo, un banco no tiene lector o un nombre no coincide, la corrida
termina en «error» con un mensaje claro para el analista.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import re
import tempfile
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any, Optional

from cvp_parser.cuadre import Estado
from cvp_parser.exportar import excel_conciliacion
from cvp_parser.lectores import LECTORES
from cvp_parser.proceso import ReporteCliente, procesar_cliente
from cvp_parser.revision import ABIERTAS, ResultadoRevision, aplicar, correcciones_caja, leer_revision

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


class ErrorCorrida(Exception):
    """Problema con los archivos de la corrida: se muestra tal cual al analista."""


@dataclass
class Entrada:
    """Lo que necesita procesar_cliente, ya con rutas locales."""
    cliente: str
    periodo: str
    bancos: list[tuple[str, Path, Path]] = field(default_factory=list)
    divisas: dict[str, Path] = field(default_factory=dict)
    cierre_caja: Optional[Path] = None
    kardex: Optional[Path] = None
    revision: Optional[Path] = None
    archivos_usados: list[str] = field(default_factory=list)
    avisos: list[str] = field(default_factory=list)


def _seguro(nombre: str) -> str:
    """Nombre de archivo apto para Storage (ASCII, sin espacios raros)."""
    s = unicodedata.normalize("NFKD", nombre).encode("ascii", "ignore").decode()
    return re.sub(r"[^A-Za-z0-9._-]+", "_", s).strip("_") or "archivo"


def armar_entrada(cliente: dict, periodo: dict, archivos: list[dict], descargar, carpeta: Path,
                  avisar=None) -> Entrada:
    """archivos: filas de `archivos` (vigentes) con `cuenta` embebida. descargar(ruta) → bytes.
    avisar(i, n, nombre): opcional, se llama antes de descargar cada archivo (para la barra de avance)."""
    clave = cliente.get("clave_config") or cliente["nombre"]
    e = Entrada(clave, f"{periodo['anio']}-{periodo['mes']:02d}")

    # Si hay dos vigentes del mismo tipo y cuenta, se usa el más reciente y se avisa.
    por_clave: dict[tuple, dict] = {}
    for a in sorted(archivos, key=lambda a: a["subido_en"]):
        k = (a["tipo"], a.get("cuenta_id"))
        if k in por_clave:
            e.avisos.append(f"Hay más de un archivo «{a['tipo']}» vigente para la misma cuenta; "
                            f"se usó el más reciente ({a['nombre_original']}).")
        por_clave[k] = a

    total = len(por_clave)          # aproximado: algún archivo puede no usarse

    def local(a: dict) -> Path:
        if avisar:
            avisar(min(len(e.archivos_usados) + 1, total), total, a["nombre_original"])
        datos = descargar(a["storage_path"])
        if hashlib.sha256(datos).hexdigest() != a["sha256"]:
            raise ErrorCorrida(f"El archivo «{a['nombre_original']}» no coincide con el que se subió "
                               "(huella SHA-256 distinta). Vuelve a subirlo.")
        p = carpeta / f"{a['id']}-{_seguro(a['nombre_original'])}"
        p.write_bytes(datos)
        e.archivos_usados.append(a["id"])
        return p

    cuentas: dict[str, dict] = {}
    for a in por_clave.values():
        if a.get("cuenta"):
            cuentas[a["cuenta_id"]] = a["cuenta"]

    faltan: list[str] = []
    for cid, c in sorted(cuentas.items(), key=lambda x: x[1]["nombre"]):
        edo = por_clave.get(("estado_cuenta", cid))
        libro = por_clave.get(("libro_sistema", cid))
        if c["tipo"] == "banco":
            if c["banco"] not in LECTORES:
                raise ErrorCorrida(f"La cuenta «{c['nombre']}» es de {c['banco']}, que todavía no tiene "
                                   f"lector en el parser (disponibles: {', '.join(LECTORES)}).")
            if not edo or not libro:
                faltan.append(f"«{c['nombre']}»: falta el " + ("estado de cuenta" if not edo else "libro del sistema"))
                continue
            if any(b == c["banco"] for b, _, _ in e.bancos):
                raise ErrorCorrida(f"Hay dos cuentas del banco {c['banco']} con archivos en este período; "
                                   "el parser procesa una cuenta por banco.")
            e.bancos.append((c["banco"], local(edo), local(libro)))
        else:
            if edo:
                e.avisos.append(f"«{c['nombre']}» es una cuenta en divisas: su estado de cuenta no se usa, "
                                "solo el libro del sistema.")
            if libro:
                e.divisas[c["nombre"]] = local(libro)
    if faltan:
        raise ErrorCorrida("Faltan archivos: " + "; ".join(faltan) + ".")
    if not e.bancos:
        raise ErrorCorrida("No hay ninguna cuenta bancaria con estado de cuenta y libro del sistema.")

    if a := por_clave.get(("cierre_caja", None)):
        e.cierre_caja = local(a)
    if a := por_clave.get(("kardex", None)):
        e.kardex = local(a)
    if a := por_clave.get(("revision", None)):
        e.revision = local(a)
    if e.kardex and not e.divisas:
        e.avisos.append("Se subió un Kardex pero ningún libro de cuentas en divisas: el Kardex no se usó.")
    return e


def ejecutar(e: Entrada, salida: Path, paso=None, numero: Optional[int] = None) -> tuple[ReporteCliente, ResultadoRevision]:
    """numero: número de corrida de la app; el Excel lo muestra para que coincida con la pantalla."""
    paso = paso or (lambda etapa, avance: None)
    anterior = leer_revision(e.revision) if e.revision else None
    paso(f"Leyendo, cuadrando y conciliando {len(e.bancos)} banco(s)"
         + (", caja" if e.cierre_caja else "") + (" y divisas" if e.divisas else ""), 45)
    rep = procesar_cliente(e.cliente, e.periodo, e.bancos, cierre_caja=e.cierre_caja,
                           correcciones_caja=correcciones_caja(anterior) if anterior else None,
                           libros_divisas=e.divisas or None, kardex=e.kardex if e.divisas else None)
    rv = aplicar(rep, anterior)
    if numero is not None:
        rv.corrida = numero
    paso("Generando el Excel de revisión", 80)
    excel_conciliacion(rep, salida, rv)
    return rep, rv


def _txt(v: Optional[Decimal]) -> Optional[str]:
    """Montos como texto para no pasar por float (Postgres los convierte a numeric exacto)."""
    return None if v is None else str(v)


def resumen(rep: ReporteCliente, rv: ResultadoRevision, e: Entrada) -> dict[str, Any]:
    bancos = []
    for b in rep.bancos:
        c = rep.cuadres[b]
        bancos.append({
            "banco": b,
            "cuadre": c.estado.value,
            "cuadra": c.estado is not Estado.NO_CUADRA,
            "conciliacion": {k.value: {"banco": v[0], "libro": v[1]}
                             for k, v in rep.conciliaciones[b].resumen().items()},
        })
    return {
        "cliente": rep.cliente,
        "periodo": rep.periodo,
        "corrida_revision": rv.corrida,
        "ok_general": rv.ok_general,
        "bancos": bancos,
        "bancos_no_cuadran": rv.bancos_no_cuadran,
        "situaciones": dict(Counter(p.situacion.value for p in rv.pendientes)),
        "abiertas": len(rv.abiertas),
        "resueltas": len(rv.resueltas),
        "alertas": rep.alertas + rep.cruces_divisas_bancos,
        "advertencias": rv.advertencias + e.avisos,
        "divisas": [{"cuenta": r.cuenta.nombre, "ventas_ok": r.ventas_ok, "nota": r.ventas_nota}
                    for r in rep.divisas],
        "uso": {"bancos": [b for b, _, _ in e.bancos], "divisas": list(e.divisas),
                "cierre_caja": e.cierre_caja is not None, "kardex": e.kardex is not None and bool(e.divisas),
                "revision": e.revision is not None},
    }


def partidas(corrida_id: str, rv: ResultadoRevision) -> list[dict[str, Any]]:
    filas = []
    for p in rv.pendientes:
        filas.append({
            "corrida_id": corrida_id,
            "codigo": p.codigo,
            "banco": p.banco,
            "origen": p.origen,
            "tipo": p.tipo,
            "fecha": p.fecha.isoformat() if p.fecha else None,
            "descripcion": p.descripcion,
            "monto_bs": _txt(p.monto_bs),
            "monto_usd": _txt(p.monto_usd),
            "detalle": p.detalle or None,
            "sugerencia": p.sugerencia or None,
            "situacion": p.situacion.value,
            "aviso": p.aviso or None,
            "propuesta": {"fila": p.propuesta[0], "fecha": p.propuesta[1].isoformat()} if p.propuesta else None,
        })
    return filas


def nombre_excel(e: Entrada, numero: int) -> str:
    return f"{_seguro(e.cliente)}_{e.periodo}_corrida{numero:02d}.xlsx"


# ---------------------------------------------------------------- orquestación con Supabase
def procesar_corrida(sb, corrida_id: str) -> bool:
    """Ejecuta la corrida y deja el resultado (o el error) en la tabla corridas.
    Devuelve False si la corrida no estaba pendiente (no existe o ya la tomó otro proceso)."""
    filtro = {"id": f"eq.{corrida_id}"}
    if not sb.reclamar("corridas", {"id": f"eq.{corrida_id}", "estado": "eq.pendiente"}, {"estado": "procesando"}):
        return False                              # no existe o ya la tomó otro proceso
    corrida = sb.uno("corridas", id=f"eq.{corrida_id}", select="*")

    def paso(etapa: str, avance: int) -> None:
        """Guarda la etapa para la barra de avance de la web. Si falla, no detiene la corrida."""
        try:
            sb.update("corridas", filtro, {"etapa": etapa, "avance": avance})
        except Exception:                          # noqa: BLE001
            pass

    paso("Preparando", 5)
    try:
        periodo = sb.uno("periodos", id=f"eq.{corrida['periodo_id']}", select="*")
        if periodo["estado"] == "cerrado":
            raise ErrorCorrida("El período está cerrado; un administrador debe reabrirlo para procesar.")
        cliente = sb.uno("clientes", id=f"eq.{periodo['cliente_id']}", select="*")
        archivos = sb.select("archivos", periodo_id=f"eq.{periodo['id']}", vigente="is.true",
                             select="*,cuenta:cuentas(*)")
        with tempfile.TemporaryDirectory() as tmp:
            carpeta = Path(tmp)
            e = armar_entrada(cliente, periodo, archivos, sb.descargar, carpeta,
                              avisar=lambda i, n, nom: paso(f"Descargando archivos ({i} de {n}): {nom}", 5 + 35 * i // n))
            salida = carpeta / nombre_excel(e, corrida["numero"])
            try:
                rep, rv = ejecutar(e, salida, paso, corrida["numero"])
            except (ValueError, KeyError) as ex:      # errores de lectura del parser
                raise ErrorCorrida(f"El parser no pudo leer los archivos: {ex}") from ex
            ruta = f"{cliente['id']}/{periodo['id']}/corridas/{salida.name}"
            paso("Guardando el Excel y los resultados", 90)
            sb.subir(ruta, salida.read_bytes(), XLSX)
        sb.insert("partidas", partidas(corrida_id, rv))
        sb.update("corridas", filtro, {
            "estado": "lista", "etapa": "Terminada", "avance": 100, "ok_general": rv.ok_general, "resumen": resumen(rep, rv, e),
            "excel_path": ruta, "archivos": e.archivos_usados, "error": None,
            "terminada_en": dt.datetime.now(dt.timezone.utc).isoformat(),
        })
    except Exception as ex:                        # noqa: BLE001 — todo error queda registrado
        msg = str(ex) if isinstance(ex, ErrorCorrida) else f"Error interno del servicio: {type(ex).__name__}: {ex}"
        sb.update("corridas", filtro, {"estado": "error", "error": msg[:2000],
                                       "terminada_en": dt.datetime.now(dt.timezone.utc).isoformat()})
        if not isinstance(ex, ErrorCorrida):
            raise
    return True
