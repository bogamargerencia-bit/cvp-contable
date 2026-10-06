from decimal import Decimal

import pytest

from cvp_parser.montos import MontoInvalido, a_monto, formato_ve, monto_us, monto_ve


@pytest.mark.parametrize("texto,esperado", [
    ("1.234.567,89", "1234567.89"),
    ("0,05", "0.05"),
    ("473.509,11", "473509.11"),
    ("6.035,00", "6035.00"),
    ("-1.502,44", "-1502.44"),
    ("1.502,44-", "-1502.44"),
    ("1502,44", "1502.44"),
    (",50", "0.50"),
])
def test_monto_ve(texto, esperado):
    assert monto_ve(texto) == Decimal(esperado)


@pytest.mark.parametrize("texto", ["1,234.56", "1.234,5", "12.34,56", "abc", "", "1.234"])
def test_monto_ve_rechaza_formatos_raros(texto):
    with pytest.raises(MontoInvalido):
        monto_ve(texto)


@pytest.mark.parametrize("texto,esperado", [
    ("1,502.44", "1502.44"),
    ("379805.45", "379805.45"),
    ("1,234,567.89", "1234567.89"),
])
def test_monto_us(texto, esperado):
    assert monto_us(texto) == Decimal(esperado)


def test_a_monto_rechaza_float():
    with pytest.raises(MontoInvalido, match="float"):
        a_monto(0.1)


def test_a_monto_no_redondea():
    with pytest.raises(MontoInvalido, match="más de 2 decimales"):
        a_monto(Decimal("1.005"))


def test_a_monto_acepta_int_y_texto():
    assert a_monto(5) == Decimal("5.00")
    assert a_monto("12.30") == Decimal("12.30")


def test_suma_exacta_sin_errores_de_float():
    # Con float, 0.1 + 0.2 != 0.3. Con Decimal sí cuadra al céntimo.
    assert monto_ve("0,10") + monto_ve("0,20") == monto_ve("0,30")


def test_formato_ve():
    assert formato_ve(Decimal("1234567.89")) == "1.234.567,89"
    assert formato_ve(Decimal("-6035")) == "-6.035,00"
