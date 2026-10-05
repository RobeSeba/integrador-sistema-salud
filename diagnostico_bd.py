"""Comprueba la conexion y el esquema de salud sin iniciar Flask ni migrar.

Ejecutar desde la carpeta del proyecto: python diagnostico_bd.py
La contrasena y la cadena de conexion no se muestran.
"""

from contextlib import closing
from pathlib import Path
import sys

from config import obtener_config


# Columnas necesarias para la dimension extendida y los tres procedimientos.
# Esta comprobacion no valida los tipos, los datos ni todos los indicadores.
COLUMNAS_MINIMAS = {
    "dim_ipress": {
        "codigo_ipress", "nombre_establecimiento", "categoria", "nivel",
        "institucion", "grupo", "sub_grupo", "macroregion", "cuenta_triaje",
        "cuenta_zc", "ubigeo", "region", "provincia", "distrito",
    },
    "fact_afiliados_sis": {
        "codigo_ipress", "fecha_corte", "total_afiliados", "ubigeo",
        "region", "provincia", "distrito",
    },
    "fact_atenciones": {
        "codigo_ipress", "fecha_corte", "total_atenciones", "ubigeo",
        "region", "provincia", "distrito",
    },
    "fact_capacidad_diaria": {
        "codigo_ipress", "fecha_corte", "total_camas", "total_camas_ocupadas",
        "tasa_ocupacion_global", "uci_inoperativas", "hosp_inoperativas",
        "vent_inoperativos", "vent_operativos",
    },
}

PROCEDIMIENTOS = {
    "usp_salud_presionafiliados",
    "usp_salud_utilizacioncamas",
    "usp_salud_inoperatividadrecursos",
}


def faltantes_esquema(filas):
    """Compara los metadatos de sys.columns con el minimo requerido."""
    presentes = {}
    for tabla, columna in filas:
        presentes.setdefault(tabla.lower(), set()).add(columna.lower())
    problemas = []
    for tabla, requeridas in COLUMNAS_MINIMAS.items():
        if tabla not in presentes:
            problemas.append(f"Falta la tabla dbo.{tabla}.")
        elif requeridas - presentes[tabla]:
            columnas = ", ".join(sorted(requeridas - presentes[tabla]))
            problemas.append(f"dbo.{tabla}: faltan columnas {columnas}.")
    return problemas


def _error_seguro(error, config):
    mensaje = str(error)
    if config.DB_PWD:
        mensaje = mensaje.replace(config.DB_PWD, "[REDACTADO]")
        mensaje = mensaje.replace(
            config.DB_PWD.replace("}", "}}"), "[REDACTADO]"
        )
    return mensaje


def main():
    config = obtener_config()
    trusted = str(config.DB_TRUSTED_CONNECTION).strip().lower()
    print("Configuracion:", Path(__file__).resolve().with_name("config.py"))
    print("Servidor configurado:", config.DB_SERVER)
    print("Base configurada:", config.DB_NAME)
    print("Driver:", config.DB_DRIVER)
    if trusted in ("yes", "1", "true"):
        print("Autenticacion: Windows (cuenta que ejecuta Python)")
    else:
        print("Autenticacion: SQL Server; usuario:", config.DB_UID or "(sin configurar)")
        print("Contrasena configurada:", "si" if config.DB_PWD else "no")

    try:
        cadena = config.connection_string()
    except ValueError as error:
        print("[ERROR DE CONFIGURACION]", _error_seguro(error, config))
        return 1

    try:
        import pyodbc
    except ImportError:
        print("[ERROR] Falta pyodbc en este Python. Instale requirements.txt en su entorno.")
        return 1

    try:
        drivers = pyodbc.drivers()
        if config.DB_DRIVER not in drivers:
            print("[ERROR] No esta instalado el driver configurado para este Python.")
            print("Drivers disponibles:", ", ".join(drivers) or "(ninguno)")
            print("Instale el driver de Microsoft o ajuste SIBS_DB_DRIVER.")
            return 1
        with closing(pyodbc.connect(
            cadena, timeout=config.DB_TIMEOUT, autocommit=True
        )) as conn:
            with closing(conn.cursor()) as cursor:
                cursor.execute(
                    "SELECT @@SERVERNAME, DB_NAME(), SUSER_SNAME(), "
                    "SERVERPROPERTY('IsIntegratedSecurityOnly')"
                )
                servidor, base, usuario, solo_windows = cursor.fetchone()
                print("[OK] Conexion establecida.")
                print("Servidor real:", servidor)
                print("Base real:", base)
                print("Usuario real:", usuario)
                if solo_windows is not None:
                    print("Modo del servidor:", "solo Windows" if solo_windows else "mixto")

                cursor.execute("""
                    SELECT t.name, c.name
                    FROM sys.tables t
                    JOIN sys.schemas s ON s.schema_id = t.schema_id
                    JOIN sys.columns c ON c.object_id = t.object_id
                    WHERE s.name = N'dbo' AND t.name IN (
                        N'dim_ipress', N'fact_afiliados_sis',
                        N'fact_atenciones', N'fact_capacidad_diaria'
                    )
                """)
                problemas = faltantes_esquema(cursor.fetchall())
                if problemas:
                    for problema in problemas:
                        print("[ESQUEMA INCOMPLETO]", problema)
                    print(
                        "Revise el nombre de la base y restaure el esquema original "
                        "de salud. Este ZIP solo incluye migraciones de soporte."
                    )
                    return 2
                print("[OK] Tablas y columnas minimas encontradas.")

                cursor.execute("""
                    SELECT p.name FROM sys.procedures p
                    JOIN sys.schemas s ON s.schema_id = p.schema_id
                    WHERE s.name = N'dbo'
                """)
                presentes = {fila[0].lower() for fila in cursor.fetchall()}
                ausentes = PROCEDIMIENTOS - presentes
                if ausentes:
                    print("[AVISO] Faltan procedimientos:", ", ".join(sorted(ausentes)))
                    print("Ejecute su script de los tres procedimientos en esta base.")
                else:
                    print("[OK] Los tres procedimientos de salud existen.")
    except pyodbc.Error as error:
        mensaje = _error_seguro(error, config)
        print("[ERROR SQL/ODBC]", mensaje)
        if "18456" in mensaje or "28000" in mensaje:
            print(
                "SQL Server rechazo el inicio de sesion. Compruebe esta misma "
                "instancia y autenticacion en SSMS; el registro de errores "
                "del servidor indica el motivo exacto."
            )
        elif "4060" in mensaje or "4064" in mensaje:
            print("Revise que la base exista y que este usuario tenga acceso.")
        elif "08001" in mensaje or "HYT00" in mensaje:
            print("Revise la instancia, el servicio SQL Server (SQLEXPRESS) y la conectividad.")
        return 1

    print("Prueba completada. Ahora puede ejecutar: python run.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
