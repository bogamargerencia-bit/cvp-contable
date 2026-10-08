"""Conciliación de un extracto bancario contra el libro de bancos del sistema.

El libro está en US$ pero cada asiento trae el monto en Bs. en "Referencia", así que se
concilia por monto en Bs. Pasadas, de la más segura a la menos segura:

  1. Monto exacto, mismo sentido, fecha a ±N días (por defecto 5).            → CONCILIADO
  2. Uno contra varios, exacto: un asiento = suma de 2-4 movimientos del banco,
     o un movimiento = suma de 2-4 asientos (p. ej. una nómina en varias líneas). → CONCILIADO_AGRUPADO
  3. Asiento resumen con montos en la descripción ("VUELTOS a + b + c"):
     cada componente se busca por monto exacto.                                → CONCILIADO_COMPONENTES
  4. Diferencia de monto: mismo sentido, ±N días, diferencia ≤ tolerancia
     (por defecto Bs. 1,00). Se empareja pero NO se da por conciliado.         → DIFERENCIA_MONTO
  5. Sentido invertido: monto exacto pero el libro lo tiene como entrada y el
     banco como salida (o al revés).                                            → SENTIDO_INVERTIDO
  6. Lo que queda: SOLO_BANCO / SOLO_LIBRO / RESUMEN_SIN_MONTO (asiento sin monto en Bs.).

Nada se ajusta. Cada partida dice con qué se emparejó y por qué.
"""
from __future__ import annotations

import itertools
import re
from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from typing import Optional

from .modelo import Extracto, Movimiento
from .sistema import AsientoLibro, LibroBanco


class EstadoPartida(str, Enum):
    CONCILIADO = "Conciliado"
    CONCILIADO_AGRUPADO = "Conciliado (agrupado)"
    CONCILIADO_COMPONENTES = "Conciliado (por componentes)"
    CONCILIADO_REFERENCIA = "Conciliado (por referencia bancaria)"
    CONCILIADO_TOTAL = "Conciliado (total del mes)"
    DIFERENCIA_MONTO = "Diferencia de monto"
    SENTIDO_INVERTIDO = "Sentido invertido"
    OTRO_BANCO = "Registrado en el libro de otro banco"
    SOLO_BANCO = "Solo en banco"
    SOLO_LIBRO = "Solo en libro"
    RESUMEN_SIN_MONTO = "Asiento resumen sin monto en Bs."
    # Asignados por la conciliación con el cierre de caja (conciliacion_caja.py):
    CONCILIADO_CAJA = "Conciliado vía cierre de caja"
    CAJA_SIN_LIBRO = "En caja, no registrado en el libro"


CONCILIADOS = {EstadoPartida.CONCILIADO, EstadoPartida.CONCILIADO_AGRUPADO,
               EstadoPartida.CONCILIADO_COMPONENTES, EstadoPartida.CONCILIADO_CAJA,
               EstadoPartida.CONCILIADO_REFERENCIA, EstadoPartida.CONCILIADO_TOTAL}


@dataclass
class Partida:
    """Un emparejamiento (o una partida sin pareja)."""
    estado: EstadoPartida
    movs: list[int] = field(default_factory=list)       # índices en extracto.movimientos
    asientos: list[int] = field(default_factory=list)   # índices en libro.asientos
    diferencia: Decimal = Decimal("0.00")               # Bs.: libro − banco (con signo de salida/entrada)
    nota: str = ""


