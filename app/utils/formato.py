"""Utilidades de formato para las plantillas y exportaciones."""

from datetime import date, datetime
from decimal import Decimal


def _a_numero(valor):
    if valor is None or valor == "":
        return None
    if isinstance(valor, (int, float, Decimal)):
        return float(valor)
    try:
        return float(str(valor).replace(",", ""))
    except (TypeError, ValueError):
        return None


def formato_numero(valor, decimales=0, sufijo=""):
    """1234567 -> '1,234,567'"""
    numero = _a_numero(valor)
    if numero is None:
        return "-"
    if decimales:
        texto = f"{numero:,.{decimales}f}"
    else:
        texto = f"{round(numero):,}"
    return texto + sufijo


def formato_porcentaje(valor, decimales=1, con_signo=False):
    """0.4287 -> '42.9'  (se espera la razon, no el porcentaje)."""
    numero = _a_numero(valor)
    if numero is None:
        return "-"
    if abs(numero) <= 1.5:
        numero *= 100.0
    prefijo = "+" if con_signo and numero > 0 else ""
    return f"{prefijo}{numero:,.{decimales}f}"


def formato_fecha(valor, con_hora=False):
    if valor is None or valor == "":
        return "-"
    if isinstance(valor, str):
        return valor
    if isinstance(valor, datetime):
        return valor.strftime("%d/%m/%Y %H:%M") if con_hora else valor.strftime("%d/%m/%Y")
    if isinstance(valor, date):
        return valor.strftime("%d/%m/%Y")
    return str(valor)


def formato_bytes(valor):
    numero = _a_numero(valor) or 0
    for unidad in ("B", "KB", "MB", "GB"):
        if numero < 1024 or unidad == "GB":
            return f"{numero:,.1f} {unidad}".replace(".0 ", " ")
        numero /= 1024.0
    return f"{numero:,.1f} GB"
