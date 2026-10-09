"""CACAO septiembre 2026: formatos nuevos (PDF de Plaza «ESTADO DE CUENTAS» y libro «reporte»)."""
from decimal import Decimal as D
from pathlib import Path

import pytest

from cvp_parser.cuadre import cuadrar
from cvp_parser.lectores import LECTORES
from cvp_parser.sistema import leer_libro

FIX = Path(__file__).parent / "fixtures" / "cacao_2026_09"
pytestmark = pytest.mark.skipif(not (FIX / "edo_plaza.pdf").exists(), reason="faltan los archivos reales de CACAO sept.")


def test_plaza_formato_nuevo():
    e = LECTORES["PLAZA"].leer([FIX / "edo_plaza.pdf"]).extractos[0]
    assert (e.cuenta, e.titular) == ("0138************7448", "JOHANA COROMOTO GIL GALINDEZ")
    assert (str(e.desde), str(e.hasta), len(e.movimientos)) == ("2026-09-01", "2026-09-30", 385)
    assert e.saldo_anterior == D("53696.15")            # = saldo final real de agosto
    assert e.movimientos[-1].saldo == D("227890.43") and not e.errores_lectura
    assert e.movimientos[0].referencia == "0390100252"
    (r,) = cuadrar([e])
    assert not r.diferencias                              # saldo corrido línea a línea


def test_libro_reporte():
    b = leer_libro(FIX / "sistema_banplus.xls")
    assert len(b.asientos) == 45
    assert sum(a.credito_usd for a in b.asientos) == D("7889.73")
    assert sum(a.monto_bs for a in b.asientos) == D("5676700.65")
    assert not any(a.debito_usd for a in b.asientos) and len(b.avisos) == 2
    p = leer_libro(FIX / "sistema_plaza.xls")
    assert (len(p.asientos), sum(a.monto_bs for a in p.asientos)) == (67, D("16634772.30"))


def test_pdf_con_extension_de_excel():
    """Un Mayor en PDF guardado como .xls se lee como PDF (desde el soporte de Mayor en PDF), con aviso."""
    lib = leer_libro(FIX / "sistema_efectivo.xls")
    assert any("PDF" in a for a in lib.avisos) and lib.asientos and not lib.diferencias_saldo
    assert lib.saldo_inicial_usd + sum(a.debito_usd - a.credito_usd for a in lib.asientos) == lib.saldo_final_usd


def test_mayor_sin_columna_de_debitos():
    """Sept. 2026: el Mayor omite la columna Débitos (mes sin entradas) y todo queda corrido a la izquierda."""
    for mayor, reporte, ini, fin in [("mayor_banplus.xls", "sistema_banplus.xls", "583.70", "-7306.03"),
                                     ("mayor_plaza.xls", "sistema_plaza.xls", "67.54", "-19949.44")]:
        m = leer_libro(FIX / mayor)
        assert (m.saldo_inicial_usd, m.saldo_final_usd) == (D(ini), D(fin))
        assert not m.diferencias_saldo and not any(a.debito_usd for a in m.asientos) and m.avisos
        r = leer_libro(FIX / reporte)
        clave = lambda l: sorted((a.fecha, a.monto_bs, a.credito_usd) for a in l.asientos)
        assert clave(m) == clave(r)                    # mismos asientos que el export «reporte»


def test_referencia_como_texto_con_coma():
    m = leer_libro(FIX / "mayor_banplus.xls")
    (a,) = [a for a in m.asientos if a.fila == 22]
    assert a.monto_bs == D("152637.69")


def test_banplus_sept_archivo_sin_dos_movimientos():
    """El export de Banplus de sept. no cuadra por sí mismo: faltan 2 movimientos del 30/09 (neto −2.557,25).
    No se ajusta: queda como «no cuadra». El período es septiembre aunque traiga 2 movimientos del 01/10."""
    e = LECTORES["BANPLUS"].leer([FIX / "edo_banplus.xlsx"]).extractos[0]
    assert (str(e.desde), str(e.hasta), len(e.movimientos)) == ("2026-09-01", "2026-09-30", 1034)
    assert not e.errores_lectura and "01/10/2026" in e.avisos_lectura[0]
    (r,) = cuadrar([e])
    assert r.estado.value == "no_cuadra"
    assert [d.tipo.value for d in r.diferencias] == ["saldo_linea", "saldo_linea", "nuevo_saldo"]
    assert "diferencia 2.557,25" in r.diferencias[-1].mensaje