@dataclass
class ResultadoConciliacion:
    extracto: Extracto
    libro: LibroBanco
    partidas: list[Partida]
    estado_mov: dict[int, Partida]
    estado_asiento: dict[int, Partida]

    def resumen(self) -> dict[EstadoPartida, tuple[int, int, Decimal, Decimal]]:
        """estado -> (nº movimientos banco, nº asientos libro, monto banco Bs., monto libro Bs.)"""
        out: dict[EstadoPartida, list] = {}
        for p in self.partidas:
            r = out.setdefault(p.estado, [0, 0, Decimal("0.00"), Decimal("0.00")])
            r[0] += len(p.movs)
            r[1] += len(p.asientos)
            r[2] += sum((_monto(self.extracto.movimientos[i]) for i in p.movs), Decimal("0.00"))
            r[3] += sum((self.libro.asientos[j].monto_bs or Decimal("0.00") for j in p.asientos), Decimal("0.00"))
        return {k: tuple(v) for k, v in out.items()}


def _monto(m: Movimiento) -> Decimal:
    return m.debito or m.credito


def _es_salida(m: Movimiento) -> bool:
    return bool(m.debito)


def _dias(m: Movimiento, a: AsientoLibro) -> int:
    fechas = [f for f in (m.fecha_real, m.fecha_contable) if f]
    return min(abs((f - a.fecha).days) for f in fechas)


