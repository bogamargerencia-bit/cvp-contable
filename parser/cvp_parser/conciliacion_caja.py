"""Conciliación del cierre de caja contra los bancos y contra los asientos resumen del libro.

El sistema registra los cobros como un asiento resumen mensual en US$ por medio de pago
(PAGO MOVIL, DEBITO, CREDITO, VUELTOS) sin monto en Bs. El cierre de caja diario sirve de
puente: cada día dice cuánto entró por cada medio y, en las fórmulas, el desglose de los pagos.

  Caja ↔ banco
    - Tarjetas (POS): el total del día (crédito + débito de ese banco) se busca en los lotes
      del banco abonados entre D+1 y D+4 (en BNC el lote del día D se abona en D+2 de madrugada).
      Un día puede ser 1 lote o la suma de 2-3 lotes. El reparto crédito/débito de la caja no
      tiene por qué coincidir con el del banco: se informa, pero se concilia por total.
    - Pago móvil: cada sumando del desglose se busca entre los créditos del banco a ±días:
        1. monto exacto                                  → Conciliado
        2. suma exacta de 2-6 créditos (pago fraccionado) → Conciliado (varios pagos en el banco)
        3. un solo dígito distinto                       → Posible error de transcripción (NO concilia)
        4. todos los créditos sin caja de la ventana suman el monto → Conciliado (varios pagos)
        5. nada → No encontrado (la nota dice cuánto queda sin caja en la ventana y la diferencia)
    - Vueltos: salidas; solo monto exacto entre los débitos de pago móvil/transferencia de todos
      los bancos (con tantos débitos, una suma podría coincidir por casualidad).
    - Créditos de pago móvil del banco que no aparecen en caja → Cobro sin registro en caja.
    - Lotes del banco sin día de caja → del mes anterior (si se abonan al inicio) o sin venta.

  Caja ↔ libro
    - Cada asiento resumen se compara con el total en US$ del medio correspondiente.
      Si coincide con el mes completo → conciliado. Si coincide con los días hasta una fecha,
      se concilia esa parte y se informan los días que faltan en el libro.

Los movimientos del banco emparejados con caja, cuyo día está cubierto por un asiento resumen
del libro, pasan de "Solo en banco" a "Conciliado vía cierre de caja".
"""
from __future__ import annotations

import datetime as dt
import itertools
import re
from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from typing import Optional

from .conciliacion import EstadoPartida as EP, ResultadoConciliacion
from .naturaleza import (E_PAGO_MOVIL, E_POS_CRE, E_POS_DEB, E_TRANSF, S_PAGO_MOVIL, S_TRANSF,
                         MovClasificado)
from .ventas import PAGO_MOVIL, POS, VUELTO, CierreCaja, ItemCaja

CERO = Decimal("0.00")


class EstadoCaja(str, Enum):
    CONCILIADO = "Conciliado"
    AGRUPADO = "Conciliado (varios pagos en el banco)"
    LOTES = "Conciliado (varios lotes)"
    POSIBLE_ERROR = "Posible error de transcripción"
    EN_TRANSITO = "En tránsito (se abona después del período)"
    NO_ENCONTRADO = "No encontrado en el banco"
    TOTAL_MES = "Cruce por total del mes"
    DIFERENCIA_DIA = "Diferencia en el día"


CONCILIADOS_CAJA = {EstadoCaja.CONCILIADO, EstadoCaja.AGRUPADO, EstadoCaja.LOTES}


@dataclass
class LineaCaja:
    """Un sumando (pago móvil / vuelto) o un día de tarjetas (POS) del cierre de caja."""
    fecha: dt.date
    medio: str
    banco: Optional[str]
    monto: Decimal
    estado: EstadoCaja
    items: list[ItemCaja]
    movs: list[tuple[str, int]] = field(default_factory=list)   # (banco, índice en el extracto)
    nota: str = ""
    en_libro: Optional[bool] = None    # ¿el día está cubierto por un asiento resumen del libro?


@dataclass
class CruceAsiento:
    banco: str
    asiento: int                       # índice en libro.asientos
    medio: Optional[str]
    usd_libro: Decimal
    usd_caja_mes: Decimal
    hasta: Optional[dt.date]           # último día de caja cubierto por el asiento
    conciliado: bool
    nota: str
    usd_libro_total: Optional[Decimal] = None   # suma de todos los asientos del grupo (si son varios)


