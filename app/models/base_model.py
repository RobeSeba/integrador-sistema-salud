"""Utilidades comunes de la capa Model: conversion de filas y helpers SQL."""

import re
from datetime import date, datetime
from decimal import Decimal

from ..database.bd import conexion

# Sentencias que modifican datos. Si se ejecutan por `consultar` sin commit,
# el pool hace rollback al devolver la conexion y el cambio se pierde en
# silencio; por eso se bloquea ese camino y se obliga a usar `ejecutar` o a
# pasar commit=True de forma explicita.
# Se ignoran los literales de texto para no confundir un mensaje como
# 'DELETE FROM ...' con una instruccion real.
_LITERAL = re.compile(r"'[^']*'")
_ES_ESCRITURA = re.compile(
    r"\b(INSERT|UPDATE|DELETE|MERGE|TRUNCATE|DROP|ALTER|CREATE)\b", re.I
)


def _es_escritura(sql):
    return bool(_ES_ESCRITURA.search(_LITERAL.sub("''", sql or "")))


class BaseModel:
    """Clase base con helpers para ejecutar consultas parametrizadas.

    Todos los modelos de la aplicacion heredan de aqui para mantener una unica
    forma de parametrizar y leer resultados desde pyodbc.
    """

    @staticmethod
    def _filas(cursor):
        columnas = [d[0] for d in cursor.description] if cursor.description else []
        return [dict(zip(columnas, fila)) for fila in cursor.fetchall()]

    @classmethod
    def consultar(cls, sql, params=None, commit=False):
        """Ejecuta una consulta y devuelve una lista de diccionarios.

        Es un metodo de solo lectura: rechaza INSERT/UPDATE/DELETE/MERGE si no
        se pasa ``commit=True``, porque en ese caso la transaccion se perderia
        al devolver la conexion al pool.
        """
        if not commit and _es_escritura(sql):
            raise ValueError(
                "consultar() solo lee: use ejecutar() para escribir, o pase "
                "commit=True de forma explicita."
            )
        with conexion() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute(sql, params or ())
                resultado = cls._filas(cursor) if cursor.description else []
            finally:
                cursor.close()
            if commit:
                conn.commit()
            return resultado

    @classmethod
    def consultar_uno(cls, sql, params=None, commit=False):
        """Ejecuta una consulta y devuelve la primera fila o None."""
        filas = cls.consultar(sql, params, commit=commit)
        return filas[0] if filas else None

    @classmethod
    def consultar_valor(cls, sql, params=None, default=None, commit=False):
        """Devuelve el primer valor de la primera fila."""
        fila = cls.consultar_uno(sql, params, commit=commit)
        if not fila:
            return default
        valor = next(iter(fila.values()), default)
        return default if valor is None else valor

    @classmethod
    def ejecutar(cls, sql, params=None):
        """Ejecuta INSERT/UPDATE/DELETE en una transaccion y devuelve n filas."""
        with conexion() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute(sql, params or ())
                afectadas = cursor.rowcount
            finally:
                cursor.close()
            conn.commit()
        return afectadas

    @classmethod
    def escalar(cls, sql, params=None, default=None):
        return cls.consultar_valor(sql, params, default=default)

    @classmethod
    def conjuntos(cls, sql, params=None):
        """Devuelve (columnas, filas) tal cual, util para exportaciones."""
        with conexion() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute(sql, params or ())
                columnas = [d[0] for d in cursor.description] if cursor.description else []
                filas = cursor.fetchall()
            finally:
                cursor.close()
            return columnas, filas

    @classmethod
    def conjuntos_multiples(cls, sql, params=None):
        """Devuelve una lista de (columnas, filas): procedure con varios resultsets."""
        with conexion() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute(sql, params or ())
                resultados = []
                while True:
                    if cursor.description:
                        columnas = [d[0] for d in cursor.description]
                        resultados.append((columnas, cursor.fetchall()))
                    if not cursor.nextset():
                        break
            finally:
                cursor.close()
            return resultados


def a_python(valor):
    """Convierte tipos de pyodbc a tipos nativos de Python."""
    if isinstance(valor, Decimal):
        return float(valor)
    if isinstance(valor, datetime):
        return valor.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(valor, date):
        return valor.isoformat()
    return valor


def normalizar_filas(filas):
    """Aplica `a_python` a todos los valores de una lista de diccionarios."""
    return [{k: a_python(v) for k, v in fila.items()} for fila in filas]


def normalizar_conjuntos(columnas, filas):
    """Normaliza un conjunto de resultados (columnas, filas)."""
    return columnas, [tuple(a_python(v) for v in fila) for fila in filas]


def identificadores(columnas):
    return ", ".join(f"[{c}]" for c in columnas)


def placeholders(cantidad):
    return ", ".join(["?"] * max(0, int(cantidad)))


def limpiar_texto(valor, por_defecto=""):
    if valor is None:
        return por_defecto
    texto = str(valor).strip()
    return texto if texto else por_defecto