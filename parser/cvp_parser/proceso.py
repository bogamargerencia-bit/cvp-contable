"""Proceso completo de un cliente para un período: leer → cuadrar → clasificar → conciliar.

    python -m cvp_parser.proceso --cliente "WEI REST" --periodo 2026-08 \\
        --banco 100_BANCO edo_100.pdf sistema_100.xls \\
        --banco BNC edo_bnc.xls sistema_bnc.xls \\
        --banco BANPLUS edo_banplus.xlsx sistema_banplus.xls \\
        -o WEI_REST_2026-08_conciliacion.xlsx
"""
from __future__ import annotations

import argparse
import datetime as dt
import re
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Optional

from .conciliacion import CONCILIADOS, EstadoPartida, ResultadoConciliacion, conciliar_cliente
from .conciliacion_caja import ResultadoCaja, conciliar_caja
from .cuadre import ResultadoCuadre, cuadrar
from .lectores import LECTORES
from .modelo import Extracto
from .naturaleza import S_NOMINA, S_TRANSF, MovClasificado, clasificar_extracto, marcar_traslados
from .sistema import LibroBanco, leer_libro
from .ventas import leer_cierre_caja


@dataclass
class ReporteCliente:
    cliente: str
    periodo: str
    bancos: list[str]
    cuadres: dict[str, ResultadoCuadre]
    libros: dict[str, LibroBanco]
    clasificados: dict[str, list[MovClasificado]]
    conciliaciones: dict[str, ResultadoConciliacion]
    alertas: list[str] = field(default_factory=list)
    caja: Optional["ResultadoCaja"] = None
    divisas: list = field(default_factory=list)          # divisas.ResultadoCuenta
    kardex: Optional[object] = None
    cruces_divisas_bancos: list[str] = field(default_factory=list)


def procesar_cliente(cliente: str, periodo: str,
                     archivos: list[tuple[str, Path, Path]], dias: int = 5,
                     tolerancia_monto: Decimal = Decimal("1.00"),
                     cierre_caja: Optional[Path] = None,
                     correcciones_caja: Optional[dict] = None,
                     libros_divisas: Optional[dict[str, Path]] = None,
                     kardex: Optional[Path] = None) -> ReporteCliente:
    """archivos: [(banco, estado_de_cuenta, export_del_sistema), ...]
    cierre_caja: Excel de ventas diarias (opcional) para conciliar los cobros."""
    extractos: dict[str, Extracto] = {}
    libros: dict[str, LibroBanco] = {}
    alertas: list[str] = []
    for banco, edo, sist in archivos:
        lector = LECTORES[banco]
        res = lector.leer([Path(edo)])
        if len(res.extractos) != 1:
            raise ValueError(f"{banco}: se esperaba 1 extracto en {edo}, hay {len(res.extractos)}")
        extractos[banco] = res.extractos[0]
        libros[banco] = leer_libro(Path(sist))

    cuadres = {r.extracto.banco: r for r in cuadrar(extractos.values())}
    clasificados = {b: clasificar_extracto(e) for b, e in extractos.items()}
    marcar_traslados(clasificados.values())
    conc = conciliar_cliente([(extractos[b], libros[b]) for b in extractos], dias=dias,
                             tolerancia_monto=tolerancia_monto,
                             naturalezas={b: {x.indice: x.naturaleza for x in l} for b, l in clasificados.items()})

    # El banco no distingue nómina de otras transferencias (salvo BNC). Si el movimiento quedó
    # emparejado con un asiento del libro que dice NÓMINA, se reclasifica como nómina.
    for b, lista in clasificados.items():
        r = conc[b]
        for x in lista:
            p = r.estado_mov.get(x.indice)
            if x.naturaleza == S_TRANSF and p and p.estado in CONCILIADOS | {EstadoPartida.DIFERENCIA_MONTO}:
                if any(re.search(r"N[OÓ]MINA", r.libro.asientos[j].descripcion, re.I) for j in p.asientos):
                    x.naturaleza = S_NOMINA
                    x.contraparte = "naturaleza tomada del libro (asiento de nómina)"

    caja = None
    if cierre_caja is not None:
        from .clientes import config_de
        cfg = config_de(cliente)
        cierre = leer_cierre_caja(Path(cierre_caja), medios=cfg.medios if cfg and cfg.medios else None,
                                  correcciones=correcciones_caja)
        for err in cierre.errores:
            alertas.append(f"Cierre de caja: {err}")
        caja = conciliar_caja(cierre, clasificados, conc, config=cfg)
        for t in caja.totales_mes:
            alertas.append(f"Tarjetas ({' + '.join(t.medios)}): {t.nota}")
        for c in caja.asientos:
            a = conc[c.banco].libro.asientos[c.asiento]
            nombre = a.descripcion if a.referencia in ("", "0") or a.monto_bs is not None else a.referencia
            if (c.conciliado and c.hasta and "Faltan en el libro" in c.nota) or not c.conciliado:
                alertas.append(f"{c.banco}: asiento «{nombre}» — {c.nota}")

    for b in extractos:
        c = cuadres[b]
        if c.diferencias:
            alertas.append(f"{b}: el estado de cuenta NO cuadra ({len(c.diferencias)} diferencias).")
        for d in libros[b].diferencias_saldo:
            alertas.append(f"{b}: el saldo del export del sistema no es consistente → {d}")
        for x in libros[b].avisos:
            alertas.append(f"{b}: {x}")
    rep = ReporteCliente(cliente, periodo, list(extractos), cuadres, libros, clasificados, conc, alertas, caja)
    if libros_divisas:
        _divisas(rep, libros_divisas, kardex, cierre_caja)
    return rep