@dataclass
class ResultadoCaja:
    cierre: CierreCaja
    lineas: list[LineaCaja]
    sin_caja: list[tuple[str, int, str]]      # (banco, índice, motivo) créditos del banco sin caja
    asientos: list[CruceAsiento]
    totales_mes: list["TotalMes"] = field(default_factory=list)
    propuestas: list["PropuestaFecha"] = field(default_factory=list)


@dataclass
class PropuestaFecha:
    """Fila de caja con la fecha mal escrita: su monto coincide exacto con los cobros de un día del
    banco que no tiene fila en la caja. Si el analista la acepta, se aplica en la corrida siguiente."""
    fila: int
    fecha_actual: dt.date
    fecha_propuesta: dt.date
    medio: str
    monto: Decimal
    motivo: str


@dataclass
class TotalMes:
    """Tarjetas conciliadas por total del mes (modo «total_mes»)."""
    medios: list[str]
    bancos: list[str]
    caja: Decimal                  # total del mes en el cierre de caja
    abonado: Decimal               # abonos POS del período en los bancos
    mes_anterior: Decimal          # abonos del período que son ventas del mes anterior (por fecha de venta)
    sin_fecha: Decimal             # abonos sin fecha de venta identificable
    por_abonar: Decimal            # caja − (abonado − mes_anterior): ventas del mes que se abonarían después
    movs: list[tuple[str, int]]
    nota: str = ""


def _detalle_texto(m) -> str:
    return f"{m.descripcion} {m.detalle}"


def _lote(x: MovClasificado) -> str:
    m = re.search(r"LOTE:\s*(\d+)", x.mov.detalle)
    return m.group(1) if m else f"{x.mov.fecha_contable:%Y%m%d}"


def _un_digito(a: Decimal, b: Decimal) -> bool:
    sa, sb = f"{a:.2f}", f"{b:.2f}"
    return len(sa) == len(sb) and sum(x != y for x, y in zip(sa, sb)) == 1


def fecha_venta(banco: str, m) -> Optional[dt.date]:
    """Fecha de la venta que liquida un abono POS, cuando el banco la informa.
    - BANPLUS: referencia de 24 dígitos «783015200030·LLL·DD·MM·…» (lote, día, mes).
    - PLAZA:  la descripción termina en DDMM («POS MAE 88046439 001 0003 1908» = 19/08).
    """
    try:
        if banco == "BANPLUS" and re.fullmatch(r"\d{24}", m.referencia or ""):
            d, mes = int(m.referencia[15:17]), int(m.referencia[17:19])
        elif banco == "PLAZA" and (x := re.search(r"\b(\d{2})(\d{2})$", m.descripcion)):
            d, mes = int(x.group(1)), int(x.group(2))
        else:
            return None
        anio = m.fecha_contable.year - (1 if mes > m.fecha_contable.month else 0)
        return dt.date(anio, mes, d)
    except ValueError:
        return None


def _dia_abono(fecha: dt.date) -> dt.date:
    """Día en que el banco abona lo cobrado en `fecha`: el fin de semana pasa al lunes."""
    return fecha + dt.timedelta(days=(7 - fecha.weekday()) % 7 if fecha.weekday() >= 5 else 0)