def test_pago_movil_fin_de_semana_mismo_dia():
    """Sept. 2026: Banplus abona el pago móvil el mismo sábado/domingo; no se debe correr al lunes."""
    from cvp_parser.proceso import procesar_cliente
    from cvp_parser.revision import aplicar
    rep = procesar_cliente("CACAO", "2026-09", [("BANPLUS", FIX / "edo_banplus.xlsx", FIX / "mayor_banplus.xls")],
                           cierre_caja=FIX / "ventas.xlsx")
    pm = [l for l in rep.caja.lineas if l.items[0].medio == "Pago móvil"]
    assert len(pm) == 30 and sum(l.estado.value == "Conciliado" for l in pm) == 20
    assert not [p for p in aplicar(rep).pendientes if p.tipo == "Cobros sin día de caja"]


@pytest.fixture(scope="module")
def rv_sept():
    from cvp_parser.proceso import procesar_cliente
    from cvp_parser.revision import aplicar
    rep = procesar_cliente("CACAO", "2026-09", [("BANPLUS", FIX / "edo_banplus.xlsx", FIX / "mayor_banplus.xls"),
                                                 ("PLAZA", FIX / "edo_plaza.pdf", FIX / "mayor_plaza.xls")],
                           cierre_caja=FIX / "ventas.xlsx")
    return aplicar(rep)


def _buscar(rv, tipo, texto):
    return [p for p in rv.pendientes if p.tipo.startswith(tipo) and texto in (p.descripcion + p.explicacion)]


def test_diagnostico_todas_las_partidas_explicadas(rv_sept):
    assert all(p.explicacion and p.que_hacer and p.sugerencia for p in rv_sept.pendientes)
    assert not [p for p in rv_sept.pendientes if p.explicacion.startswith("Partida que la conciliación")]


def test_diagnostico_factura_en_la_referencia(rv_sept):
    """Las 4 facturas con el número de factura en la Referencia se emparejan con su pago en Banplus."""
    esperado = {"36930": "107.244,80", "37011": "138.615,74", "778": "8.116,92", "38024": "97.113,95"}
    for fact, monto in esperado.items():
        [p] = _buscar(rv_sept, "Solo en libro", f"FACT {fact}")
        assert "número de factura" in p.explicacion and monto in p.que_hacer
        assert p.sugerencia == "Corregido en el sistema"
    # Los movimientos emparejados ya no se listan aparte como «solo en banco».
    assert not [p for p in rv_sept.pendientes if p.tipo.startswith("Solo en banco")
                and any(r in p.descripcion for r in ("92117469532", "90117480942", "93017541954", "90217901738"))]


def test_diagnostico_hueco_banplus_30_09(rv_sept):
    ps = [p for p in rv_sept.pendientes if p.tipo == "Estado de cuenta no cuadra" and p.banco == "BANPLUS"]
    assert ps and all("55.257,80" in p.explicacion and "57.815,05" in p.explicacion and "-2.557,25" in p.explicacion
                      and "le falten movimientos" in p.explicacion for p in ps)


def test_diagnostico_traslado_persona_y_sin_beneficiario(rv_sept):
    [sal] = _buscar(rv_sept, "Solo en banco: Traslados a cuentas propias", "0063444863")
    [ent] = _buscar(rv_sept, "Solo en banco: Traslados desde cuentas propias", "164063444863")
    assert "hacia Banplus" in sal.explicacion and "viene de Plaza" in ent.explicacion
    dominico = _buscar(rv_sept, "Solo en banco: Pagos por transferencia", "DOMINICO")
    assert len(dominico) == 3 and all("COMPRA DE 1000$" in p.explicacion for p in dominico)
    [lol] = _buscar(rv_sept, "Solo en banco: Pagos por transferencia", "LOLIMAR")
    assert "227.000,00" in lol.explicacion
    [suelto] = _buscar(rv_sept, "Solo en banco: Pagos por transferencia", "90918099412")
    assert suelto.monto_bs == D("-42783.00") and "no informa a quién" in suelto.explicacion


