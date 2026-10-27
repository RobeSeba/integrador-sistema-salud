"""Ejecutor de migraciones SQL (idempotentes) y siembra de datos base."""

import re

import pyodbc

from .bd import conexion, ruta_sql

_SEPARADOR = re.compile(r"^\s*GO\s*;?\s*$", re.IGNORECASE | re.MULTILINE)


def dividir_lotes(script: str):
    """Divide un script SQL por los separadores GO conservando el orden."""
    lotes = []
    for bloque in _SEPARADOR.split(script):
        if bloque.strip():
            lotes.append(bloque)
    return lotes


def listar_migraciones():
    carpeta = ruta_sql()
    return sorted(p for p in carpeta.glob("*.sql"))


def ejecutar_migraciones(verbose=True):
    """Ejecuta todos los scripts .sql de la carpeta migrations."""
    aplicadas = []
    archivos = listar_migraciones()
    if not archivos:
        raise RuntimeError(
            f"No se encontraron scripts .sql en la carpeta de migraciones: {ruta_sql()}"
        )
    with conexion() as conn:
        cursor = conn.cursor()
        for archivo in archivos:
            script = archivo.read_text(encoding="utf-8")
            for lote in dividir_lotes(script):
                cursor.execute(lote)
                # Los PRINT de los scripts se pierden; no es critico.
            conn.commit()
            aplicadas.append(archivo.name)
            if verbose:
                print(f"  [OK] {archivo.name}")
        cursor.close()
    return aplicadas


def _password_hash(password):
    from werkzeug.security import generate_password_hash

    return generate_password_hash(password)


def sembrar_datos_base(password_admin="admin123", verbose=True):
    """Crea el usuario administrador por defecto si la tabla esta vacia."""
    from ..models.admin_model import AdminModel

    with conexion() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM dbo.sys_usuarios")
        total = cursor.fetchone()[0]
        cursor.close()

        if total == 0:
            AdminModel.crear_usuario(
                usuario="admin",
                password=password_admin,
                nombre_completo="Administrador del Sistema",
                rol="ADMINISTRADOR",
                email="admin@sibs.pe",
                cargo="Administrador de plataforma",
            )
            if verbose:
                print(f"  [OK] Usuario administrador creado (usuario: admin)")
        elif verbose:
            print(f"  [--] sys_usuarios ya tiene {total} registro(s)")
    return total


# Usuarios funcionales por rol. Son idempotentes: si el usuario del rol ya
# existe, no se toca. Las contrasenas son provisionales y el hash se guarda,
# por eso la clave en claro no queda en la base.
USUARIOS_ROL = [
    {
        "usuario": "analista",
        "password": "analista123",
        "nombre_completo": "Analista Sanitario SIBS",
        "rol": "ANALISTA_SANITARIO",
        "email": "analista@sibs.pe",
        "cargo": "Analista sanitario regional",
    },
    {
        "usuario": "planificacion",
        "password": "planifica123",
        "nombre_completo": "Funcionario de Planificacion SIBS",
        "rol": "FUNCIONARIO",
        "email": "planificacion@sibs.pe",
        "cargo": "Funcionario de planificacion",
    },
    {
        "usuario": "monitoreo",
        "password": "monitorea123",
        "nombre_completo": "Responsable de Monitoreo SIBS",
        "rol": "MONITOREO",
        "email": "monitoreo@sibs.pe",
        "cargo": "Responsable de monitoreo",
    },
]


def sembrar_usuarios_role(verbose=True):
    """Crea los usuarios funcionales de cada rol si no existen.

    Cada usuario recibe su conjunto completo de modulos en
    dbo.sys_permisos_usuario (seguridad.MODULOS_POR_ROL), de modo que el
    administrador puede ajustarlo luego usuario por usuario.
    """
    from ..modulos import MODULOS, MODULOS_POR_ROL
    from ..models.admin_model import AdminModel

    creados = 0
    for datos in USUARIOS_ROL:
        existe = AdminModel.consultar_uno(
            "SELECT id_usuario FROM dbo.sys_usuarios WHERE usuario = ?",
            [datos["usuario"]],
        )
        if existe:
            continue
        creado = AdminModel.crear_usuario(
            usuario=datos["usuario"],
            password=datos["password"],
            nombre_completo=datos["nombre_completo"],
            rol=datos["rol"],
            email=datos["email"],
            cargo=datos["cargo"],
        )
        AdminModel.fijar_modulos(
            creado["id_usuario"],
            list(MODULOS_POR_ROL.get(datos["rol"], set()) & set(MODULOS)),
        )
        creados += 1
        if verbose:
            print(f"  [OK] Usuario '{datos['usuario']}' creado (rol: {datos['rol']})")
    return creados


def inicializar_base(config, password_admin="admin123", verbose=True):
    """Punto de entrada: aplica migraciones y siembra los datos base."""
    if verbose:
        print("Aplicando migraciones...")
    ejecutar_migraciones(verbose=verbose)
    if verbose:
        print("Sembrando datos base...")
    sembrar_datos_base(password_admin=password_admin, verbose=verbose)
    sembrar_usuarios_role(verbose=verbose)
    if verbose:
        print("Base de datos inicializada.")