def conciliar_caja(cierre: CierreCaja, clasificados: dict[str, list[MovClasificado]],
                   conciliaciones: dict[str, ResultadoConciliacion],
                   dias_pm: tuple[int, int] = (-1, 3), dias_pos: tuple[int, int] = (1, 4),
                   max_grupo: int = 6, max_candidatos: int = 20, config=None) -> ResultadoCaja:
    """config: clientes.ConfigCliente (opcional) con los modos de cruce y los asientos resumen."""
    totales_mes: list[TotalMes] = []
    propuestas: list[PropuestaFecha] = []
    usados: set[tuple[str, int]] = set()
    lineas: list[LineaCaja] = []
    sin_caja: list[tuple[str, int, str]] = []

    def libre(b: str, x: MovClasificado) -> bool:
        p = conciliaciones[b].estado_mov.get(x.indice)
        # Un movimiento conciliado con el libro por «total del mes» (p. ej. VTAS … PAGO MOVIL con el total en
        # Bs.) sigue disponible para el cruce día a día con la caja: son dos controles distintos.
        return (b, x.indice) not in usados and p is not None and p.estado in (EP.SOLO_BANCO, EP.CONCILIADO_TOTAL)

    hasta_banco = {b: r.extracto.hasta for b, r in conciliaciones.items()}
    desde_banco = {b: r.extracto.desde or r.extracto.hasta.replace(day=1) for b, r in conciliaciones.items()}

    # ---------------------------------------------------------------- Tarjetas (POS) por lote
    for banco in sorted({i.banco for i in cierre.items if i.tipo == POS and i.banco in clasificados}):
        lotes: dict[str, list[MovClasificado]] = {}
        for x in clasificados[banco]:
            if x.naturaleza in (E_POS_CRE, E_POS_DEB) and libre(banco, x):
                lotes.setdefault(_lote(x), []).append(x)
        total_lote = {l: sum((x.mov.credito for x in xs), CERO) for l, xs in lotes.items()}
        fecha_lote = {l: min(x.mov.fecha_contable for x in xs) for l, xs in lotes.items()}
        lotes_usados: set[str] = set()
        por_dia: dict[dt.date, list[ItemCaja]] = {}
        for i in cierre.items:
            if i.tipo == POS and i.banco == banco and i.modo in ("lote", ""):
                por_dia.setdefault(i.fecha, []).append(i)
        if not por_dia:
            continue
        for fecha in sorted(por_dia):
            items = por_dia[fecha]
            total = sum((i.monto_bs for i in items), CERO)
            cands = sorted((l for l in lotes if l not in lotes_usados
                            and dias_pos[0] <= (fecha_lote[l] - fecha).days <= dias_pos[1]),
                           key=lambda l: (fecha_lote[l], l))
            elegido: Optional[list[str]] = None
            for k in (1, 2, 3):
                for combo in itertools.combinations(cands, k):
                    if sum((total_lote[l] for l in combo), CERO) == total:
                        elegido = list(combo)
                        break
                if elegido:
                    break
            caja_txt = " / ".join(f"{i.medio} {i.monto_bs}" for i in items)
            if elegido:
                lotes_usados.update(elegido)
                movs = [x for l in elegido for x in lotes[l]]
                cre = sum((x.mov.credito for x in movs if x.naturaleza == E_POS_CRE), CERO)
                deb = sum((x.mov.credito for x in movs if x.naturaleza == E_POS_DEB), CERO)
                nota = (f"Lote {' + '.join(elegido)} abonado {fecha_lote[elegido[0]]:%d/%m}. "
                        f"Caja: {caja_txt}. Banco: crédito {cre} / débito {deb}.")
                usados.update((banco, x.indice) for x in movs)
                lineas.append(LineaCaja(fecha, f"Tarjetas {banco}", banco, total,
                                        EstadoCaja.CONCILIADO if len(elegido) == 1 else EstadoCaja.LOTES,
                                        items, [(banco, x.indice) for x in movs], nota))
            else:
                transito = (fecha + dt.timedelta(days=dias_pos[0] + 1)) > hasta_banco[banco]
                lineas.append(LineaCaja(
                    fecha, f"Tarjetas {banco}", banco, total,
                    EstadoCaja.EN_TRANSITO if transito else EstadoCaja.NO_ENCONTRADO, items, [],
                    f"Caja: {caja_txt}." + (" El lote se abonaría después del cierre del estado de cuenta."
                                            if transito else "")))
        for l, xs in lotes.items():
            if l in lotes_usados:
                continue
            inicio = (fecha_lote[l] - desde_banco[banco]).days < dias_pos[1]
            motivo = (f"Lote {l} abonado {fecha_lote[l]:%d/%m}: ventas del mes anterior" if inicio
                      else f"Lote {l} abonado {fecha_lote[l]:%d/%m}: sin día en el cierre de caja")
            for x in xs:
                usados.add((banco, x.indice))
                sin_caja.append((banco, x.indice, motivo))

    # ---------------------------------------------------------------- Pago móvil y vueltos
    def buscar(items_de_medio: list[ItemCaja], bancos: list[str], naturalezas: set[str],
               es_credito: bool, solo_exacto: bool = False) -> None:
        """solo_exacto: para salidas (vueltos) buscadas en todos los bancos, donde hay tantos
        débitos que una suma o un dígito distinto puede coincidir por casualidad."""
        pendientes: list[tuple[ItemCaja, Decimal]] = [(i, c) for i in items_de_medio for c in i.componentes]

        def cands(fecha: dt.date) -> list[tuple[str, MovClasificado]]:
            out = []
            for b in bancos:
                for x in clasificados.get(b, []):
                    monto = x.mov.credito if es_credito else x.mov.debito
                    if (monto and x.naturaleza in naturalezas and libre(b, x)
                            and dias_pm[0] <= (x.mov.fecha_contable - fecha).days <= dias_pm[1]):
                        out.append((b, x))
            return out

        def monto(x: MovClasificado) -> Decimal:
            return x.mov.credito if es_credito else x.mov.debito

        resto = []
        for item, comp in pendientes:                              # 1. exacto
            c = [(b, x) for b, x in cands(item.fecha) if monto(x) == comp]
            if c:
                b, x = min(c, key=lambda bx: abs((bx[1].mov.fecha_contable - item.fecha).days))
                usados.add((b, x.indice))
                lineas.append(LineaCaja(item.fecha, item.medio, b, comp, EstadoCaja.CONCILIADO, [item],
                                        [(b, x.indice)], f"{b} {x.mov.fecha_contable:%d/%m} {x.mov.descripcion}"))
            else:
                resto.append((item, comp))
        if solo_exacto:
            for item, comp in resto:
                lineas.append(LineaCaja(item.fecha, item.medio, item.banco, comp, EstadoCaja.NO_ENCONTRADO,
                                        [item], [], "Ningún débito de pago móvil/transferencia de los bancos "
                                        "tiene este monto exacto a ±días."))
            return
        resto2 = []
        for item, comp in resto:                                   # 2. pago fraccionado
            c = sorted([(b, x) for b, x in cands(item.fecha) if monto(x) < comp],
                       key=lambda bx: abs((bx[1].mov.fecha_contable - item.fecha).days))[:max_candidatos]
            grupo = None
            for k in range(2, max_grupo + 1):
                for combo in itertools.combinations(c, k):
                    if sum((monto(x) for _, x in combo), CERO) == comp:
                        grupo = combo
                        break
                if grupo:
                    break
            if grupo:
                usados.update((b, x.indice) for b, x in grupo)
                lineas.append(LineaCaja(item.fecha, item.medio, grupo[0][0], comp, EstadoCaja.AGRUPADO, [item],
                                        [(b, x.indice) for b, x in grupo],
                                        f"{len(grupo)} pagos en el banco: "
                                        + " + ".join(f"{monto(x)} ({x.mov.fecha_contable:%d/%m})" for _, x in grupo)))
            else:
                resto2.append((item, comp))
        for item, comp in resto2:                                  # 3. error de transcripción
            c = [(b, x) for b, x in cands(item.fecha) if _un_digito(monto(x), comp)]
            if c:
                b, x = min(c, key=lambda bx: abs((bx[1].mov.fecha_contable - item.fecha).days))
                usados.add((b, x.indice))
                lineas.append(LineaCaja(item.fecha, item.medio, b, comp, EstadoCaja.POSIBLE_ERROR, [item],
                                        [(b, x.indice)],
                                        f"Caja {comp} vs. banco {monto(x)} ({x.mov.fecha_contable:%d/%m} "
                                        f"{x.mov.descripcion}): difieren en un dígito ({monto(x) - comp}). "
                                        "Revisar; no se concilió."))
            else:
                # 4. ¿Todos los créditos sin caja de la ventana suman el monto? (pagos en muchas partes)
                resto_b = cands(item.fecha)
                suma = sum((monto(x) for _, x in resto_b), CERO)
                if resto_b and suma == comp:
                    usados.update((b, x.indice) for b, x in resto_b)
                    lineas.append(LineaCaja(item.fecha, item.medio, resto_b[0][0], comp, EstadoCaja.AGRUPADO,
                                            [item], [(b, x.indice) for b, x in resto_b],
                                            f"{len(resto_b)} pagos en el banco (todos los que quedaban sin caja "
                                            "en la ventana de fechas)"))
                    continue
                nota = ("Ningún crédito del banco coincide (exacto, suma ni dígito)." if es_credito
                        else "Ningún débito de pago móvil/transferencia coincide.")
                if resto_b:
                    nota += (f" En la ventana quedan {len(resto_b)} movimientos del banco sin caja por "
                             f"Bs. {suma} (diferencia caja − banco: {comp - suma}).")
                lineas.append(LineaCaja(item.fecha, item.medio, item.banco, comp, EstadoCaja.NO_ENCONTRADO,
                                        [item], [], nota))

    # ---------------------------------------------------------------- Tarjetas por total del mes
    grupos_tm: dict[tuple[str, ...], list[ItemCaja]] = {}
    for i in cierre.items:
        if i.tipo == POS and i.modo == "total_mes":
            grupos_tm.setdefault(tuple(sorted(set(i.bancos))), []).append(i)
    # Medios que comparten banco (PUNTO CACAO y PUNTO JOHANA GIL usan Plaza) se concilian juntos.
    fusion: list[tuple[set[str], list[ItemCaja]]] = []
    for bancos_g, its in grupos_tm.items():
        for g in fusion:
            if g[0] & set(bancos_g):
                g[0].update(bancos_g)
                g[1].extend(its)
                break
        else:
            fusion.append((set(bancos_g), list(its)))
    for bancos_g, its in fusion:
        bancos_g = sorted(b for b in bancos_g if b in clasificados)
        inicio = min(desde_banco[b] for b in bancos_g)
        movs = [(b, x) for b in bancos_g for x in clasificados[b]
                if x.naturaleza in (E_POS_CRE, E_POS_DEB) and (b, x.indice) not in usados]
        abonado = sum((x.mov.credito for _, x in movs), CERO)
        anteriores = [(b, x) for b, x in movs if (fv := fecha_venta(b, x.mov)) and fv < inicio]
        sin_fecha = sum((x.mov.credito for b, x in movs if fecha_venta(b, x.mov) is None), CERO)
        mes_ant = sum((x.mov.credito for _, x in anteriores), CERO)
        caja = sum((i.monto_bs for i in its), CERO)
        por_abonar = caja - (abonado - mes_ant)
        medios_g = sorted({i.medio for i in its})
        del_mes = [(b, x) for b, x in movs if (b, x) not in anteriores]
        for b, x in anteriores:
            usados.add((b, x.indice))
            sin_caja.append((b, x.indice, f"Abono POS de ventas del mes anterior "
                                          f"({fecha_venta(b, x.mov):%d/%m/%Y})"))
        usados.update((b, x.indice) for b, x in del_mes)
        nota = (f"Caja {caja} − (abonos del período {abonado} − ventas del mes anterior {mes_ant}) = "
                f"{por_abonar} por abonar después del cierre del estado de cuenta.")
        if sin_fecha:
            nota += f" Hay Bs. {sin_fecha} en abonos sin fecha de venta identificable."
        totales_mes.append(TotalMes(medios_g, bancos_g, caja, abonado, mes_ant, sin_fecha, por_abonar,
                                    [(b, x.indice) for b, x in del_mes], nota))
        por_dia_tm: dict[dt.date, list[ItemCaja]] = {}
        for i in its:
            por_dia_tm.setdefault(i.fecha, []).append(i)
        primero = True
        for fecha in sorted(por_dia_tm):
            items = por_dia_tm[fecha]
            lineas.append(LineaCaja(fecha, " + ".join(medios_g), None, sum((i.monto_bs for i in items), CERO),
                                    EstadoCaja.TOTAL_MES, items,
                                    [(b, x.indice) for b, x in del_mes] if primero else [],
                                    "Sin correspondencia diaria exacta con los abonos: ver el total del mes."))
            primero = False

    # ---------------------------------------------------------------- Pago móvil por total diario
    def por_total_diario(items_de_medio: list[ItemCaja], banco: str) -> None:
        creditos: dict[dt.date, list[MovClasificado]] = {}
        for x in clasificados.get(banco, []):
            if x.naturaleza == E_PAGO_MOVIL and x.mov.credito and libre(banco, x):
                creditos.setdefault(x.mov.fecha_contable, []).append(x)
        # El fin de semana se cruza con el lunes solo si el banco no abonó ese mismo día
        # (agosto: Banplus abonaba el lunes; septiembre: abona el sábado y el domingo).
        bloques: dict[dt.date, list[ItemCaja]] = {}
        for i in items_de_medio:
            bloques.setdefault(i.fecha if i.fecha in creditos else _dia_abono(i.fecha), []).append(i)
        for dia in sorted(bloques):
            items = bloques[dia]
            caja = sum((i.monto_bs for i in items), CERO)
            xs = creditos.pop(dia, [])
            banco_t = sum((x.mov.credito for x in xs), CERO)
            dias_txt = ", ".join(f"{i.fecha:%d/%m}" for i in items)
            usados.update((banco, x.indice) for x in xs)
            if caja == banco_t:
                lineas.append(LineaCaja(dia, items[0].medio, banco, caja, EstadoCaja.CONCILIADO, items,
                                        [(banco, x.indice) for x in xs],
                                        f"Caja de {dias_txt} = {len(xs)} cobros abonados el {dia:%d/%m}."))
                continue
            dif = banco_t - caja
            pista = ""
            if dif > 0:  # el banco tiene más: ¿qué cobros explican la diferencia?
                for k in (1, 2, 3):
                    combo = next((c for c in itertools.combinations(xs, k)
                                  if sum((x.mov.credito for x in c), CERO) == dif), None)
                    if combo:
                        pista = (" Posibles cobros no registrados en caja: "
                                 + ", ".join(f"{x.mov.credito} (ref {x.mov.referencia})" for x in combo) + ".")
                        break
            lineas.append(LineaCaja(dia, items[0].medio, banco, caja, EstadoCaja.DIFERENCIA_DIA, items,
                                    [(banco, x.indice) for x in xs],
                                    f"Caja de {dias_txt}: {caja}; banco el {dia:%d/%m}: {banco_t} ({len(xs)} cobros); "
                                    f"diferencia banco − caja {dif}.{pista}"))
        # ¿Un día del banco sin caja coincide exactamente con una fila de caja de otro día? → fecha mal escrita.
        total_sin_caja = {dia: sum((x.mov.credito for x in xs), CERO) for dia, xs in creditos.items()}
        for l in lineas:
            if l.estado is EstadoCaja.DIFERENCIA_DIA and l.banco == banco and l.items[0].medio == items_de_medio[0].medio:
                for it in l.items:
                    for dia, tot in total_sin_caja.items():
                        if tot == it.monto_bs:
                            l.nota += (f" La fila {it.fila} de la caja (fecha {it.fecha:%d/%m}, {it.monto_bs}) coincide "
                                       f"exactamente con los cobros del {dia:%d/%m}: ¿fecha mal escrita en la caja?")
                            # Se propone la fecha que falta en la caja y que el banco abonaría ese día.
                            faltan = [d for d in cierre.fechas_faltantes if _dia_abono(d) == dia]
                            if len(faltan) == 1 and not any(p.fila == it.fila for p in propuestas):
                                propuestas.append(PropuestaFecha(
                                    it.fila, it.fecha, faltan[0], it.medio, it.monto_bs,
                                    f"El monto {it.monto_bs} coincide exactamente con los {len(creditos[dia])} cobros "
                                    f"del banco del {dia:%d/%m}, día que no tiene fila en la caja."))
        for dia, xs in creditos.items():
            for x in xs:
                usados.add((banco, x.indice))
                sin_caja.append((banco, x.indice, f"Cobro de pago móvil del {dia:%d/%m} sin día en el cierre de caja"))

    for medio in cierre.medios:
        its = cierre.items_de(medio)
        tipo, banco, modo = its[0].tipo, its[0].banco, its[0].modo
        if tipo == PAGO_MOVIL and modo == "total_diario" and banco in clasificados:
            por_total_diario(its, banco)
        elif tipo == PAGO_MOVIL and banco in clasificados:
            buscar(its, [banco], {E_PAGO_MOVIL, E_TRANSF}, es_credito=True)
        elif tipo == VUELTO:
            buscar(its, list(clasificados), {S_PAGO_MOVIL, S_TRANSF}, es_credito=False, solo_exacto=True)

    # Créditos de pago móvil del banco que no aparecen en caja.
    bancos_pm = {i.banco for i in cierre.items if i.tipo == PAGO_MOVIL}
    for b in bancos_pm & set(clasificados):
        for x in clasificados[b]:
            if x.naturaleza == E_PAGO_MOVIL and x.mov.credito and libre(b, x):
                sin_caja.append((b, x.indice, "Cobro de pago móvil sin registro en el cierre de caja"))

    lineas.sort(key=lambda l: (l.medio, l.fecha))
    asientos = _cruzar_libro(cierre, conciliaciones, lineas, config)
    _aplicar(conciliaciones, lineas, asientos)
    return ResultadoCaja(cierre, lineas, sin_caja, asientos, totales_mes, propuestas)