def test_diagnostico_caja_y_libro_sin_entradas(rv_sept):
    [d30] = [p for p in rv_sept.pendientes if p.tipo == "Caja: Diferencia en el día" and p.fecha.day == 30]
    assert "2.580,97" in d30.explicacion and "dos veces" in d30.explicacion
    [d07] = [p for p in rv_sept.pendientes if p.tipo == "Caja: Diferencia en el día" and p.fecha.day == 7]
    assert d07.sugerencia == "Aceptar"
    assert {p.banco for p in rv_sept.pendientes if p.tipo == "Libro sin entradas en el mes"} == {"BANPLUS", "PLAZA"}


def test_diagnostico_no_empareja_con_comisiones():
    """WEI REST: un asiento nunca se propone como pareja de una comisión o cargo del banco."""
    import test_wei_rest as tw
    from cvp_parser.proceso import procesar_cliente
    from cvp_parser.revision import aplicar
    rv = aplicar(procesar_cliente("WEI REST", "2026-08", tw.ARCHIVOS, cierre_caja=tw.VENTAS))
    assert not [p for p in rv.pendientes if "Comision" in p.explicacion and p.tipo == "Solo en libro"]
    [k] = [p for p in rv.pendientes if p.descripcion.startswith("KOZMOS")]
    assert "10.622,93" in k.explicacion and "-200,00" in k.explicacion



def test_comisiones_e_islr_aparte(tmp_path):
    """WEI/CACAO: comisiones, cargos e ISLR no se concilian movimiento a movimiento; van aparte, un total
    por banco y categoría (con su desglose por tipo) y una hoja propia en el Excel."""
    import openpyxl
    import test_wei_rest as tw
    from cvp_parser.cargos import por_conciliar
    from cvp_parser.exportar import excel_conciliacion
    from cvp_parser.naturaleza import S_COMISION, S_ISLR
    from cvp_parser.proceso import procesar_cliente
    from cvp_parser.revision import aplicar
    rep = procesar_cliente("WEI REST", "2026-08", tw.ARCHIVOS)
    cats = por_conciliar(rep)
    bnc = next(c for c in cats if c.banco == "BNC" and c.nombre == S_COMISION)
    # Total exacto = suma de todos los movimientos de comisiones de BNC (ninguno quedó conciliado).
    todos = [x.mov for x in rep.clasificados["BNC"] if x.naturaleza == S_COMISION]
    assert bnc.total == sum((m.credito - m.debito for m in todos), D("0")) and len(bnc.movimientos) == len(todos)
    assert {t.nombre for t in bnc.tipos} >= {"Comisión Credito Inmediato", "Comisión Pago Movil"}
    rv = aplicar(rep)
    ps = [p for p in rv.pendientes if p.tipo.startswith("Por conciliar en el sistema")]
    assert {(p.banco, p.tipo.split(": ", 1)[1]) for p in ps} >= {("BNC", S_COMISION), ("BNC", S_ISLR)}
    assert not [p for p in rv.pendientes if p.tipo in (f"Solo en banco: {S_COMISION}", f"Solo en banco: {S_ISLR}")]
    p = next(p for p in ps if p.banco == "BNC" and p.tipo.endswith(S_COMISION))
    assert p.monto_bs == bnc.total and p.sugerencia == "Aceptar" and "Comisión Pago Movil" in p.explicacion
    salida = excel_conciliacion(rep, tmp_path / "x.xlsx", rv)
    ws = openpyxl.load_workbook(salida)["Comisiones e ISLR"]
    textos = [c.value for row in ws.iter_rows() for c in row if isinstance(c.value, str)]
    assert f"Total {S_COMISION}" in textos and f"Gran total {S_COMISION}" in textos and "Detalle de movimientos" in textos
