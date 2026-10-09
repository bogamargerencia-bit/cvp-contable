"""Diagnóstico automático: las comprobaciones que un analista experto haría a mano sobre una corrida.

No cambia ninguna conciliación ni ajusta montos: solo explica en lenguaje claro qué pasó y qué hacer.
Lo usa revision.pendientes() para llenar las columnas «Explicación», «Qué hacer» y «Decisión sugerida».

Comprobaciones:
  1. Parejas mal registradas: un asiento «solo en libro» y un movimiento «solo en banco» del mismo sentido,
     ±3 días, cuyo monto en Bs. da una tasa coherente con la del día (p. ej. la Referencia tiene el número
     de factura en vez del monto en Bs.).
  2. Archivo del banco incompleto: saltos de la columna de saldo (dónde, cuánto y si explican el saldo final).
  3. Traslados entre cuentas propias: salida de un banco y entrada en otro (ya marcados por la naturaleza).
  4. Misma persona (cédula/RIF en la descripción) que ya aparece en asientos conciliados del libro
     (p. ej. «COMPRA DE 1000$») y pagos y cobros de la misma persona.
  5. Montos de diferencias de caja que aparecen (o no) en algún banco del mes; cobros idénticos el mismo día.
  6. Libro sin entradas en el mes; movimientos del banco posteriores al período.
"""
from __future__ import annotations

import datetime as dt
import re
import statistics
from collections import defaultdict
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from typing import TYPE_CHECKING, Optional

from .conciliacion import CONCILIADOS, EstadoPartida as EP
from .cuadre import TipoDiferencia
from .modelo import Movimiento
from .montos import CERO, formato_ve
from .naturaleza import (E_TRASLADO, OTROS, S_CARGOS, S_COMISION, S_ISLR, S_PAGO_MOVIL, S_TRANSF,
                         S_TRASLADO, E_TRANSF, MovClasificado)

if TYPE_CHECKING:
    from .proceso import ReporteCliente

NOMBRE = {"100_BANCO": "100% Banco", "BNC": "BNC", "BANPLUS": "Banplus", "PLAZA": "Plaza",
          "ACTIVO": "Activo", "MERCANTIL": "Mercantil",
          "VENEZOLANO": "Venezolano de Crédito", "BANCAMIGA": "Bancamiga"}
TOL_TASA = Decimal("0.03")          # ±3 % sobre la tasa del día para proponer una pareja
DIAS_PAREJA = 3
NO_EMPAREJAR = {S_COMISION, S_CARGOS, S_ISLR}   # cargos del banco: nunca son el pago de un asiento
CEDULA = re.compile(r"\b([VJEGP])0*(\d{6,9})\b")


def bs(d: Optional[Decimal]) -> str:
    return "—" if d is None else formato_ve(d)