def conciliar(extracto: Extracto, libro: LibroBanco, dias: int = 5,
              tolerancia_monto: Decimal = Decimal("1.00"),
              max_grupo: int = 4, max_candidatos: int = 25,
              naturalezas: Optional[dict[int, str]] = None) -> ResultadoConciliacion:
    """naturalezas: índice del movimiento → naturaleza (naturaleza.py); habilita la pasada de
    «total del mes» (un asiento de cierre igual a la suma de una o dos naturalezas del banco)."""
    movs = extracto.movimientos
    asientos = libro.asientos
    libres_m = set(range(len(movs)))
    libres_a = set(range(len(asientos)))
    partidas: list[Partida] = []

    def tomar(p: Partida) -> None:
        partidas.append(p)
        libres_m.difference_update(p.movs)
        libres_a.difference_update(p.asientos)

    def candidatos(j: int, mismo_sentido: bool = True) -> list[int]:
        a = asientos[j]
        return [i for i in libres_m
                if (_es_salida(movs[i]) == a.es_salida) == mismo_sentido
                and _dias(movs[i], a) <= dias]

    con_monto = [j for j in range(len(asientos)) if asientos[j].monto_bs is not None]

    # 0. Referencia bancaria: el asiento trae el número de operación del banco en vez del monto.
    def ref(t: str) -> str:
        return (t or "").strip().lstrip("0")
    for j, a in enumerate(asientos):
        if not a.referencia_banco:
            continue
        ra = ref(a.referencia_banco)
        c = [i for i in libres_m if len(ref(movs[i].referencia)) >= 6 and len(ra) >= 6
             and (ref(movs[i].referencia).endswith(ra) or ra.endswith(ref(movs[i].referencia)))
             and abs((movs[i].fecha_contable - a.fecha).days) <= 2 * dias]
        c.sort(key=lambda i: (_es_salida(movs[i]) != a.es_salida, _dias(movs[i], a)))
        if c:
            i = c[0]
            nota = f"Referencia {a.referencia_banco} = {movs[i].referencia}; banco Bs. {_monto(movs[i])}"
            if a.monto_usd:
                nota += f" (tasa implícita {(_monto(movs[i]) / a.monto_usd).quantize(Decimal('0.01'))})"
            if _es_salida(movs[i]) != a.es_salida:
                tomar(Partida(EstadoPartida.SENTIDO_INVERTIDO, [i], [j], nota=nota + ". Sentido invertido."))
            else:
                tomar(Partida(EstadoPartida.CONCILIADO_REFERENCIA, [i], [j], nota=nota))

    # 1. Monto exacto. Primero los asientos con menos candidatos, para no "robar" parejas.
    def exactos(j: int) -> list[int]:
        return [i for i in candidatos(j) if _monto(movs[i]) == asientos[j].monto_bs]
    for j in sorted(con_monto, key=lambda j: (len(exactos(j)), asientos[j].fecha)):
        if j not in libres_a:
            continue
        c = exactos(j)
        if c:
            i = min(c, key=lambda i: (_dias(movs[i], asientos[j]), i))
            tomar(Partida(EstadoPartida.CONCILIADO, [i], [j]))

    # 2a. Un asiento contra varios movimientos.
    for j in sorted(con_monto, key=lambda j: asientos[j].fecha):
        if j not in libres_a:
            continue
        objetivo = asientos[j].monto_bs
        c = sorted((i for i in candidatos(j) if _monto(movs[i]) < objetivo),
                   key=lambda i: _dias(movs[i], asientos[j]))[:max_candidatos]
        grupo = _buscar_suma(c, lambda i: _monto(movs[i]), objetivo, max_grupo)
        if grupo:
            tomar(Partida(EstadoPartida.CONCILIADO_AGRUPADO, sorted(grupo), [j],
                          nota=f"1 asiento = {len(grupo)} movimientos del banco"))

    # 2b. Un movimiento contra varios asientos.
    for i in sorted(libres_m, key=lambda i: movs[i].fecha_contable):
        if i not in libres_m:
            continue
        m = movs[i]
        c = sorted((j for j in libres_a if asientos[j].monto_bs is not None
                    and asientos[j].es_salida == _es_salida(m)
                    and asientos[j].monto_bs < _monto(m) and _dias(m, asientos[j]) <= dias),
                   key=lambda j: _dias(m, asientos[j]))[:max_candidatos]
        grupo = _buscar_suma(c, lambda j: asientos[j].monto_bs, _monto(m), max_grupo)
        if grupo:
            tomar(Partida(EstadoPartida.CONCILIADO_AGRUPADO, [i], sorted(grupo),
                          nota=f"1 movimiento del banco = {len(grupo)} asientos"))

    # 3. Asientos resumen con componentes en la descripción. Son asientos de cierre de mes:
    #    los componentes se buscan en todo el extracto, no solo a ±N días.
    notas_resumen: dict[int, str] = {}
    for j in sorted(libres_a):
        a = asientos[j]
        if not a.componentes_bs:
            continue
        elegidos: list[int] = []
        faltan: list[Decimal] = []
        for comp in a.componentes_bs:
            c = [i for i in libres_m if _monto(movs[i]) == comp and i not in elegidos]
            if c:
                elegidos.append(min(c, key=lambda i: _dias(movs[i], a)))
            else:
                faltan.append(comp)
        if not faltan:
            tomar(Partida(EstadoPartida.CONCILIADO_COMPONENTES, sorted(elegidos), [j],
                          nota=f"{len(elegidos)} componentes de la descripción encontrados en el banco"))
        else:
            encontrados = ", ".join(f"{_monto(movs[i])} ({movs[i].fecha_contable:%d/%m})" for i in elegidos)
            notas_resumen[j] = (f"Componentes encontrados {len(elegidos)} de {len(a.componentes_bs)}"
                                + (f": {encontrados}" if encontrados else "")
                                + f". No encontrados en este banco: {', '.join(str(x) for x in faltan)}")

    # 3b. Total del mes: asientos de cierre («INGRESO POR PUNTO DE VENTAS AGOSTO», «COMISIONES
    #     BANCARIAS AGOSTO») iguales a la suma de una o dos naturalezas del banco en todo el período.
    pistas_total: dict[int, str] = {}
    if naturalezas:
        for j in sorted(libres_a):
            a = asientos[j]
            if a.monto_bs is None:
                continue
            grupos: dict[str, list[int]] = {}
            for i in libres_m:
                if _es_salida(movs[i]) == a.es_salida:
                    grupos.setdefault(naturalezas.get(i, "?"), []).append(i)
            opciones = [(n,) for n in grupos] + list(itertools.combinations(sorted(grupos), 2))
            hallado = None
            cercano = None
            for opt in opciones:
                idx = [i for n in opt for i in grupos[n]]
                if len(idx) < 2:
                    continue
                total = sum((_monto(movs[i]) for i in idx), Decimal("0.00"))
                if total == a.monto_bs:
                    hallado = (opt, idx, None)
                    break
                sobra = total - a.monto_bs     # ¿sobra exactamente un movimiento (p. ej. un envío de prueba)?
                if sobra > 0 and len(idx) >= 3:
                    unico = [i for i in idx if _monto(movs[i]) == sobra]
                    if len(unico) == 1:
                        hallado = (opt, [i for i in idx if i != unico[0]], unico[0])
                        break
                dif = abs(total - a.monto_bs)
                if dif <= a.monto_bs * Decimal("0.01") and (cercano is None or dif < cercano[0]):
                    cercano = (dif, opt, idx, total)
            if hallado:
                opt, idx, excluido = hallado
                nota = f"Total del mes de {' + '.join(opt)}: {len(idx)} movimientos del banco"
                if excluido is not None:
                    m = movs[excluido]
                    nota += (f" (sin {m.fecha_contable:%d/%m} {m.descripcion} {_monto(m)}, que es justo la "
                             "diferencia; ese movimiento queda solo en banco)")
                tomar(Partida(EstadoPartida.CONCILIADO_TOTAL, sorted(idx), [j], nota=nota))
            elif cercano:
                dif, opt, idx, total = cercano
                pistas_total[j] = (f"Posible total del mes de {' + '.join(opt)}: {len(idx)} movimientos por "
                                   f"Bs. {total} (diferencia {a.monto_bs - total}). Revisar; no se concilió.")

    # 4. Diferencia de monto (céntimos / redondeos).
    for j in sorted(con_monto, key=lambda j: asientos[j].fecha):
        if j not in libres_a:
            continue
        a = asientos[j]
        c = [i for i in candidatos(j) if abs(_monto(movs[i]) - a.monto_bs) <= tolerancia_monto]
        if c:
            i = min(c, key=lambda i: (abs(_monto(movs[i]) - a.monto_bs), _dias(movs[i], a)))
            dif = a.monto_bs - _monto(movs[i])
            tomar(Partida(EstadoPartida.DIFERENCIA_MONTO, [i], [j], diferencia=dif,
                          nota=f"Libro {a.monto_bs} vs. banco {_monto(movs[i])}"))

    # 5. Sentido invertido.
    for j in sorted(con_monto, key=lambda j: asientos[j].fecha):
        if j not in libres_a:
            continue
        a = asientos[j]
        c = [i for i in candidatos(j, mismo_sentido=False) if _monto(movs[i]) == a.monto_bs]
        if c:
            i = min(c, key=lambda i: _dias(movs[i], a))
            lado = "salida (crédito)" if a.es_salida else "entrada (débito)"
            tomar(Partida(EstadoPartida.SENTIDO_INVERTIDO, [i], [j],
                          nota=f"El libro lo registra como {lado}; el banco al revés"))

    # 6. Sin pareja.
    for j in sorted(libres_a):
        estado = EstadoPartida.RESUMEN_SIN_MONTO if asientos[j].es_resumen else EstadoPartida.SOLO_LIBRO
        partidas.append(Partida(estado, [], [j], nota=notas_resumen.get(j, "") or pistas_total.get(j, "")))
    for i in sorted(libres_m):
        partidas.append(Partida(EstadoPartida.SOLO_BANCO, [i], []))

    est_m = {i: p for p in partidas for i in p.movs}
    est_a = {j: p for p in partidas for j in p.asientos}
    return ResultadoConciliacion(extracto, libro, partidas, est_m, est_a)