# ---------------------------------------------------------------- Caja ↔ libro
_MEDIO_POR_REF = [
    (r"M[OÓ]VIL", "Pago móvil {banco}"),
    (r"^D[EÉ]BITO", "T. debito {banco}"),
    (r"^CR[EÉ]DITO", "T. credito {banco}"),
    (r"VUELTO", "Vueltos"),
]
_NOMBRE_BANCO = {"100_BANCO": "100% BANCO", "BNC": "BNC", "BANPLUS": "BANPLUS"}


def _cruce(medios: list[str], its: list[ItemCaja], usd_libro: Decimal) -> tuple[Decimal, Optional[dt.date], bool, str]:
    """Compara US$ del libro con la caja: mes completo, o hasta una fecha (faltan días en el libro)."""
    nombre = " + ".join(f"«{m}»" for m in medios)
    total = sum((i.usd for i in its), Decimal(0)).quantize(CERO)
    if total == usd_libro:
        return total, its[-1].fecha, True, f"Igual al total del mes de {nombre} en el cierre de caja."
    acumulado, hasta = Decimal(0), None
    for i in its:
        acumulado += i.usd
        if acumulado.quantize(CERO) == usd_libro:
            hasta = i.fecha
    if hasta:
        faltan = [i for i in its if i.fecha > hasta]
        f_usd = sum((i.usd for i in faltan), Decimal(0)).quantize(CERO)
        f_bs = sum((i.monto_bs for i in faltan), CERO)
        return total, hasta, True, (f"Cubre {nombre} del {its[0].fecha:%d/%m} al {hasta:%d/%m}. "
                                    f"Faltan en el libro: {', '.join(sorted({f'{i.fecha:%d/%m}' for i in faltan}))} "
                                    f"(US$ {f_usd} = Bs. {f_bs}).")
    return total, None, False, (f"No coincide con {nombre}: caja US$ {total} vs. libro US$ {usd_libro} "
                                f"(diferencia libro − caja {usd_libro - total}).")