def _divisas(rep: ReporteCliente, archivos: dict[str, Path], kardex: Optional[Path],
             ventas: Optional[Path]) -> None:
    """Cuentas en divisas: ventas ↔ libro ↔ Kardex (ver divisas.py) y venta de dólares ↔ bancos."""
    from .clientes import config_de
    from .divisas import conciliar_divisas, leer_ventas_divisas
    from .kardex import leer_kardex
    cfg = config_de(rep.cliente)
    if cfg is None or not cfg.divisas:
        raise ValueError(f"{rep.cliente}: no hay cuentas en divisas configuradas en clientes.py")
    nombres = {c.nombre.upper(): c.nombre for c in cfg.divisas}
    libros = {}
    for k, ruta in archivos.items():
        nombre = nombres.get(k.upper()) or next((v for kk, v in nombres.items() if k.upper() in kk), None)
        if nombre is None:
            raise ValueError(f"Cuenta en divisas «{k}» no configurada (opciones: {', '.join(nombres.values())})")
        libros[nombre] = leer_libro(Path(ruta))
    kx = leer_kardex(Path(kardex)) if kardex else None
    vd = leer_ventas_divisas(Path(ventas), cfg.divisas) if ventas else None
    rep.kardex = kx
    rep.divisas = conciliar_divisas(cfg.divisas, libros, vd, kx)
    for r in rep.divisas:
        for d in r.libro.diferencias_saldo:
            rep.alertas.append(f"{r.cuenta.nombre}: el saldo del libro no es consistente → {d}")
        if not r.ventas_ok:
            rep.alertas.append(f"{r.cuenta.nombre}: {r.ventas_nota}")
    # Venta de dólares: salidas de las cuentas en divisas con la misma descripción que una entrada
    # en el libro de un banco (± 1 día). Se compara lo vendido en US$ con lo que registra el banco.
    salidas: dict[tuple[str, dt.date], list] = {}
    for r in rep.divisas:
        for a in r.libro.asientos:
            if a.credito_usd:
                salidas.setdefault((_norm(a.descripcion), a.fecha), []).append((r.cuenta.nombre, a))
    for b in rep.bancos:
        for a in rep.libros[b].asientos:
            if not a.debito_usd or a.monto_bs is None:
                continue
            for (desc, f), lst in salidas.items():
                if desc == _norm(a.descripcion) and abs((f - a.fecha).days) <= 1:
                    usd = sum((x.credito_usd for _, x in lst), Decimal("0.00"))
                    tasa_venta = (a.monto_bs / usd).quantize(Decimal("0.01"))
                    rep.cruces_divisas_bancos.append(
                        f"«{a.descripcion}» {a.fecha:%d/%m}: salieron US$ {usd} de "
                        + " + ".join(f"{n} {x.credito_usd}" for n, x in lst)
                        + f"; {b} recibió Bs. {a.monto_bs} (tasa de venta {tasa_venta}) y su libro lo registra "
                        f"como US$ {a.debito_usd} (tasa {a.tasa_implicita}); diferencia US$ {a.debito_usd - usd}.")


def _norm(t: str) -> str:
    return re.sub(r"\s+", " ", (t or "").upper()).strip()


def main() -> None:
    ap = argparse.ArgumentParser(description="Cuadre, naturaleza y conciliación de un cliente")
    ap.add_argument("--cliente", required=True)
    ap.add_argument("--periodo", required=True, help="AAAA-MM")
    ap.add_argument("--banco", nargs=3, action="append", required=True,
                    metavar=("BANCO", "ESTADO_DE_CUENTA", "EXPORT_SISTEMA"))
    ap.add_argument("--dias", type=int, default=5)
    ap.add_argument("--ventas", help="Excel del cierre de caja diario (opcional)")
    ap.add_argument("--revision", help="Excel emitido por la app en la corrida anterior, con las decisiones")
    ap.add_argument("--divisa", nargs=2, action="append", metavar=("CUENTA", "EXPORT_SISTEMA"),
                    help="libro en US$ de una cuenta en divisas (p. ej. «Zelle» SISTEMA_ZELLE.XLS)")
    ap.add_argument("--kardex", help="Kardex de tesorería en divisas (opcional)")
    ap.add_argument("-o", "--salida", required=True)
    a = ap.parse_args()
    from .exportar import excel_conciliacion
    from .revision import aplicar, correcciones_caja, leer_revision
    anterior = leer_revision(Path(a.revision)) if a.revision else None
    rep = procesar_cliente(a.cliente, a.periodo, [(b, Path(e), Path(s)) for b, e, s in a.banco], dias=a.dias,
                           cierre_caja=Path(a.ventas) if a.ventas else None,
                           correcciones_caja=correcciones_caja(anterior) if anterior else None,
                           libros_divisas={c: Path(f) for c, f in a.divisa} if a.divisa else None,
                           kardex=Path(a.kardex) if a.kardex else None)
    rv = aplicar(rep, anterior)
    excel_conciliacion(rep, Path(a.salida), rv)
    for b in rep.bancos:
        c = rep.cuadres[b]
        print(f"{b:10} cuadre: {c.estado.value}")
        for k, v in rep.conciliaciones[b].resumen().items():
            print(f"    {k.value:38} banco {v[0]:4}  libro {v[1]:4}")
    for al in rep.alertas:
        print("ATENCIÓN:", al)
    from collections import Counter
    print(f"Revisión corrida {rv.corrida}: {'OK GENERAL' if rv.ok_general else 'CON PENDIENTES'} · "
          + ", ".join(f"{k.value}: {v}" for k, v in Counter(p.situacion for p in rv.pendientes).items())
          + f" · resueltas: {len(rv.resueltas)}")
    for adv in rv.advertencias:
        print("ATENCIÓN:", adv)
    print("Excel:", a.salida)


if __name__ == "__main__":
    main()
