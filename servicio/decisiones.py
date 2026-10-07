"""Decisiones del analista para una corrida.

La fuente es la base de datos (tabla `decisiones`, se registran en la pantalla de Revisión de la web).
El Excel de revisión sigue sirviendo: si hay uno vigente en el período, sus decisiones se incorporan,
salvo para las partidas que alguien decidió en línea DESPUÉS de subir ese Excel (gana lo más reciente).
Las decisiones válidas que vienen del Excel se guardan en la base para que aparezcan en la web.

Se arma el mismo `RevisionAnterior` que antes salía solo del Excel, así revision.aplicar() no cambia:
  - corrida anterior  = la última corrida «lista» del período
  - decisiones        = una por cada partida de esa corrida (vacía si no tiene)
  - propuestas        = correcciones de fecha de caja propuestas en esa corrida
  - correcciones      = las ya aceptadas (tabla correcciones_caja) + las que traiga el Excel
  - historial         = el que quedó en el resumen de la corrida anterior (o el del Excel)
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Any, Optional

from cvp_parser.revision import DecisionLeida, RevisionAnterior, _validar, leer_revision

from .corrida import Entrada, ErrorCorrida


def _fh(s: Any) -> dt.datetime:
    """Fecha y hora de Postgres/PostgREST (ISO); sin zona se asume UTC."""
    v = s if isinstance(s, dt.datetime) else dt.datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    return v if v.tzinfo else v.replace(tzinfo=dt.timezone.utc)


def _fecha(s: Any) -> dt.date:
    return s if isinstance(s, dt.date) else dt.date.fromisoformat(str(s)[:10])


@dataclass
class Previo:
    anterior: Optional[RevisionAnterior]
    nuevas: list[dict[str, Any]] = field(default_factory=list)     # decisiones del Excel a guardar en la base
    revisor_por_codigo: dict[str, str] = field(default_factory=dict)  # código → uuid de quien decidió


def _historial_desde_json(filas: list[list]) -> list[list]:
    out = []
    for f in filas or []:
        f = list(f)
        if len(f) > 1 and isinstance(f[1], str):
            try:
                f[1] = _fh(f[1]).replace(tzinfo=None)
            except ValueError:
                pass
        out.append(f)
    return out


def cargar(sb, periodo: dict, corrida: dict, e: Entrada) -> Previo:
    excel = leer_revision(e.revision) if e.revision else None
    if excel and (excel.cliente, excel.periodo) != (e.cliente, e.periodo):
        raise ErrorCorrida(f"El Excel de revisión es de {excel.cliente} {excel.periodo}, "
                           f"no de {e.cliente} {e.periodo}. Quítalo o sube el correcto.")
    previas = [c for c in sb.select("corridas", periodo_id=f"eq.{periodo['id']}", estado="eq.lista",
                                    select="id,numero,resumen")
               if c["numero"] < corrida["numero"]]
    if not previas:
        return Previo(excel)              # primera corrida del período en la base: solo el Excel, si lo hay
    prev = max(previas, key=lambda c: c["numero"])

    filas = sb.select("partidas", corrida_id=f"eq.{prev['id']}", select="codigo,tipo,descripcion,propuesta")
    vig = {d["codigo"]: d for d in sb.select("decisiones", periodo_id=f"eq.{periodo['id']}", vigente="is.true",
                                             select="codigo,decision,comentario,revisado_por,decidido_en")}
    ids = sorted({d["revisado_por"] for d in vig.values()})
    nombres = ({p["id"]: (p.get("nombre") or p.get("email") or "") for p in
                sb.select("perfiles", id=f"in.({','.join(ids)})", select="id,nombre,email")} if ids else {})

    decisiones: dict[str, DecisionLeida] = {}
    revisor: dict[str, str] = {}
    for f in filas:
        cod = f["codigo"]
        d = vig.get(cod)
        decisiones[cod] = DecisionLeida(cod, d["decision"] if d else "", (d.get("comentario") or "") if d else "",
                                        nombres.get(d["revisado_por"], "") if d else "", f["tipo"],
                                        f.get("descripcion") or "")
        if d:
            revisor[cod] = d["revisado_por"]

    nuevas: list[dict[str, Any]] = []
    if excel:
        meta = e.revision_meta or {}
        subido = _fh(meta.get("subido_en") or "1970-01-01T00:00:00+00:00")
        quien = meta.get("subido_por") or corrida.get("creada_por")
        for cod, x in excel.decisiones.items():
            if cod not in decisiones or not x.decision:
                continue
            d = vig.get(cod)
            if d and _fh(d["decidido_en"]) > subido:
                continue                   # se decidió en línea después de subir el Excel: gana la web
            actual = decisiones[cod]
            if (actual.decision, actual.comentario) == (x.decision, x.comentario):
                continue
            nueva = DecisionLeida(cod, x.decision, x.comentario, x.revisado_por, actual.tipo, actual.descripcion)
            decisiones[cod] = nueva
            if _validar(nueva) is None and quien:
                nuevas.append({"periodo_id": periodo["id"], "codigo": cod, "decision": x.decision,
                               "comentario": x.comentario or None, "revisado_por": quien, "corrida_id": prev["id"]})
                revisor[cod] = quien
            # Si no es válida, se usa solo en esta corrida («Decisión incompleta» con su aviso); no se guarda.

    propuestas = {f["codigo"]: (int(f["propuesta"]["fila"]), _fecha(f["propuesta"]["fecha"]))
                  for f in filas if f.get("propuesta")}
    correcciones = {int(c["fila"]): _fecha(c["fecha_nueva"])
                    for c in sb.select("correcciones_caja", periodo_id=f"eq.{periodo['id']}", select="fila,fecha_nueva")}
    if excel:
        for fila, fecha in excel.correcciones_previas.items():
            correcciones.setdefault(fila, fecha)
    historial = _historial_desde_json((prev.get("resumen") or {}).get("historial"))
    if not historial and excel:
        historial = excel.historial
    origen = "decisiones registradas en la app" + (f" + {excel.archivo}" if excel else "")
    anterior = RevisionAnterior(e.cliente, e.periodo, int(prev["numero"]), decisiones, historial, origen,
                                propuestas, correcciones)
    return Previo(anterior, nuevas, revisor)


def guardar(sb, periodo: dict, corrida: dict, previo: Previo, rep) -> None:
    """Después de una corrida exitosa: guarda las decisiones nuevas del Excel y las correcciones de caja aplicadas."""
    pid = periodo["id"]
    for n in previo.nuevas:
        sb.update("decisiones", {"periodo_id": f"eq.{pid}", "codigo": f"eq.{n['codigo']}", "vigente": "is.true"},
                  {"vigente": False})
        sb.insert("decisiones", [n])
    if rep.caja and rep.caja.cierre.correcciones:
        ya = {int(c["fila"]) for c in sb.select("correcciones_caja", periodo_id=f"eq.{pid}", select="fila")}
        cod_por_fila = {fila: cod for cod, (fila, _) in (previo.anterior.propuestas.items() if previo.anterior else [])}
        filas = []
        for fila, actual, nueva in rep.caja.cierre.correcciones:
            if fila in ya:
                continue
            cod = cod_por_fila.get(fila, "")
            quien = previo.revisor_por_codigo.get(cod) or corrida.get("creada_por")
            if not quien:
                continue
            filas.append({"periodo_id": pid, "codigo": cod or "excel", "fila": fila,
                          "fecha_actual": _fecha(actual).isoformat(), "fecha_nueva": _fecha(nueva).isoformat(),
                          "aceptada_por": quien})
        if filas:
            sb.insert("correcciones_caja", filas)
