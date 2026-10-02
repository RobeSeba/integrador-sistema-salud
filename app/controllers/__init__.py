"""Controladores del sistema SIBS.

La logica de negocio vive en app.models; aqui solo se traducen peticiones
HTTP a llamadas de modelo y se eligen las plantillas.
"""

from .auth_controller import auth_bp
from .admin_controller import admin_bp
from .analisis_controller import analisis_bp
from .api_controller import api_bp
from .tablero_controller import tablero_bp

__all__ = [
    "auth_bp",
    "admin_bp",
    "analisis_bp",
    "api_bp",
    "tablero_bp",
]