def _cruzar_libro(cierre: CierreCaja, conc: dict[str, ResultadoConciliacion],
                  lineas: list[LineaCaja], config=None) -> list[CruceAsiento]:
    out: list[CruceAsiento] = []
    if config is not None and config.asientos_resumen:
        for regla in config.asientos_resumen:
            its = sorted((i for m in regla.medios for i in cierre.items_de(m)), key=lambda i: i.fecha)
            elegidos = [(b, j, a) for b, patron in regla.asientos if b in conc
                        for j, a in enumerate(conc[b].libro.asientos)
                        if a.debito_usd and re.search(patron, a.descripcion, re.I)]
            if not elegidos:
                continue
            usd = sum((a.monto_usd for _, _, a in elegidos), CERO)
            if not its:
                for b, j, a in elegidos:
                    out.append(CruceAsiento(b, j, None, a.monto_usd, CERO, None, False,
                                            "No hay columna equivalente en el cierre de caja."))
                continue
            total, hasta, ok, nota = _cruce(regla.medios, its, usd)
            if len(elegidos) > 1:
                nota = (f"Suma de {len(elegidos)} asientos ("
                        + " + ".join(f"{b} US$ {a.monto_usd}" for b, _, a in elegidos) + f" = US$ {usd}). " + nota)
            for b, j, a in elegidos:
                out.append(CruceAsiento(b, j, " + ".join(regla.medios), a.monto_usd, total, hasta, ok, nota, usd))
        medios_cruce = {m for c in out if c.conciliado for m in (c.medio or "").split(" + ")}
        for l in lineas:
            nombres = {i.medio for i in l.items}
            l.en_libro = bool(nombres) and nombres <= medios_cruce and all(
                any(l.fecha <= c.hasta for c in out if c.conciliado and m in (c.medio or "").split(" + "))
                for m in nombres)
        return out
    for b, r in conc.items():
        for j, a in enumerate(r.libro.asientos):
            if not a.es_resumen:
                continue
            medio = None
            for patron, plantilla in _MEDIO_POR_REF:
                if re.search(patron, a.referencia.upper()):
                    medio = plantilla.format(banco=_NOMBRE_BANCO.get(b, b))
                    break
            its = sorted(cierre.items_de(medio), key=lambda i: i.fecha) if medio else []
            if not its:
                out.append(CruceAsiento(b, j, medio, a.monto_usd, CERO, None, False,
                                        "No hay columna equivalente en el cierre de caja."))
                continue
            total = sum((i.usd for i in its), Decimal(0)).quantize(CERO)
            if total == a.monto_usd:
                out.append(CruceAsiento(b, j, medio, a.monto_usd, total, its[-1].fecha, True,
                                        f"Igual al total del mes de «{medio}» en el cierre de caja."))
                continue
            acumulado, hasta = Decimal(0), None
            for i in its:
                acumulado += i.usd
                if acumulado.quantize(CERO) == a.monto_usd:
                    hasta = i.fecha
            if hasta:
                faltan = [i for i in its if i.fecha > hasta]
                f_usd = sum((i.usd for i in faltan), Decimal(0)).quantize(CERO)
                f_bs = sum((i.monto_bs for i in faltan), CERO)
                out.append(CruceAsiento(b, j, medio, a.monto_usd, total, hasta, True,
                                        f"Cubre «{medio}» del {its[0].fecha:%d/%m} al {hasta:%d/%m}. "
                                        f"Faltan en el libro: {', '.join(f'{i.fecha:%d/%m}' for i in faltan)} "
                                        f"(US$ {f_usd} = Bs. {f_bs})."))
            else:
                out.append(CruceAsiento(b, j, medio, a.monto_usd, total, None, False,
                                        f"No coincide con «{medio}»: caja US$ {total} vs. libro US$ {a.monto_usd} "
                                        f"(diferencia {a.monto_usd - total})."))
    for l in lineas:
        nombres = [i.medio for i in l.items]
        cruces = [c for c in out if c.medio in nombres and c.conciliado]
        l.en_libro = bool(cruces) and all(any(c.medio == m and l.fecha <= c.hasta for c in cruces) for m in nombres)
    return out


