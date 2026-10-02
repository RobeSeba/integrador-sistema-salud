"""Punto de entrada del sistema SIBS.

Ejecucion en desarrollo:
    python run.py

Configuracion por variable de entorno:
    SIBS_ENV=produccion|desarrollo|pruebas
"""

from app import crear_app

app = crear_app()


if __name__ == "__main__":
    config = app.config["SIBS_CONFIG"]
    print(f"{config.APP_NAME} -> {config.APP_TITULO}")
    print(f"Base de datos: {config.DB_SERVER} / {config.DB_NAME}")
    app.run(host="127.0.0.1", port=5000, debug=config.DEBUG)