def tx(t: Optional[Decimal]) -> str:
    """Tasa Bs./US$ para mostrar en un texto (no es un monto: se muestra con 2 decimales)."""
    return "—" if t is None else formato_ve(t.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def nb(b: str) -> str:
    return NOMBRE.get(b, b)


@dataclass
class Explicacion:
    texto: str                       # qué pasó
    que_hacer: str                   # acción concreta
    decision: str                    # decisión sugerida (Aceptar / Justificado / Corregido en el sistema)


@dataclass
class Pareja:
    banco: str
    asiento: int                     # índice en libro.asientos
    mov: int                         # índice en extracto.movimientos
    tasa: Decimal
    tasa_dia: Decimal


@dataclass
class Diagnostico:
    tasas: dict[dt.date, Decimal] = field(default_factory=dict)       # tasa implícita mediana por día
    parejas: dict[tuple[str, int], Pareja] = field(default_factory=dict)        # (banco, asiento) → pareja
    movs_en_pareja: set[tuple[str, int]] = field(default_factory=set)
    nota_mov: dict[tuple[str, int], str] = field(default_factory=dict)           # (banco, mov) → nota
    libro_sin_entradas: list[str] = field(default_factory=list)
    cuadre: dict[str, Explicacion] = field(default_factory=dict)                 # banco → explicación
    montos_banco: dict[Decimal, list[tuple[str, Movimiento]]] = field(default_factory=dict)

    def tasa_cercana(self, f: dt.date) -> Optional[Decimal]:
        if not self.tasas:
            return None
        dia = min(self.tasas, key=lambda d: (abs((d - f).days), d))
        return self.tasas[dia] if abs((dia - f).days) <= 7 else None


# ---------------------------------------------------------------- tasa del día (de lo ya conciliado)
def _tasas(rep: "ReporteCliente") -> dict[dt.date, Decimal]:
    por_dia: dict[dt.date, list[Decimal]] = defaultdict(list)
    for b in rep.bancos:
        rc = rep.conciliaciones[b]
        for j, a in enumerate(rc.libro.asientos):
            p = rc.estado_asiento.get(j)
            if p and p.estado in CONCILIADOS and a.tasa_implicita and len(p.asientos) == 1:
                por_dia[a.fecha].append(a.tasa_implicita)
    return {d: Decimal(statistics.median(v)).quantize(Decimal("0.0001")) for d, v in por_dia.items() if v}


# ---------------------------------------------------------------- 1. parejas mal registradas
def _parejas(rep: "ReporteCliente", dg: Diagnostico) -> None:
    for b in rep.bancos:
        rc = rep.conciliaciones[b]
        movs = rc.extracto.movimientos
        nat = {x.indice: x.naturaleza for x in rep.clasificados[b]}
        libres = [i for i, p in rc.estado_mov.items()
                  if p.estado is EP.SOLO_BANCO and nat.get(i) not in NO_EMPAREJAR]
        for j, a in enumerate(rc.libro.asientos):
            p = rc.estado_asiento.get(j)
            if not p or p.estado is not EP.SOLO_LIBRO or not a.monto_usd:
                continue
            cands = []
            for i in libres:
                m = movs[i]
                if (b, i) in dg.movs_en_pareja or abs((m.fecha_contable - a.fecha).days) > DIAS_PAREJA:
                    continue
                monto = m.debito if a.es_salida else m.credito
                if not monto:
                    continue
                tasa = (monto / a.monto_usd).quantize(Decimal("0.0001"))
                ref = dg.tasa_cercana(a.fecha)
                if ref and abs(tasa - ref) <= ref * TOL_TASA:
                    cands.append((abs(tasa - ref), abs((m.fecha_contable - a.fecha).days), i, tasa, ref))
            cands.sort()
            # Solo se propone si hay un mejor candidato claro (si dos empatan, no se adivina).
            if cands and (len(cands) == 1 or cands[0][:2] < cands[1][:2]):
                _, _, i, tasa, ref = cands[0]
                dg.parejas[(b, j)] = Pareja(b, j, i, tasa, ref)
                dg.movs_en_pareja.add((b, i))


# ---------------------------------------------------------------- 2. archivo del banco incompleto
def _cuadre(rep: "ReporteCliente", dg: Diagnostico) -> None:
    for b in rep.bancos:
        c = rep.cuadres[b]
        saltos = [d for d in c.diferencias if d.tipo is TipoDiferencia.SALDO_LINEA and d.diferencia is not None]
        final = next((d for d in c.diferencias if d.tipo is TipoDiferencia.NUEVO_SALDO), None)
        if not c.diferencias:
            continue
        movs = c.extracto.movimientos
        partes = []
        neto = CERO
        for d in saltos:
            salto = -d.diferencia                         # lo que el saldo del banco «salta» sin línea
            neto += salto
            m = movs[d.linea - 1] if d.linea else None
            donde = f"{m.fecha_contable:%d/%m} «{m.descripcion}» ref {m.referencia}" if m else f"movimiento {d.linea}"
            partes.append(f"en {donde} el saldo del banco {'sube' if salto > 0 else 'baja'} {bs(abs(salto))} "
                          "sin ninguna línea que lo explique")
        if saltos:
            texto = ("El archivo del banco no cuadra por sí mismo: " + "; ".join(partes) + ".")
            if final is not None and final.diferencia is not None and -final.diferencia == neto:
                texto += (f" El efecto neto ({bs(neto)}) es exactamente la diferencia entre el saldo final que "
                          f"informa el banco ({bs(final.esperado)}) y el que da el detalle ({bs(final.obtenido)}).")
            texto += " Lo más probable es que al archivo le falten movimientos."
            dg.cuadre[b] = Explicacion(
                texto, "Pedir al banco el estado de cuenta oficial (PDF) o volver a descargar el archivo, buscar "
                       "esos movimientos y reemplazar el estado de cuenta en la app.", "Corregido en el sistema")
        else:
            dg.cuadre[b] = Explicacion(
                "El detalle del estado de cuenta no coincide con los totales o saldos que informa el propio banco.",
                "Revisar el archivo del banco (que esté completo y sea del período) y reemplazarlo si hace falta.",
                "Corregido en el sistema")


# ---------------------------------------------------------------- 3 y 4. traslados y misma persona
def _cedula(texto: str) -> Optional[str]:
    m = CEDULA.search(texto or "")
    return f"{m.group(1)}{int(m.group(2))}" if m else None


def _personas(rep: "ReporteCliente", dg: Diagnostico) -> None:
    conocidos: dict[str, list[str]] = defaultdict(list)          # cédula → asientos conciliados del libro
    sueltos: dict[str, list[tuple[str, MovClasificado]]] = defaultdict(list)
    for b in rep.bancos:
        rc = rep.conciliaciones[b]
        for x in rep.clasificados[b]:
            ced = _cedula(x.mov.descripcion)
            if not ced:
                continue
            p = rc.estado_mov.get(x.indice)
            if p and p.estado in CONCILIADOS and p.asientos:
                a = rc.libro.asientos[p.asientos[0]]
                conocidos[ced].append(f"«{a.descripcion}» ({x.mov.fecha_contable:%d/%m}, Bs. {bs(x.mov.debito or x.mov.credito)})")
            elif p and p.estado is EP.SOLO_BANCO:
                sueltos[ced].append((b, x))
    for ced, lst in sueltos.items():
        salidas = [(b, x) for b, x in lst if x.mov.debito]
        entradas = [(b, x) for b, x in lst if x.mov.credito]
        for b, x in lst:
            notas = []
            if conocidos.get(ced):
                notas.append(f"A esta misma persona ({ced}) el libro ya le registró " + "; ".join(conocidos[ced][:2])
                             + ": probablemente es la misma operación (registrar igual).")
            if salidas and entradas:
                otros = [y for _, y in (entradas if x.mov.debito else salidas)]
                notas.append(f"Con la misma persona ({ced}) hay también " +
                             ", ".join(f"{'un cobro' if y.mov.credito else 'un pago'} del {y.mov.fecha_contable:%d/%m} "
                                       f"por Bs. {bs(y.mov.credito or y.mov.debito)}" for y in otros[:3]) +
                             ": ¿préstamo, devolución o pago parcial?")
            if notas:
                dg.nota_mov[(b, x.indice)] = " ".join(notas)
    for b in rep.bancos:
        for x in rep.clasificados[b]:
            if x.naturaleza in (S_TRASLADO, E_TRASLADO) and x.contraparte:
                otro = x.contraparte.split()[0]
                dg.nota_mov.setdefault((b, x.indice), (
                    f"Traslado entre cuentas propias: {'sale hacia' if x.mov.debito else 'viene de'} {nb(otro)} "
                    f"({x.contraparte.split(' ', 1)[1]}). Debe registrarse en los dos libros: salida en uno y "
                    "entrada en el otro."))


# ---------------------------------------------------------------- 6. libro sin entradas
def _libro_sin_entradas(rep: "ReporteCliente", dg: Diagnostico) -> None:
    for b in rep.bancos:
        lib = rep.libros[b]
        entradas_banco = sum((m.credito for m in rep.conciliaciones[b].extracto.movimientos), CERO)
        if lib.asientos and not any(a.debito_usd for a in lib.asientos) and entradas_banco > 0:
            dg.libro_sin_entradas.append(b)


def diagnosticar(rep: "ReporteCliente") -> Diagnostico:
    dg = Diagnostico(tasas=_tasas(rep))
    for b in rep.bancos:
        for m in rep.conciliaciones[b].extracto.movimientos:
            for v in (m.debito, m.credito):
                if v:
                    dg.montos_banco.setdefault(v, []).append((b, m))
    _parejas(rep, dg)
    _cuadre(rep, dg)
    _personas(rep, dg)
    _libro_sin_entradas(rep, dg)
    return dg


# ---------------------------------------------------------------- textos por tipo de partida
def explicar_pareja(rep: "ReporteCliente", pr: Pareja) -> Explicacion:
    rc = rep.conciliaciones[pr.banco]
    a = rc.libro.asientos[pr.asiento]
    m = rc.extracto.movimientos[pr.mov]
    monto_banco = m.debito or m.credito
    ref_txt = a.referencia or "—"
    pista = ""
    if a.monto_bs is not None and re.search(rf"\b{re.escape(str(int(a.monto_bs)))}\b", a.descripcion):
        pista = f" La Referencia del libro ({ref_txt}) es el número de factura de la descripción, no el monto en Bs."
    if a.monto_bs is not None and abs(monto_banco - a.monto_bs) <= monto_banco * Decimal("0.05"):
        dif = monto_banco - a.monto_bs
        return Explicacion(
            f"El libro registra «{a.descripcion}» por Bs. {bs(a.monto_bs)} (US$ {bs(a.monto_usd)}) y el banco tiene "
            f"el {m.fecha_contable:%d/%m} «{m.descripcion}» ref {m.referencia} por Bs. {bs(monto_banco)}: casi el "
            f"mismo monto (diferencia Bs. {bs(dif)}), y la tasa ({tx(pr.tasa)}) es la de esos días ({tx(pr.tasa_dia)}). "
            "Probablemente es el mismo pago con el monto en Bs. anotado distinto.",
            f"Verificar el comprobante: si el banco tiene razón, corregir la Referencia del asiento a {bs(monto_banco)} "
            "en el sistema; si la diferencia es real (comisión, redondeo), justificarla.", "Corregido en el sistema")
    return Explicacion(
        f"El libro registra «{a.descripcion}» por US$ {bs(a.monto_usd)} con Bs. {bs(a.monto_bs)} en la Referencia, "
        f"y el banco tiene el {m.fecha_contable:%d/%m} «{m.descripcion}» ref {m.referencia} por Bs. {bs(monto_banco)}. "
        f"Con ese monto la tasa sería {tx(pr.tasa)}, igual a la de esos días ({tx(pr.tasa_dia)}): "
        f"es el mismo pago con el monto en Bs. mal registrado.{pista}",
        f"Corregir en el sistema la Referencia (monto en Bs.) de este asiento a {bs(monto_banco)} y volver a "
        "exportar el libro.", "Corregido en el sistema")


def explicar_otro_banco(det: str) -> Explicacion:
    m = re.search(r"El movimiento está en (\S+): (.*)", det)
    donde = f"{nb(m.group(1))}: {m.group(2)}" if m else det
    return Explicacion(
        f"Este asiento está en este libro, pero el movimiento salió de otro banco ({donde}).",
        "Mover el asiento al libro del banco correcto en el sistema.", "Corregido en el sistema")


def explicar_solo_libro(rep: "ReporteCliente", banco: str, j: int, dg: Diagnostico) -> Explicacion:
    a = rep.conciliaciones[banco].libro.asientos[j]
    ref = dg.tasa_cercana(a.fecha)
    if a.monto_bs is not None and a.monto_usd and ref:
        tasa = a.monto_bs / a.monto_usd
        if abs(tasa - ref) > ref * Decimal("0.2"):
            return Explicacion(
                f"El asiento tiene Bs. {bs(a.monto_bs)} en la Referencia para US$ {bs(a.monto_usd)}: una tasa de "
                f"{tx(tasa)}, muy lejos de la del día ({tx(ref)}). El monto en "
                "Bs. está mal registrado y por eso no se encuentra en el banco.",
                f"Buscar el pago en el banco por unos Bs. {bs((a.monto_usd * ref).quantize(Decimal('0.01')))} y corregir la "
                "Referencia en el sistema.", "Corregido en el sistema")
    return Explicacion(
        f"El libro registra este {'pago' if a.es_salida else 'cobro'} el {a.fecha:%d/%m}, pero no aparece en el "
        "estado de cuenta del banco con ese monto ni en ±5 días.",
        "Verificar si el movimiento está en otro banco, en el mes siguiente (en tránsito) o si el asiento sobra.",
        "Justificado")


def explicar_caja_dia(rep: "ReporteCliente", dg: Diagnostico, l) -> Explicacion:
    """Diferencia entre la caja de un día y lo abonado en el banco ese día (pago móvil por total diario)."""
    caja = l.monto
    banco_t = sum((rep.conciliaciones[b].extracto.movimientos[i].credito for b, i in l.movs), CERO)
    dif = banco_t - caja
    fechas = ", ".join(f"{i.fecha:%d/%m}" for i in l.items)
    base = f"La caja del {fechas} registra Bs. {bs(caja)} de {l.medio.lower()}; el banco abonó Bs. {bs(banco_t)} ese día."
    if abs(dif) < 1:
        return Explicacion(f"{base} Diferencia de céntimos ({bs(dif)}): casi seguro un redondeo al anotar la caja.",
                           "Nada que corregir.", "Aceptar")
    if dif > 0:
        m = re.search(r"Posibles cobros no registrados en caja: (.*)\.", l.nota)
        if m:
            refs = re.findall(r"ref (\S+?)\)", m.group(1))
            extra = ""
            movs_dia = [rep.conciliaciones[b].extracto.movimientos[i] for b, i in l.movs]
            for ref in refs:
                mv = next((x for x in movs_dia if x.referencia == ref), None)
                if mv and sum(1 for x in movs_dia if x.credito == mv.credito) > 1:
                    extra = (f" Ese día hay otro cobro idéntico de Bs. {bs(mv.credito)}: ¿se cobró dos veces al "
                             "mismo cliente?")
            return Explicacion(
                f"{base} El banco tiene Bs. {bs(dif)} más: el cobro {m.group(1)} no está anotado en la caja.{extra}",
                "Agregar ese cobro a la caja del día (o justificar si no es una venta).",
                "Justificado")
        return Explicacion(f"{base} El banco tiene Bs. {bs(dif)} más que la caja y ningún cobro suelto lo explica.",
                           "Revisar los cobros del día en el banco contra la caja.", "Justificado")
    falta = -dif
    otros = [(b, m) for b, m in dg.montos_banco.get(falta, [])]
    if otros:
        donde = "; ".join(f"{nb(b)} {m.fecha_contable:%d/%m} «{m.descripcion}» ref {m.referencia}" for b, m in otros[:3])
        return Explicacion(f"{base} La caja tiene Bs. {bs(falta)} más; ese monto aparece en: {donde}.",
                           "Verificar si ese cobro entró por otro banco u otro día y corregir la caja.", "Justificado")
    return Explicacion(
        f"{base} La caja tiene Bs. {bs(falta)} más que el banco, y ese monto no aparece en ningún banco del mes.",
        "Revisar si fue un pago móvil rechazado o anotado de más en la caja; corregir la caja o justificar.",
        "Justificado")


QUE_HACER_GRUPO = {
    S_COMISION: ("Comisiones que cobró el banco y no están en el libro.",
                 "Registrar en el sistema el asiento de comisiones bancarias del mes por el total."),
    S_CARGOS: ("Cargos del banco (mantenimiento, cuotas, servicios) que no están en el libro.",
               "Registrar en el sistema el asiento de gastos bancarios del mes por el total."),
    S_ISLR: ("Retenciones de ISLR que hizo el banco y no están en el libro.",
             "Registrar en el sistema la retención de ISLR del mes."),
}


def explicar_mov_suelto(rep: "ReporteCliente", banco: str, x: MovClasificado, dg: Diagnostico) -> Explicacion:
    m = x.mov
    hasta = rep.conciliaciones[banco].extracto.hasta
    nota = dg.nota_mov.get((banco, x.indice), "")
    if m.fecha_contable > hasta:
        return Explicacion(f"Movimiento del {m.fecha_contable:%d/%m/%Y}, posterior al período; el banco lo incluyó "
                           "en el archivo.", "Nada que hacer en este mes; se registra en el mes siguiente.", "Justificado")
    sentido = "salida" if m.debito else "entrada"
    texto = (f"{sentido.capitalize()} del banco del {m.fecha_contable:%d/%m} «{m.descripcion}» ref {m.referencia} por "
             f"Bs. {bs(m.debito or m.credito)} que no tiene asiento en el libro.")
    desc = (m.descripcion or "").lower()
    if "regulariz" in desc:
        texto += " Es un débito del banco que reversa cobros de pago móvil."
        hacer = "Averiguar con el banco a qué cobros corresponde y registrar el reverso."
    elif x.naturaleza in (S_TRASLADO, E_TRASLADO):
        hacer = "Registrar el traslado en el sistema en los dos libros (salida en uno, entrada en el otro)."
    elif x.naturaleza in (S_TRANSF, S_PAGO_MOVIL) and not _cedula(m.descripcion) and not nota:
        texto += " El banco no informa a quién se le pagó."
        hacer = "Identificar el beneficiario (comprobante en la banca en línea) y registrar el asiento."
    elif m.credito and "interes" in desc.replace("é", "e"):
        hacer = "Registrar el ingreso por intereses."
    else:
        hacer = "Registrar el asiento en el sistema."
    if nota:
        texto += " " + nota
    return Explicacion(texto, hacer, "Corregido en el sistema")


def explicar_libro_sin_entradas(rep: "ReporteCliente", banco: str) -> Explicacion:
    movs = rep.conciliaciones[banco].extracto.movimientos
    ent = sum((m.credito for m in movs), CERO)
    return Explicacion(
        f"El libro de {nb(banco)} no tiene ninguna entrada (débito) en el mes, pero el banco recibió Bs. {bs(ent)}. "
        "Lo normal es que falte el asiento de ventas / cobros del mes.",
        "Registrar en el sistema los asientos de ventas (cobros POS, pago móvil, transferencias) y volver a "
        "exportar el libro.", "Corregido en el sistema")


# Textos por defecto, por tipo de partida, cuando no hay un diagnóstico más específico.
GENERICO: dict[str, tuple[str, str, str]] = {
    "Saldo del libro inconsistente": (
        "El saldo corrido del export del sistema no coincide con sus propios débitos y créditos: falta o sobra "
        "una línea, o se exportó con un filtro.",
        "Volver a exportar el libro completo del período y reemplazarlo en la app.", "Corregido en el sistema"),
    "Sentido invertido": (
        "El libro y el banco tienen el mismo monto, pero en sentido contrario (uno lo tiene como entrada y el otro "
        "como salida).",
        "Corregir el asiento en el sistema (débito ↔ crédito).", "Corregido en el sistema"),
    "Asiento resumen sin conciliar": (
        "Asiento que agrupa varias operaciones y no trae el monto en Bs. en la Referencia, por eso no se puede "
        "comparar con el banco.",
        "Justificar indicando qué agrupa, o colocar el monto en Bs. en la Referencia.", "Justificado"),
    "Asiento resumen incompleto": (
        "El asiento resumen de ventas no cubre todos los días del cierre de caja.",
        "Completar el asiento en el sistema con los días que faltan.", "Corregido en el sistema"),
    "Caja: corrección de fecha propuesta": (
        "La fecha de esta fila del cierre de caja no coincide con el abono del banco; la app propone cambiarla.",
        "Si la fecha propuesta es correcta, marcar «Aceptar»: la app la corrige sola en la próxima corrida.",
        "Aceptar"),
    "Cierre de caja con errores": (
        "El archivo de cierre de caja tiene un error (de lectura o de sumas).",
        "Corregir el cierre de caja y volver a subirlo.", "Corregido en el sistema"),
    "Tarjetas: por abonar en el mes siguiente": (
        "Ventas con tarjeta de los últimos días del mes que el banco abona en el mes siguiente. Es normal.",
        "Verificar en el estado de cuenta del mes siguiente que se abonen por ese total.", "Justificado"),
    "Caja: Posible error de transcripción": (
        "La caja anota un monto y en el banco hay uno muy parecido ese día: probable error al transcribir.",
        "Si el monto del banco es el correcto, «Aceptar»; si no, corregir la caja.", "Aceptar"),
    "Caja: No encontrado en el banco": (
        "Cobro anotado en la caja que no aparece en el banco del mes.",
        "Verificar si entró por otro banco o fue rechazado; corregir la caja o justificar.", "Justificado"),
    "Caja: En tránsito (se abona después del período)": (
        "Cobro de los últimos días que el banco abona después del cierre del mes.",
        "Verificar en el estado de cuenta del mes siguiente.", "Justificado"),
    "Cobro sin registro en caja": (
        "El banco recibió este cobro y no está en el cierre de caja.",
        "Ubicar la venta y agregarla a la caja, o justificar si no es una venta.", "Justificado"),
    "Cobros sin día de caja": (
        "Cobros por pago móvil de un día que no tiene cierre de caja.",
        "Verificar si falta el cierre de ese día; si son ventas del mes anterior, justificar.", "Justificado"),
    "Abono POS de ventas del mes anterior": (
        "Abonos de tarjeta de los primeros días del mes que corresponden a ventas del mes anterior (por eso no "
        "tienen día en el cierre de caja de este mes).",
        "Comprobar que el total coincida con lo «por abonar en el mes siguiente» del mes anterior y justificar.",
        "Justificado"),
    "Lote sin día de caja": (
        "Abonos de tarjeta de un día que no tiene cierre de caja.",
        "Si son ventas del mes anterior, comprobar contra lo «por abonar» de ese mes y justificar.", "Justificado"),
    "Venta de divisas: el banco la registra a otra tasa": (
        "El banco registró la venta de divisas a una tasa distinta de la que usa el libro.",
        "Indicar la tasa usada o corregir el asiento.", "Justificado"),
}
GENERICO["Kardex: aviso de lectura"] = (
    "El Kardex tiene una fila escrita distinto de las demás (p. ej. la fecha como texto o en otra columna). "
    "La app la leyó igual; revisa que la fecha que tomó sea la correcta.",
    "Si la fecha leída es correcta, «Aceptar». Para el próximo mes, escribir la fecha como fecha en su columna.",
    "Aceptar")
GENERICO["Kardex con errores"] = (
    "El Kardex no se pudo leer completo o una de sus secciones no suma su propio total: hay movimientos que la "
    "app no está viendo.",
    "Corregir esa fila del Kardex (fecha y monto en sus columnas) y volver a subirlo.", "Corregido en el sistema")
GENERICO_DIVISAS = ("Diferencia entre el libro de divisas, el cierre de caja y el Kardex.",
                    "Revisar cuál de los tres está mal y corregirlo (o justificar).", "Justificado")
GENERICO_OTRO = ("Partida que la conciliación no pudo cerrar.", "Revisar el detalle técnico.", "Justificado")


def generico(tipo: str) -> Explicacion:
    t = GENERICO.get(tipo) or (GENERICO_DIVISAS if tipo.startswith("Divisas") else GENERICO_OTRO)
    return Explicacion(*t)


def explicar_diferencia_monto(dif: Optional[Decimal]) -> Explicacion:
    if dif is not None and abs(dif) < 1:
        return Explicacion(f"Mismo movimiento en libro y banco con una diferencia de céntimos (Bs. {bs(dif)}).",
                           "Nada que corregir.", "Aceptar")
    return Explicacion(f"Libro y banco tienen el mismo movimiento con montos distintos (diferencia Bs. {bs(dif)}).",
                       "Corregir el monto en Bs. (Referencia) del asiento en el sistema, o justificar la diferencia.",
                       "Corregido en el sistema")


def explicar_grupo(nat: str, estado: str, movs: list[Movimiento]) -> Explicacion:
    lista = "; ".join(f"{m.fecha_contable:%d/%m} ref {m.referencia or '—'} Bs. {bs(m.debito or m.credito)}"
                      for m in movs[:15])
    if len(movs) > 15:
        lista += f"; y {len(movs) - 15} más"
    if estado == EP.CAJA_SIN_LIBRO.value:
        return Explicacion(f"{len(movs)} cobros que sí están en el cierre de caja pero no en el libro del sistema "
                           f"(falta el asiento de ventas). Movimientos: {lista}.",
                           "Registrar el asiento de ventas / cobros del período en el sistema.",
                           "Corregido en el sistema")
    if nat in QUE_HACER_GRUPO:
        t, h = QUE_HACER_GRUPO[nat]
        return Explicacion(f"{t} Movimientos: {lista}.", h, "Corregido en el sistema")
    return Explicacion(f"{len(movs)} movimientos de «{nat}» que el banco tiene y el libro no. Movimientos: {lista}.",
                       "Registrar los asientos en el sistema (o justificar indicando dónde están registrados).",
                       "Corregido en el sistema")


def explicar_divisa_fecha(cuenta: str, a, k, lado: str) -> Explicacion:
    """Mismo monto en el libro de divisas y en el Kardex, pero con fechas a más de ±3 días."""
    dias = abs((a.fecha - k.fecha).days)
    texto = (f"Es la misma operación en los dos registros, con fechas distintas: el libro de {cuenta} tiene el "
             f"{a.fecha:%d/%m} «{a.descripcion}» por US$ {bs(abs(a.debito_usd - a.credito_usd))} y el Kardex (fila "
             f"{k.fila}) tiene el {k.fecha:%d/%m} «{k.descripcion}» por US$ {bs(abs(k.monto))}: {dias} días de diferencia. "
             "La app solo los empareja sola si están a ±3 días.")
    hacer = ("Verificar la fecha real de la operación y corregir la fecha en el libro o en el Kardex. Si las dos "
             "fechas son correctas, «Justificado» indicando la diferencia. Decide igual esta partida y la del "
             + ("Kardex" if lado == "libro" else "libro") + ".")
    return Explicacion(texto, hacer, "Justificado")


def explicar_venta_aparte(cuenta: str, k, ventas: Decimal, kardex_dia: Decimal) -> Explicacion:
    """Parte de las ventas del día que el Kardex anotó en una fila aparte (no en la fila de ventas)."""
    return Explicacion(
        f"Es venta del día, anotada en otra fila del Kardex. El cierre de caja tiene US$ {bs(ventas)} de ventas en "
        f"{cuenta} el {k.fecha:%d/%m}; la fila de ventas del Kardex tiene US$ {bs(kardex_dia)} (faltan "
        f"US$ {bs(ventas - kardex_dia)}), y el Kardex anotó esos US$ {bs(k.monto)} aparte, en la fila {k.fila} "
        f"(«{k.descripcion}»). Las dos diferencias se compensan exactamente.",
        "Nada que corregir en el libro. Si se quiere el Kardex ordenado, sumar esa fila a la de ventas del día.",
        "Aceptar")


def explicar_por_conciliar(cat) -> Explicacion:
    """Total del mes de comisiones / cargos / ISLR POS de un banco, para comparar con el asiento del sistema."""
    n = len(cat.movimientos)
    tipos = "; ".join(f"{t.nombre}: {len(t.movimientos)} mov., Bs. {bs(abs(t.total))}" for t in cat.tipos[:12])
    if len(cat.tipos) > 12:
        tipos += f"; y {len(cat.tipos) - 12} tipos más"
    return Explicacion(
        f"Total del mes en {nb(cat.banco)}: {n} movimientos por Bs. {bs(abs(cat.total))}. Por tipo: {tipos}. "
        "Estos movimientos no se concilian uno por uno: se comparan en total con el asiento del mes del sistema. "
        "El detalle está en la hoja «Comisiones e ISLR» del Excel.",
        f"Comparar Bs. {bs(abs(cat.total))} con el asiento del mes en el sistema. Si coincide, «Aceptar». Si no, "
        "corregir el asiento y luego «Aceptar», o «Justificado» explicando la diferencia. No usar «Corregido en el "
        "sistema»: esta partida aparece en cada corrida porque se concilia a mano.",
        "Aceptar")


ASIENTO_APARTE = re.compile(r"COMISI|ISLR|RETENC|GASTOS? BANC|CARGOS? BANC", re.I)


def explicar_asiento_aparte(a) -> Explicacion:
    """Asiento de comisiones / cargos / ISLR del libro: no se concilia con movimientos del banco."""
    return Explicacion(
        f"Asiento de comisiones, cargos o retenciones del mes («{a.descripcion}», US$ {bs(a.monto_usd)}). Estos "
        "conceptos no se concilian movimiento por movimiento: se comparan en total con la hoja «Comisiones e ISLR».",
        "Comparar el asiento con el total del banco en esa hoja (y en la partida «Por conciliar en el sistema»). "
        "Si coincide, «Aceptar»; si no, corregir el asiento.", "Aceptar")


VENTAS_MEDIO = [
    (re.compile(r"PAGO\s*M[OÓ]VIL|P2C", re.I), "pago móvil", {"Cobros por pago móvil / P2C"}),
    (re.compile(r"PUNTO|\bPOS\b|D[EÉ]BITO|CR[EÉ]DITO", re.I), "tarjetas (POS)",
     {"Cobros POS – tarjeta de débito", "Cobros POS – tarjeta de crédito"}),
]
ES_VENTAS = re.compile(r"\bVTAS\b|\bVENTAS?\b|INGRESO", re.I)


def explicar_total_ventas(rep: "ReporteCliente", banco: str, j: int) -> Optional[Explicacion]:
    """Asiento de ventas del mes con el total en Bs. que no casó con el total de cobros del banco."""
    rc = rep.conciliaciones[banco]
    a = rc.libro.asientos[j]
    texto_a = f"{a.referencia} {a.descripcion}"
    if a.monto_bs is None or a.es_salida or not ES_VENTAS.search(texto_a):
        return None
    medio = next(((n, nats) for rx, n, nats in VENTAS_MEDIO if rx.search(texto_a)), None)
    if medio is None:
        return None
    nombre, nats = medio
    cobros = [x for x in rep.clasificados[banco] if x.naturaleza in nats and x.mov.credito]
    total = sum((x.mov.credito for x in cobros), CERO)
    otros = [x for x in cobros if (p := rc.estado_mov.get(x.indice)) and p.estado in CONCILIADOS
             and p.estado is not EP.CONCILIADO_TOTAL and any(k != j for k in p.asientos)]
    otros_t = sum((x.mov.credito for x in otros), CERO)
    libres_t = total - otros_t
    texto = (f"El libro registra «{a.descripcion}» por Bs. {bs(a.monto_bs)}. En el banco, los cobros por {nombre} del "
             f"mes suman Bs. {bs(total)} ({len(cobros)} movimientos)")
    if otros:
        det = "; ".join(f"{x.mov.fecha_contable:%d/%m} ref {x.mov.referencia or '—'} Bs. {bs(x.mov.credito)}"
                        for x in otros[:5])
        texto += (f"; de ellos, {len(otros)} ya están conciliados con otro asiento del libro ({det}), así que para "
                  f"este asiento quedan Bs. {bs(libres_t)}")
    texto += f". Diferencia del asiento: Bs. {bs(a.monto_bs - libres_t)}."
    if otros and a.monto_bs == total:
        texto += (" El asiento usa el total completo del banco: incluye cobros que ya tienen su propio asiento "
                  "(quedarían registrados dos veces).")
        hacer = (f"Si esos cobros sí tienen su propio asiento, poner Bs. {bs(libres_t)} en la Referencia. Si no "
                 "corresponden a ese otro asiento, corregir ese asiento.")
    else:
        hacer = (f"Revisar el monto en la Referencia: para conciliar debe ser Bs. {bs(libres_t)} (suma exacta de los "
                 f"cobros por {nombre} del banco sin asiento propio). Si la diferencia es real, justificarla.")
    return Explicacion(texto, hacer, "Corregido en el sistema")