def _buscar_suma(cands: list[int], valor, objetivo: Decimal, max_k: int) -> Optional[list[int]]:
    """Primera combinación de 2..max_k candidatos cuya suma es exactamente el objetivo."""
    for k in range(2, max_k + 1):
        for combo in itertools.combinations(cands, k):
            if sum((valor(x) for x in combo), Decimal("0.00")) == objetivo:
                return list(combo)
    return None


def conciliar_cliente(pares: list[tuple[Extracto, LibroBanco]], dias: int = 5,
                      tolerancia_monto: Decimal = Decimal("1.00"),
                      naturalezas: Optional[dict[str, dict[int, str]]] = None) -> dict[str, ResultadoConciliacion]:
    """Concilia cada banco con su libro y luego cruza entre bancos del mismo cliente:
    un asiento "solo en libro" del banco X que coincide (monto exacto, mismo sentido,
    ±N días) con un movimiento "solo en banco" del banco Y se marca en ambos como
    registrado en el libro de otro banco. No se da por conciliado: hay que corregir el libro.
    """
    res = {e.banco: conciliar(e, l, dias=dias, tolerancia_monto=tolerancia_monto,
                              naturalezas=(naturalezas or {}).get(e.banco)) for e, l in pares}
    usados: set[tuple[str, int]] = set()
    for bx, rx in res.items():
        for p in list(rx.partidas):
            if p.estado is not EstadoPartida.SOLO_LIBRO:
                continue
            j = p.asientos[0]
            a = rx.libro.asientos[j]
            cands = []
            for by, ry in res.items():
                if by == bx:
                    continue
                for q in ry.partidas:
                    if q.estado is not EstadoPartida.SOLO_BANCO or (by, q.movs[0]) in usados:
                        continue
                    m = ry.extracto.movimientos[q.movs[0]]
                    if _monto(m) == a.monto_bs and _es_salida(m) == a.es_salida and _dias(m, a) <= dias:
                        cands.append((_dias(m, a), by, q, m))
            if not cands:
                continue
            _, by, q, m = min(cands, key=lambda c: c[0])
            ry = res[by]
            usados.add((by, q.movs[0]))
            p.estado = EstadoPartida.OTRO_BANCO
            p.nota = (f"El movimiento está en {by}: {m.fecha_contable:%d/%m/%Y} {m.descripcion} "
                      f"{_monto(m)} (ref {m.referencia or '-'})")
            q.estado = EstadoPartida.OTRO_BANCO
            q.nota = f"Registrado en el libro de {bx}: fila {a.fila}, {a.fecha:%d/%m/%Y} {a.descripcion}"

    _pistas(res, dias)
    return res


