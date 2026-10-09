"""Clasificación de movimientos bancarios por naturaleza.

Reglas por banco: (patrón regex sobre "descripcion | detalle | nota", dirección, naturaleza).
Se usa la primera regla que coincide. Lo que no coincide queda en "Otros (sin clasificar)"
para que se vea y se agregue una regla; nunca se fuerza.

Además, `marcar_traslados` detecta traslados entre cuentas propias del mismo cliente:
un débito en un banco y un crédito por el mismo monto en otro, con fechas a ±2 días.
"""
from __future__ import annotations

import datetime as dt
import re
from collections import OrderedDict
from dataclasses import dataclass
from decimal import Decimal
from typing import Iterable, Optional

from .modelo import Extracto, Movimiento

# --- Naturalezas (el orden es el del reporte) --------------------------------
E_POS_DEB = "Cobros POS – tarjeta de débito"
E_POS_CRE = "Cobros POS – tarjeta de crédito"
E_PAGO_MOVIL = "Cobros por pago móvil / P2C"
E_TRANSF = "Transferencias recibidas"
E_TRASLADO = "Traslados desde cuentas propias"
E_REVERSO = "Reversos y devoluciones recibidos"
S_NOMINA = "Pagos de nómina"
S_TRANSF = "Pagos por transferencia / crédito inmediato"
S_PAGO_MOVIL = "Pagos por pago móvil"
S_POS = "Compras con tarjeta (POS)"
S_TRASLADO = "Traslados a cuentas propias"
S_COMISION = "Comisiones bancarias"
S_ISLR = "Retención ISLR en cobros POS"
S_IMPUESTOS = "Pagos de impuestos (SENIAT)"
S_CARGOS = "Cargos bancarios (mantenimiento, estado de cuenta, SMS)"
S_REVERSO = "Reversos y rechazos (débitos)"
OTROS = "Otros (sin clasificar)"

ORDEN = [E_POS_DEB, E_POS_CRE, E_PAGO_MOVIL, E_TRANSF, E_TRASLADO, E_REVERSO,
         S_NOMINA, S_TRANSF, S_PAGO_MOVIL, S_POS, S_TRASLADO, S_COMISION, S_ISLR, S_IMPUESTOS,
         S_CARGOS, S_REVERSO, OTROS]
ENTRADAS = {E_POS_DEB, E_POS_CRE, E_PAGO_MOVIL, E_TRANSF, E_TRASLADO, E_REVERSO}

C, D = "C", "D"  # crédito (entrada) / débito (salida)

REGLAS: dict[str, list[tuple[str, str, str]]] = {
    "PLAZA": [
        (r"^POS (MAE|ELE)", C, E_POS_DEB),
        (r"^POS CRE", C, E_POS_CRE),
        (r"^DOM POS|^COM TRF|COM\.P2P", D, S_COMISION),
        (r"CARGO POR MANTENIMIENTO|TRASPASO FONDOS CUOTA", D, S_CARGOS),
        (r"^TDY (ENVIO|PAGO)", D, S_PAGO_MOVIL),
        (r"N[OÓ]MINA", D, S_NOMINA),
        (r"^TRF |^PAGO ", D, S_TRANSF),
        (r"^TDY|PAGO MOVIL", C, E_PAGO_MOVIL),
        (r"^TRF ", C, E_TRANSF),
    ],
    "100_BANCO": [
        (r"^Com\.", D, S_COMISION),
        (r"Mantenimiento POS|Emisi[oó]n de Estados|Cuota de Mantenimiento|Mensajeria SMS", D, S_CARGOS),
        (r"PagoMovil|Pago M[oó]vil", C, E_PAGO_MOVIL),
        (r"Credito Inmediato (Recibido|Rechazado)", D, S_REVERSO),
        (r"Credito Inmediato", C, E_TRANSF),
        (r"Credito Inmediato", D, S_TRANSF),
        (r"COMPRA POS", D, S_POS),
    ],
    "BNC": [
        (r"Tarjeta Deb", C, E_POS_DEB),
        (r"Tarjeta Cre", C, E_POS_CRE),
        (r"I\.S\.l\.R|ISLR", D, S_ISLR),
        (r"Mantenimiento Cuenta", D, S_CARGOS),
        (r"Comisi[oó]n|Cobra Comision|Agregadores POS", D, S_COMISION),
        (r"Dev/Rev", C, E_REVERSO),
        (r"NOMINA", D, S_NOMINA),
        (r"Cr[eé]dito Inmediato Emitido|Tranf\. entre Ctas", D, S_TRANSF),
        (r"Credito Inmediato Recibido|Tranf\. entre Ctas", C, E_TRANSF),
        (r"Cargo Pago Movil", D, S_PAGO_MOVIL),
        (r"Abono Pago Movil", C, E_PAGO_MOVIL),
        (r"Compra de POS", D, S_POS),
    ],
    "BANPLUS": [
        (r"Liquidacion Ventas (Maestro|Electron)", C, E_POS_DEB),
        (r"Liquidacion Ventas TDC", C, E_POS_CRE),
        (r"Dev\. Transferencia|NC Reverso Comision", C, E_REVERSO),
        (r"Impuestos Seniat", D, S_IMPUESTOS),
        (r"^Comision|Atencion Telefonica|Servicio de Atencion|Reembolso de costos POS", D, S_COMISION),
        (r"Emision|Mantenimiento de Cuenta|Servicio SMS", D, S_CARGOS),
        (r"Pago Plus Comercios", C, E_PAGO_MOVIL),
        (r"NC Transf", C, E_TRANSF),
        (r"ND Transf|Transf\. Internet", D, S_TRANSF),
        (r"Pago Plus Otros Bancos", D, S_PAGO_MOVIL),
        (r"Compra POS", D, S_POS),
    ],
    "VENEZOLANO": [
        (r"^POS DEB", C, E_POS_DEB),
        (r"^POS CREDITO", C, E_POS_CRE),
        (r"^REINT", C, E_REVERSO),
        (r"PAGO MOVIL", C, E_PAGO_MOVIL),
        (r"CREDITO INMEDIATO ABONO", C, E_TRANSF),
        (r"^COMISION|COSTO DE OP\.PUNTO", D, S_COMISION),
        (r"GENER\.PROC\.DE EDO|CUOTA DE MANTENIM", D, S_CARGOS),
        (r"RETENCION I\.S\.L\.R", D, S_ISLR),
        (r"^CRED\.INM(ED)?\.ENV", D, S_TRANSF),     # a terceros o a cuenta propia (MISMO TIT): ver marcar_traslados
    ],
    "MERCANTIL": [
        (r"CREDITO INMEDIATO|TRANSFERENCIA RECIBIDA", C, E_TRANSF),
        (r"^COMISION", D, S_COMISION),                       # antes que nómina: «COMISION POR … PAGO NOMINA»
        (r"EMISION EDO\. DE CTA|TARIFA MANTENIMIENTO", D, S_CARGOS),
        (r"PAGO AL SENIAT|IMPUESTO IGTF", D, S_IMPUESTOS),
        (r"PAGO DE NOMINA", D, S_NOMINA),
        (r"CREDITO INMEDIATO - TRANSF\. PRES|TRANSFERENCIA DESDE LA CUENTA|ALTO VALOR PRESENTADA", D, S_TRANSF),
    ],
    "BANCAMIGA": [
        (r"Liquidaci[oó]n a Comercio TDD", C, E_POS_DEB),
        (r"Liquidaci[oó]n a Comercio TDC", C, E_POS_CRE),
        (r"COBRO POR PROCESAMIENTO|Comisi[oó]n", D, S_COMISION),
        (r"Mantenimiento de Cuenta|Emision Estado de Cuenta|Envio de SMS", D, S_CARGOS),
        (r"ND Credito Inmediato", D, S_TRANSF),
        (r"NC Credito Inmediato|Credito Inmediato", C, E_TRANSF),
        (r"Consumo Masterdebit", D, S_POS),
    ],
}