def _aplicar(conc: dict[str, ResultadoConciliacion], lineas: list[LineaCaja],
             asientos: list[CruceAsiento]) -> None:
    """Pasa a «Conciliado vía cierre de caja» lo que quedó cubierto por caja + libro."""
    for c in asientos:
        r = conc[c.banco]
        p = r.estado_asiento[c.asiento]
        if p.estado is EP.RESUMEN_SIN_MONTO and c.conciliado:
            p.estado = EP.CONCILIADO_CAJA
            p.nota = c.nota
        elif p.estado is EP.RESUMEN_SIN_MONTO:
            p.nota = (p.nota + " · " if p.nota else "") + c.nota
    hay_asiento = {m for c in asientos for m in (c.medio or "").split(" + ")}
    for l in lineas:
        for b, i in l.movs:
            p = conc[b].estado_mov[i]
            if p.estado is not EP.SOLO_BANCO:
                continue
            if l.estado is EstadoCaja.DIFERENCIA_DIA:
                p.nota = f"Caja {l.medio}: diferencia en el día {l.fecha:%d/%m} (ver hoja Cierre de caja)"
                continue
            if l.estado not in CONCILIADOS_CAJA | {EstadoCaja.TOTAL_MES}:
                continue
            nombres = {it.medio for it in l.items}
            if l.en_libro or (l.estado is EstadoCaja.TOTAL_MES and nombres & hay_asiento):
                p.estado = EP.CONCILIADO_CAJA
            else:
                p.estado = EP.CAJA_SIN_LIBRO
            p.nota = (f"Caja: total del mes de {l.medio}" if l.estado is EstadoCaja.TOTAL_MES
                      else f"Caja {l.fecha:%d/%m} {l.medio} {l.monto}")
            if p.estado is EP.CAJA_SIN_LIBRO:
                p.nota += " · el día no está en el asiento resumen del libro"
