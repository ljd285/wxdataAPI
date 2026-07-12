"""
Tests unitarios para las funciones de utilidad de aemet_informe.py
Ejecutar con: pytest tests/
"""

import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from aemet_informe import a_numero, obtener_rango_fechas, calcular_extremos, calcular_series_temporales


# ──────────────────────────────────────────────
# a_numero
# ──────────────────────────────────────────────
class TestANumero:
    def test_entero(self):
        assert a_numero("25") == 25.0

    def test_decimal_coma(self):
        assert a_numero("12,3") == pytest.approx(12.3)

    def test_decimal_punto(self):
        assert a_numero("12.3") == pytest.approx(12.3)

    def test_ip_precipitacion(self):
        assert a_numero("Ip") == 0.0

    def test_none(self):
        assert a_numero(None) is None

    def test_cadena_vacia(self):
        assert a_numero("") is None

    def test_texto_invalido(self):
        assert a_numero("abc") is None

    def test_negativo(self):
        assert a_numero("-5,2") == pytest.approx(-5.2)

    def test_float_directo(self):
        assert a_numero(10.5) == pytest.approx(10.5)


# ──────────────────────────────────────────────
# obtener_rango_fechas
# ──────────────────────────────────────────────
class TestObtenerRangoFechas:
    def test_formato_correcto(self):
        inicio, fin = obtener_rango_fechas(7)
        assert inicio.endswith("UTC")
        assert fin.endswith("UTC")

    def test_inicio_antes_que_fin(self):
        from datetime import datetime
        fmt = "%Y-%m-%dT00:00:00UTC"
        inicio, fin = obtener_rango_fechas(7)
        assert datetime.strptime(inicio, fmt) < datetime.strptime(fin, fmt)

    def test_dias_cero(self):
        from datetime import datetime
        fmt = "%Y-%m-%dT00:00:00UTC"
        inicio, fin = obtener_rango_fechas(0)
        assert datetime.strptime(inicio, fmt) <= datetime.strptime(fin, fmt)


# ──────────────────────────────────────────────
# calcular_extremos
# ──────────────────────────────────────────────
REGISTROS_MUESTRA = [
    {"tmax": 35.0, "tmin": 10.0, "racha": 80.0, "prec": 50.0,
     "estacion": "Est-A", "provincia": "Prov-X", "fecha": "2024-07-01"},
    {"tmax": 20.0, "tmin": -2.0, "racha": 120.0, "prec": 5.0,
     "estacion": "Est-B", "provincia": "Prov-Y", "fecha": "2024-07-02"},
    {"tmax": None, "tmin": 5.0,  "racha": None,  "prec": 200.0,
     "estacion": "Est-C", "provincia": "Prov-Z", "fecha": "2024-07-03"},
]

class TestCalcularExtremos:
    def test_tmax(self):
        ext = calcular_extremos(REGISTROS_MUESTRA)
        assert ext["tmax"]["tmax"] == 35.0
        assert ext["tmax"]["estacion"] == "Est-A"

    def test_tmin(self):
        ext = calcular_extremos(REGISTROS_MUESTRA)
        assert ext["tmin"]["tmin"] == -2.0
        assert ext["tmin"]["estacion"] == "Est-B"

    def test_racha_ignora_none(self):
        ext = calcular_extremos(REGISTROS_MUESTRA)
        assert ext["racha"]["racha"] == 120.0

    def test_prec_max(self):
        ext = calcular_extremos(REGISTROS_MUESTRA)
        assert ext["prec"]["prec"] == 200.0

    def test_sin_datos(self):
        ext = calcular_extremos([{"tmax": None, "tmin": None, "racha": None, "prec": None,
                                   "estacion": "", "provincia": "", "fecha": ""}])
        assert ext["tmax"] is None


# ──────────────────────────────────────────────
# calcular_series_temporales
# ──────────────────────────────────────────────
class TestCalcularSeriesTemporales:
    def test_fechas_ordenadas(self):
        series = calcular_series_temporales(REGISTROS_MUESTRA)
        assert series["fechas"] == sorted(series["fechas"])

    def test_media_tmax(self):
        series = calcular_series_temporales(REGISTROS_MUESTRA)
        idx = series["fechas"].index("2024-07-01")
        assert series["tmax_media"][idx] == pytest.approx(35.0)

    def test_prec_total(self):
        series = calcular_series_temporales(REGISTROS_MUESTRA)
        idx = series["fechas"].index("2024-07-03")
        assert series["prec_total"][idx] == pytest.approx(200.0)

    def test_none_cuando_sin_datos(self):
        registros = [{"fecha": "2024-07-01", "tmax": None, "tmin": None, "prec": None}]
        series = calcular_series_temporales(registros)
        assert series["tmax_media"][0] is None