"""
Informe climatológico de España (últimos N días) - AEMET OpenData

Uso:
    python aemet_informe.py                  # Últimos 7 días (por defecto)
    python aemet_informe.py --dias 14        # Últimos 14 días
    python aemet_informe.py --dias 3 --csv   # 3 días y exportar CSV
    python aemet_informe.py --sin-navegador  # No abrir el navegador al terminar

Variables de entorno requeridas (fichero .env o entorno del sistema):
    AEMET_API_KEY=<tu_api_key>

Requisitos:
    pip install -r requirements.txt
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import logging
import os
import sys
import time
import webbrowser
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv
from jinja2 import Environment, FileSystemLoader

# ---------------------------------------------------------------
# CONFIGURACIÓN DE LOGGING
# ---------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("aemet_informe.log", encoding="utf-8"),
    ],
)
log = logging.getLogger(__name__)

# ---------------------------------------------------------------
# CONSTANTES
# ---------------------------------------------------------------
BASE_URL = "https://opendata.aemet.es/opendata/api"
CACHE_DIR = Path(".cache_aemet")
CACHE_TTL_SEGUNDOS = 3600          # 1 hora
MAX_REINTENTOS = 4
BACKOFF_BASE = 2.0                  # segundos; se duplica en cada reintento


# ---------------------------------------------------------------
# CARGA DE CONFIGURACIÓN
# ---------------------------------------------------------------
def cargar_api_key() -> str:
    """
    Lee la API key exclusivamente desde variables de entorno o fichero .env.
    Lanza EnvironmentError si no está definida — nunca usa fallback hardcodeado.
    """
    load_dotenv()
    api_key = os.environ.get("AEMET_API_KEY", "").strip()
    if not api_key:
        raise EnvironmentError(
            "La variable de entorno AEMET_API_KEY no está definida.\n"
            "Crea un fichero .env con: AEMET_API_KEY=<tu_clave>"
        )
    return api_key


# ---------------------------------------------------------------
# CACHÉ LOCAL
# ---------------------------------------------------------------
def _clave_cache(endpoint: str) -> Path:
    """Genera una ruta de fichero de caché basada en el hash del endpoint."""
    CACHE_DIR.mkdir(exist_ok=True)
    nombre = hashlib.md5(endpoint.encode()).hexdigest() + ".json"
    return CACHE_DIR / nombre


def _leer_cache(endpoint: str) -> list[dict] | None:
    """Devuelve los datos en caché si existen y son recientes; si no, None."""
    ruta = _clave_cache(endpoint)
    if not ruta.exists():
        return None
    edad = time.time() - ruta.stat().st_mtime
    if edad > CACHE_TTL_SEGUNDOS:
        log.debug("Caché expirada para %s (%.0f s)", endpoint, edad)
        return None
    log.info("Usando caché local (%.0f s de antigüedad).", edad)
    return json.loads(ruta.read_text(encoding="utf-8"))


def _escribir_cache(endpoint: str, datos: list[dict]) -> None:
    """Persiste los datos en caché."""
    ruta = _clave_cache(endpoint)
    ruta.write_text(json.dumps(datos, ensure_ascii=False), encoding="utf-8")
    log.debug("Caché guardada en %s", ruta)


# ---------------------------------------------------------------
# CLIENTE HTTP CON REINTENTOS Y BACKOFF EXPONENCIAL
# ---------------------------------------------------------------
def _get_con_reintentos(url: str, **kwargs) -> requests.Response:
    """
    Realiza una petición GET con reintentos automáticos ante errores
    transitorios (429, 5xx, timeouts).  Usa backoff exponencial.
    """
    for intento in range(1, MAX_REINTENTOS + 1):
        try:
            resp = requests.get(url, timeout=30, **kwargs)
            if resp.status_code == 429:
                espera = BACKOFF_BASE ** intento
                log.warning("Rate limit (429). Esperando %.1f s (intento %d/%d)…", espera, intento, MAX_REINTENTOS)
                time.sleep(espera)
                continue
            resp.raise_for_status()
            return resp
        except requests.exceptions.Timeout:
            espera = BACKOFF_BASE ** intento
            log.warning("Timeout en intento %d/%d. Reintentando en %.1f s…", intento, MAX_REINTENTOS, espera)
            time.sleep(espera)
        except requests.exceptions.HTTPError as exc:
            if exc.response is not None and exc.response.status_code < 500:
                raise   # Errores 4xx no son transitorios (salvo 429, ya manejado)
            espera = BACKOFF_BASE ** intento
            log.warning("Error HTTP %s en intento %d/%d. Reintentando en %.1f s…",
                        exc.response.status_code if exc.response else "?",
                        intento, MAX_REINTENTOS, espera)
            time.sleep(espera)

    raise RuntimeError(f"No se pudo completar la petición a {url} tras {MAX_REINTENTOS} intentos.")


def obtener_datos(endpoint: str, api_key: str, usar_cache: bool = True) -> list[dict]:
    """
    Petición en dos pasos que exige la API de AEMET.
    Usa caché local para evitar re-descargas innecesarias.
    Detecta automáticamente la codificación de la respuesta.
    """
    if usar_cache:
        cached = _leer_cache(endpoint)
        if cached is not None:
            return cached

    url = f"{BASE_URL}{endpoint}"
    log.info("Consultando AEMET: %s", url)

    # Paso 1: obtener la URL real de los datos
    resp1 = _get_con_reintentos(url, params={"api_key": api_key})
    body = resp1.json()

    if body.get("estado") != 200 or "datos" not in body:
        raise RuntimeError(f"Respuesta inesperada de AEMET: {body}")

    # Paso 2: descargar los datos reales
    resp2 = _get_con_reintentos(body["datos"])

    # Detección automática de codificación
    encoding = resp2.apparent_encoding or "utf-8"
    log.debug("Codificación detectada: %s", encoding)
    datos = json.loads(resp2.content.decode(encoding, errors="replace"))

    if usar_cache:
        _escribir_cache(endpoint, datos)

    return datos


# ---------------------------------------------------------------
# UTILIDADES DE CONVERSIÓN
# ---------------------------------------------------------------
def a_numero(valor: Any) -> float | None:
    """
    Convierte el formato de AEMET a float.

    - "12,3"  → 12.3
    - "Ip"    →  0.0  (precipitación inapreciable)
    - None/"" → None

    >>> a_numero("12,3")
    12.3
    >>> a_numero("Ip")
    0.0
    >>> a_numero(None) is None
    True
    >>> a_numero("abc") is None
    True
    """
    if valor is None or valor == "":
        return None
    if str(valor).strip() == "Ip":
        return 0.0
    try:
        return float(str(valor).replace(",", "."))
    except ValueError:
        return None


def obtener_rango_fechas(dias_atras: int) -> tuple[str, str]:
    """
    Devuelve (fecha_inicio, fecha_fin) en formato ISO requerido por AEMET.

    >>> inicio, fin = obtener_rango_fechas(7)
    >>> inicio.endswith("UTC")
    True
    """
    fin = datetime.utcnow()
    inicio = fin - timedelta(days=dias_atras)
    fmt = "%Y-%m-%dT00:00:00UTC"
    return inicio.strftime(fmt), fin.strftime(fmt)


# ---------------------------------------------------------------
# RECOPILACIÓN Y NORMALIZACIÓN
# ---------------------------------------------------------------
def recopilar_datos_espana(api_key: str, dias_atras: int, usar_cache: bool = True) -> list[dict]:
    """Descarga y normaliza los registros diarios de todas las estaciones."""
    fecha_ini, fecha_fin = obtener_rango_fechas(dias_atras)
    endpoint = (
        f"/valores/climatologicos/diarios/datos"
        f"/fechaini/{fecha_ini}/fechafin/{fecha_fin}/todasestaciones"
    )
    log.info("Rango de fechas: %s → %s", fecha_ini, fecha_fin)
    registros_crudos = obtener_datos(endpoint, api_key, usar_cache=usar_cache)

    registros: list[dict] = []
    for r in registros_crudos:
        registros.append({
            "fecha":        r.get("fecha", ""),
            "estacion":     r.get("nombre", ""),
            "provincia":    r.get("provincia", ""),
            "latitud":      a_numero(r.get("latitud")),
            "longitud":     a_numero(r.get("longitud")),
            "altitud":      a_numero(r.get("altitud")),
            "tmax":         a_numero(r.get("tmax")),
            "tmin":         a_numero(r.get("tmin")),
            "viento_medio": a_numero(r.get("velmedia")),
            "racha":        a_numero(r.get("racha")),
            "prec":         a_numero(r.get("prec")),
        })

    log.info("Registros normalizados: %d", len(registros))
    return registros


# ---------------------------------------------------------------
# CÁLCULO DE EXTREMOS
# ---------------------------------------------------------------
def calcular_extremos(registros: list[dict]) -> dict:
    """
    Calcula los valores extremos nacionales.

    >>> recs = [
    ...     {"tmax": 35.0, "tmin": 10.0, "racha": 80.0, "prec": 50.0,
    ...      "estacion": "A", "provincia": "X", "fecha": "2024-01-01"},
    ...     {"tmax": 20.0, "tmin": 2.0,  "racha": 40.0, "prec": 5.0,
    ...      "estacion": "B", "provincia": "Y", "fecha": "2024-01-02"},
    ... ]
    >>> extremos = calcular_extremos(recs)
    >>> extremos["tmax"]["tmax"]
    35.0
    >>> extremos["tmin"]["tmin"]
    2.0
    """
    def extremo(campo: str, maximo: bool = True) -> dict | None:
        validos = [r for r in registros if r.get(campo) is not None]
        if not validos:
            return None
        return max(validos, key=lambda r: r[campo]) if maximo else min(validos, key=lambda r: r[campo])

    return {
        "tmax":  extremo("tmax",  maximo=True),
        "tmin":  extremo("tmin",  maximo=False),
        "racha": extremo("racha", maximo=True),
        "prec":  extremo("prec",  maximo=True),
    }


def calcular_series_temporales(registros: list[dict]) -> dict:
    """
    Agrega medias diarias nacionales para los gráficos de tendencia.
    Devuelve un dict con listas {fechas, tmax_media, tmin_media, prec_total}.
    """
    por_fecha: dict[str, dict] = {}
    for r in registros:
        fecha = r["fecha"]
        if fecha not in por_fecha:
            por_fecha[fecha] = {"tmax": [], "tmin": [], "prec": []}
        for campo in ("tmax", "tmin", "prec"):
            if r[campo] is not None:
                por_fecha[fecha][campo].append(r[campo])

    fechas_ord = sorted(por_fecha.keys())

    def media(lista: list[float]) -> float | None:
        return round(sum(lista) / len(lista), 1) if lista else None

    return {
        "fechas":      fechas_ord,
        "tmax_media":  [media(por_fecha[f]["tmax"]) for f in fechas_ord],
        "tmin_media":  [media(por_fecha[f]["tmin"]) for f in fechas_ord],
        "prec_total":  [round(sum(por_fecha[f]["prec"]), 1) if por_fecha[f]["prec"] else None
                        for f in fechas_ord],
    }


# ---------------------------------------------------------------
# EXPORTACIÓN CSV
# ---------------------------------------------------------------
def exportar_csv(registros: list[dict], ruta: Path) -> None:
    """Exporta todos los registros a un fichero CSV."""
    campos = ["fecha", "estacion", "provincia", "latitud", "longitud",
              "altitud", "tmax", "tmin", "viento_medio", "racha", "prec"]
    with ruta.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=campos, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(registros)
    log.info("CSV exportado: %s (%d filas)", ruta, len(registros))


# ---------------------------------------------------------------
# GENERACIÓN HTML (via Jinja2)
# ---------------------------------------------------------------
def construir_html(
    registros: list[dict],
    extremos: dict,
    series: dict,
    dias_atras: int,
) -> str:
    """Renderiza la plantilla Jinja2 con todos los datos."""
    dias_disponibles = sorted({r["fecha"] for r in registros}, reverse=True)

    env = Environment(
        loader=FileSystemLoader(Path(__file__).parent),
        autoescape=True,
    )
    template = env.get_template("template.html")

    return template.render(
        registros=registros,
        extremos=extremos,
        series=series,
        dias_atras=dias_atras,
        dias_disponibles=dias_disponibles,
        generado=datetime.now().strftime("%d/%m/%Y %H:%M"),
        series_json=json.dumps(series, ensure_ascii=False),
    )


# ---------------------------------------------------------------
# PUNTO DE ENTRADA
# ---------------------------------------------------------------
def parsear_argumentos() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Genera un informe climatológico de España usando AEMET OpenData."
    )
    parser.add_argument(
        "--dias", type=int, default=7, metavar="N",
        help="Número de días hacia atrás a consultar (por defecto: 7)."
    )
    parser.add_argument(
        "--csv", action="store_true",
        help="Exportar también los datos en formato CSV."
    )
    parser.add_argument(
        "--sin-cache", action="store_true",
        help="Forzar descarga aunque exista caché local reciente."
    )
    parser.add_argument(
        "--sin-navegador", action="store_true",
        help="No abrir el informe en el navegador al terminar."
    )
    parser.add_argument(
        "--salida", type=Path, default=Path("informe_espana.html"),
        help="Ruta del fichero HTML de salida."
    )
    return parser.parse_args()


def main() -> None:
    args = parsear_argumentos()

    # Seguridad: API key solo desde entorno
    api_key = cargar_api_key()

    registros = recopilar_datos_espana(
        api_key=api_key,
        dias_atras=args.dias,
        usar_cache=not args.sin_cache,
    )

    if not registros:
        log.error("No se obtuvieron registros. Revisa la conexión o la API key.")
        sys.exit(1)

    extremos = calcular_extremos(registros)
    series   = calcular_series_temporales(registros)
    html     = construir_html(registros, extremos, series, args.dias)

    args.salida.write_text(html, encoding="utf-8")
    log.info("Informe HTML generado: %s", args.salida.resolve())

    if args.csv:
        ruta_csv = args.salida.with_suffix(".csv")
        exportar_csv(registros, ruta_csv)

    if not args.sin_navegador:
        webbrowser.open(args.salida.resolve().as_uri())


if __name__ == "__main__":
    try:
        main()
    except EnvironmentError as e:
        log.critical("Error de configuración: %s", e)
        sys.exit(1)
    except RuntimeError as e:
        log.critical("Error de ejecución: %s", e)
        sys.exit(1)
    except KeyboardInterrupt:
        log.info("Interrumpido por el usuario.")
        sys.exit(0)