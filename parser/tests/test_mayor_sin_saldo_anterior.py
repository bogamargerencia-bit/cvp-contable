"""Mayor en Excel sin columna de débitos y con «Saldo Anterior:» vacío (Shiro, Bancamiga sept. 2026).

El sistema omite la columna de débitos cuando el mes no tiene entradas y todo queda corrido a la izquierda
(como CACAO). Si además la cuenta arranca sin saldo, la celda del Saldo Anterior viene vacía: antes eso
impedía detectar el corrimiento y las salidas se leían como entradas («Sentido invertido»).
"""
import datetime as dt
from decimal import Decimal as D

import openpyxl
import pytest

from cvp_parser.sistema import ENCABEZADO, leer_libro


def _mayor(tmp_path, saldo_anterior, con_linea_cuenta=True):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["SHIRO ALIMENTOS, C.A. ($)"])
    ws.append(ENCABEZADO)
    if con_linea_cuenta:
        # Corrida: «Saldo Anterior:» en la columna F (índice 5) y su valor en G (vacío si no hay saldo).
        ws.append(["Cuenta:", "1102003", "", "BANCAMIGA", "", "Saldo Anterior:", saldo_anterior, ""])
    s = D(saldo_anterior or 0)
    for dia, ref, desc, monto in [(8, 301924.11, "NE 7997 HIPERPOLLO VALENCIA, CENTRO LOMITO", "370.60"),
                                  (25, 400000.00, "COMPRA DIVISAS", "467.47"),
                                  (25, 500000.00, "COMPRA DIVISAS", "584.34")]:
        s -= D(monto)
        # Columnas corridas: monto en E (índice 4), saldo en G (índice 6); F y H vacías.
        ws.append([dt.datetime(2026, 9, dia), "20260900000004", ref, desc, float(monto), "", float(s), ""])
    ws.append(["", "", "", "Totales:", 1422.41, "", float(s), ""])
    ruta = tmp_path / "MOVIMIENTOS DEL SISTEMA BANCAMIGA SHIRO.xlsx"
    wb.save(ruta)
    return ruta


@pytest.mark.parametrize("saldo_anterior", ["", 0])
def test_sin_saldo_anterior_las_salidas_siguen_siendo_salidas(tmp_path, saldo_anterior):
    lb = leer_libro(_mayor(tmp_path, saldo_anterior))
    assert [a.credito_usd for a in lb.asientos] == [D("370.60"), D("467.47"), D("584.34")]
    assert not any(a.debito_usd for a in lb.asientos)
    assert all(a.es_salida for a in lb.asientos)
    assert lb.saldo_inicial_usd == D("0.00") and lb.saldo_final_usd == D("-1422.41")
    assert lb.diferencias_saldo == []
    assert [a.monto_bs for a in lb.asientos] == [D("301924.11"), D("400000.00"), D("500000.00")]


def test_con_saldo_anterior_sigue_funcionando(tmp_path):
    lb = leer_libro(_mayor(tmp_path, 1000))
    assert lb.saldo_inicial_usd == D("1000.00") and lb.saldo_final_usd == D("-422.41")
    assert all(a.es_salida for a in lb.asientos) and lb.diferencias_saldo == []


def test_columnas_corridas_sin_linea_cuenta(tmp_path):
    """Red de seguridad: sin la línea «Cuenta:», el corrimiento se detecta por las filas."""
    lb = leer_libro(_mayor(tmp_path, "", con_linea_cuenta=False))
    assert all(a.es_salida for a in lb.asientos)
    assert any("corridas" in x for x in lb.avisos)
