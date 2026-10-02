"""Generacion de descargas CSV y XLSX a partir de las filas de los modelos."""

import csv
import io
from datetime import date, datetime
from decimal import Decimal

from flask import Response, current_app

from ..utils.formato import _a_numero

# Columnas que se exportan como fecha (las demas se dejan como texto).
_COLUMNAS_FECHA = (
    "fecha", "periodo", "fecha_inicio", "fecha_fin", "fecha_carga",
    "fecha_dato", "fecha_creacion", "fecha_actualizacion", "ultimo_acceso",
)

# Sufijo de unidad por nombre de columna, para que el archivo sea legible.
_SUFIJOS = {
    "total_afiliados": "SIS",
    "afiliados_rural": "SIS",
    "afiliados_rim": "SIS",
    "total_atenciones": "atenciones",
    "atenciones_emergencia": "atenciones",
    "camas_operativas": "camas",
    "camas_disponibles": "camas",
    "camas_ocupadas": "camas",
}


def _texto_celda(valor):
    """Convierte cualquier valor de pyodbc a algo escribible en la hoja."""
    if valor is None:
        return ""
    if isinstance(valor, bool):
        return "SI" if valor else "NO"
    if isinstance(valor, (datetime, date)):
        return valor.strftime("%Y-%m-%d") if not isinstance(valor, datetime) \
            else valor.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(valor, Decimal):
        return float(valor)
    if isinstance(valor, float):
        return round(valor, 4)
    return valor


def _encabezados(filas):
    if not filas:
        return []
    # normalizar_filas devuelve dicts, pero se acepta una lista de tuplas.
    if isinstance(filas[0], dict):
        return list(filas[0].keys())
    return [f"col_{i + 1}" for i in range(len(filas[0]))]


def _sufijo(columna):
    if columna in _SUFIJOS:
        return f" [{_SUFIJOS[columna]}]"
    if columna.endswith("pct"):
        return " [%]"
    return ""


def construir_csv(filas, nombre_archivo):
    columnas = _encabezados(filas)
    buffer = io.StringIO()
    # utf-8-sig + ';' para que Excel en espanol abra los acentos y las columnas.
    buffer.write("\ufeff")
    escritor = csv.writer(buffer, delimiter=";", lineterminator="\r\n")
    escritor.writerow([f"{c}{_sufijo(c)}" for c in columnas])
    for fila in filas:
        if isinstance(fila, dict):
            escritor.writerow([_texto_celda(fila.get(c)) for c in columnas])
        else:
            escritor.writerow([_texto_celda(v) for v in fila])
    return Response(
        buffer.getvalue().encode("utf-8"),
        mimetype="text/csv; charset=utf-8",
        headers=_cabeceras(nombre_archivo, "csv"),
    )


def construir_xlsx(filas, nombre_archivo, titulo=None):
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    columnas = _encabezados(filas)
    libro = Workbook()
    hoja = libro.active
    hoja.title = "Datos"

    fila_inicio = 1
    if titulo:
        hoja.cell(row=1, column=1, value=titulo).font = Font(bold=True, size=13)
        fila_inicio = 3

    estilo_encabezado = Font(bold=True, color="FFFFFF")
    relleno = PatternFill("solid", fgColor="0F4C81")
    for indice, columna in enumerate(columnas, start=1):
        celda = hoja.cell(row=fila_inicio, column=indice,
                          value=f"{columna}{_sufijo(columna)}")
        celda.font = estilo_encabezado
        celda.fill = relleno
        celda.alignment = Alignment(vertical="center", wrap_text=True)

    for indice_fila, fila in enumerate(filas, start=fila_inicio + 1):
        valores = (
            [fila.get(c) for c in columnas]
            if isinstance(fila, dict)
            else list(fila)
        )
        for indice_col, valor in enumerate(valores, start=1):
            hoja.cell(row=indice_fila, column=indice_col, value=_texto_celda(valor))

    # Ancho de columna aproximado segun el contenido mas largo.
    for indice, columna in enumerate(columnas, start=1):
        largos = [len(str(columna)) + len(_sufijo(columna))]
        for fila in filas[:200]:
            valor = fila.get(columna) if isinstance(fila, dict) else fila[indice - 1]
            largos.append(min(len(str(_texto_celda(valor))), 60))
        hoja.column_dimensions[get_column_letter(indice)].width = min(
            max(largos) + 2, 45
        )
    hoja.freeze_panes = hoja.cell(row=fila_inicio + 1, column=1)

    buffer = io.BytesIO()
    libro.save(buffer)
    return Response(
        buffer.getvalue(),
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers=_cabeceras(nombre_archivo, "xlsx"),
    )


def _cabeceras(nombre_archivo, extension):
    limite = current_app.config["SIBS_CONFIG"].MAXIMO_EXPORTAR
    return {
        "Content-Disposition": f'attachment; filename="{nombre_archivo}.{extension}"',
        "X-Export-Limite": str(limite),
    }


def construir_exportacion(filas, formato, nombre_archivo, titulo=None):
    """Despacha al formato pedido y aplica el limite de filas configurado."""
    formato = (formato or "csv").lower()
    if formato not in ("csv", "xlsx", "excel"):
        formato = "csv"

    limite = current_app.config["SIBS_CONFIG"].MAXIMO_EXPORTAR
    if filas and len(filas) > limite:
        filas = filas[:limite]

    if formato == "csv":
        return construir_csv(filas, nombre_archivo)
    return construir_xlsx(filas, nombre_archivo, titulo)


def filas_a_dataframe(filas):
    """Utilidad para Dependencias opcionales de pandas."""
    import pandas as pd

    return pd.DataFrame(filas)