def clasificar(banco: str, m: Movimiento) -> str:
    texto = f"{m.descripcion} | {m.detalle} | {m.nota}"
    sentido = D if m.debito else C
    for patron, dirc, nat in REGLAS.get(banco, []):
        if dirc == sentido and re.search(patron, texto, re.I):
            return nat
    return OTROS


@dataclass
class MovClasificado:
    banco: str
    indice: int              # posición en extracto.movimientos (0 = primero)
    mov: Movimiento
    naturaleza: str
    contraparte: str = ""    # para traslados: "BNC 31/08/2026 ref ..."


def clasificar_extracto(e: Extracto) -> list[MovClasificado]:
    return [MovClasificado(e.banco, i, m, clasificar(e.banco, m)) for i, m in enumerate(e.movimientos)]


def marcar_traslados(listas: Iterable[list[MovClasificado]], dias: int = 2) -> int:
    """Empareja débitos y créditos por el mismo monto entre bancos distintos del mismo cliente.

    Solo considera débitos de tipo transferencia y créditos de tipo transferencia recibida.
    Devuelve cuántos pares se marcaron.
    """
    todos = [x for l in listas for x in l]
    salidas = [x for x in todos if x.naturaleza == S_TRANSF]
    entradas = [x for x in todos if x.naturaleza == E_TRANSF]
    usados: set[int] = set()
    pares = 0
    for s in salidas:
        cands = [e for e in entradas
                 if id(e) not in usados and e.banco != s.banco
                 and e.mov.credito == s.mov.debito
                 and abs((e.mov.fecha_contable - s.mov.fecha_contable).days) <= dias]
        if not cands:
            continue
        cands.sort(key=lambda e: (_ref_comun(s.mov, e.mov), abs((e.mov.fecha_contable - s.mov.fecha_contable).days)))
        e = cands[0]
        usados.add(id(e))
        s.naturaleza, e.naturaleza = S_TRASLADO, E_TRASLADO
        s.contraparte = f"{e.banco} {e.mov.fecha_contable:%d/%m/%Y} ref {e.mov.referencia}"
        e.contraparte = f"{s.banco} {s.mov.fecha_contable:%d/%m/%Y} ref {s.mov.referencia}"
        pares += 1
    return pares


def _ref_comun(a: Movimiento, b: Movimiento) -> int:
    """0 si una referencia termina en la otra (mejor candidato), 1 si no."""
    ra, rb = a.referencia.lstrip("0"), b.referencia.lstrip("0")
    if ra and rb and (ra.endswith(rb) or rb.endswith(ra)):
        return 0
    return 1


def resumen(clasificados: list[MovClasificado]) -> "OrderedDict[str, tuple[int, Decimal, Decimal]]":
    """naturaleza -> (cantidad, total entradas, total salidas), en el orden del reporte."""
    out: "OrderedDict[str, list]" = OrderedDict((n, [0, Decimal("0.00"), Decimal("0.00")]) for n in ORDEN)
    for x in clasificados:
        r = out[x.naturaleza]
        r[0] += 1
        r[1] += x.mov.credito
        r[2] += x.mov.debito
    return OrderedDict((k, tuple(v)) for k, v in out.items() if v[0])