_ES_COMISION = re.compile(r"comisi|^com\.|cobra comision", re.I)


def _pistas(res: dict[str, ResultadoConciliacion], dias: int,
            dif_max: Decimal = Decimal("5.00")) -> None:
    """Para cada asiento que sigue "solo en libro", anota en la nota la mejor pista (sin conciliar):
    mismo monto fuera de la ventana de días, o diferencia ≤ dif_max dentro de la ventana."""
    for bx, rx in res.items():
        for p in rx.partidas:
            if p.estado is not EstadoPartida.SOLO_LIBRO:
                continue
            a = rx.libro.asientos[p.asientos[0]]
            if a.monto_bs is None:          # referencia bancaria o asiento resumen: no hay monto con qué comparar
                continue
            pistas = []
            for by, ry in res.items():
                for q in ry.partidas:
                    if q.estado is not EstadoPartida.SOLO_BANCO:
                        continue
                    m = ry.extracto.movimientos[q.movs[0]]
                    if _es_salida(m) != a.es_salida or _ES_COMISION.search(m.descripcion):
                        continue
                    dif, d = _monto(m) - a.monto_bs, _dias(m, a)
                    if dif == 0 or (abs(dif) <= dif_max and d <= dias):
                        pistas.append((abs(dif), d, by, m))
            if pistas:
                dif, d, by, m = min(pistas, key=lambda x: (x[0], x[1]))
                p.nota = (f"Posible: {by} {m.fecha_contable:%d/%m/%Y} {m.descripcion} {_monto(m)} "
                          f"(diferencia de monto {dif}, {d} días). Revisar; no se concilió.")
