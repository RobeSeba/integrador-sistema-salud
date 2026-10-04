"""Configuracion del sistema SIBS (brechas de capacidad sanitaria).

Los valores pueden sobreescribirse por variables de entorno para no depender
de credenciales fijas en el codigo fuente.
"""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
INSTANCE_DIR = BASE_DIR / "instance"


def _bool(nombre, defecto=False):
    valor = os.environ.get(nombre)
    if valor is None:
        return defecto
    return valor.strip().lower() in ("1", "true", "t", "yes", "si", "s")


class Config:
    # --- General -----------------------------------------------------------
    SECRET_KEY = os.environ.get("SIBS_SECRET_KEY", "sibs-brechas-capacidad-sanitaria-2024")
    APP_NAME = "SIBS"
    APP_TITULO = (
        "Sistema de Informacion para la Identificacion y Priorizacion "
        "de Brechas de Capacidad Sanitaria"
    )
    APP_SUBTITULO = "Establecimientos de Salud del Peru"

    # --- Base de datos (SQL Server / pyodbc) --------------------------------
    DB_DRIVER = os.environ.get("SIBS_DB_DRIVER", "ODBC Driver 17 for SQL Server")
    DB_SERVER = os.environ.get("SIBS_DB_SERVER", r"localhost")
    DB_NAME = os.environ.get("SIBS_DB_NAME", "SaludBrechasDB")
    DB_TRUSTED_CONNECTION = os.environ.get("SIBS_DB_TRUSTED", "yes")
    DB_TRUST_CERT = os.environ.get("SIBS_DB_TRUST_CERT", "yes")
    DB_UID = os.environ.get("SIBS_DB_UID") or None
    DB_PWD = os.environ.get("SIBS_DB_PWD") or None
    DB_POOL_SIZE = int(os.environ.get("SIBS_DB_POOL_SIZE", "8"))
    DB_TIMEOUT = int(os.environ.get("SIBS_DB_TIMEOUT", "30"))

    # --- Parametros por defecto de los filtros ------------------------------
    FECHA_INICIO_DEFECTO = os.environ.get("SIBS_FECHA_INICIO", "2023-01-01")
    FECHA_FIN_DEFECTO = os.environ.get("SIBS_FECHA_FIN", "2023-12-31")
    UMBRAL_OCUPACION_DEFECTO = float(os.environ.get("SIBS_UMBRAL_OCUPACION", "85"))

    # --- Carga de archivos ---------------------------------------------------
    UPLOAD_FOLDER = os.environ.get(
        "SIBS_UPLOAD_FOLDER", str(INSTANCE_DIR / "cargas")
    )
    MAX_CONTENT_LENGTH = int(os.environ.get("SIBS_MAX_UPLOAD_MB", "60")) * 1024 * 1024
    EXTENSIONES_PERMITIDAS = {"csv", "xlsx", "xls", "txt"}

    # --- Paginacion / exportacion -------------------------------------------
    FILAS_POR_PAGINA = int(os.environ.get("SIBS_FILAS_PAGINA", "50"))
    MAXIMO_EXPORTAR = int(os.environ.get("SIBS_MAX_EXPORTAR", "50000"))

    # --- Roles --------------------------------------------------------------
    ROLES = {
        "ADMINISTRADOR": {
            "nombre": "Administrador",
            "descripcion": "Gestion de usuarios, cargas de datos y reglas de priorizacion.",
            "color": "#7c3aed",
        },
        "FUNCIONARIO": {
            "nombre": "Funcionario",
            "descripcion": "Rankings, detalle de establecimientos y reportes para gestion.",
            "color": "#0d9488",
        },
        "ANALISTA_SANITARIO": {
            "nombre": "Analista sanitario",
            "descripcion": "Consulta territorial de afiliados, atenciones y capacidad.",
            "color": "#0284c7",
        },
        "ANALISTA_DATOS": {
            "nombre": "Analista de datos",
            "descripcion": "Analisis comparativo, series temporales y exploracion de datos.",
            "color": "#9333ea",
        },
        "MONITOREO": {
            "nombre": "Responsable de monitoreo",
            "descripcion": "Vigilancia de ocupacion critica e inoperatividad de recursos.",
            "color": "#dc2626",
        },
    }

    @classmethod
    def connection_string(cls):
        partes = [
            f"DRIVER={{{cls.DB_DRIVER}}};",
            f"SERVER={cls.DB_SERVER};",
            f"DATABASE={cls.DB_NAME};",
        ]
        if cls.DB_TRUSTED_CONNECTION.lower() in ("yes", "1", "true"):
            partes.append("Trusted_Connection=yes;")
        else:
            partes.append(f"UID={cls.DB_UID};")
            partes.append(f"PWD={cls.DB_PWD};")
        if cls.DB_TRUST_CERT.lower() in ("yes", "1", "true"):
            partes.append("TrustServerCertificate=yes;")
        partes.append(f"Connection Timeout={cls.DB_TIMEOUT};")
        partes.append("APP=SIBS;")
        return "".join(partes)


class ProduccionConfig(Config):
    DEBUG = False
    TESTING = False


class DesarrolloConfig(Config):
    DEBUG = _bool("SIBS_DEBUG", True)
    TESTING = False


class PruebasConfig(Config):
    DEBUG = False
    TESTING = True


CONFIGURACIONES = {
    "produccion": ProduccionConfig,
    "desarrollo": DesarrolloConfig,
    "pruebas": PruebasConfig,
}


def obtener_config(nombre=None):
    nombre = nombre or os.environ.get("SIBS_ENV", "desarrollo")
    return CONFIGURACIONES.get(nombre, DesarrolloConfig)