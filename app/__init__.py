"""Fabrica de la aplicacion Flask del sistema SIBS.

 aqui se registra todo lo que es transversal a los controladores: pool de
conexiones, blueprints, filtros de plantilla, manejadores de error y el
contexto comun que las vistas necesitan (usuario autenticado, catalogos y
filtros por defecto).
"""

import logging
from datetime import date, datetime, timedelta
from decimal import Decimal

from flask import Flask, g, render_template, request
from flask_wtf.csrf import CSRFError, CSRFProtect

from config import obtener_config

from .database.bd import init_pool
from .database.migraciones import inicializar_base


def crear_app(nombre_config=None, ejecutar_migraciones=True):
    config = obtener_config(nombre_config)

    app = Flask(
        __name__,
        instance_relative_config=False,
        template_folder="views/templates",
        static_folder="views/static",
    )
    app.config.from_object(config)
    app.config["SIBS_CONFIG"] = config

    _configurar_logging(app, config)
    init_pool(config)
    if ejecutar_migraciones:
        inicializar_base(config, verbose=app.debug)

    _registrar_blueprints(app)
    _registrar_filtros(app)
    _registrar_context(app)
    _registrar_errores(app)
    _registrar_seguridad(app)

    @app.cli.command("reconstruir-dim-ipress")
    def _reconstruir():
        """Regenera dbo.dim_ipress_ext desde los tres hechos."""
        from .models.territorio_model import TerritorioModel

        print(TerritorioModel.refrescar_dim_ipress_ext())

    return app


# ----------------------------------------------------------------------
def _configurar_logging(app, config):
    nivel = logging.DEBUG if config.DEBUG else logging.INFO
    logging.basicConfig(
        level=nivel,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )
    app.logger.setLevel(nivel)


def _registrar_blueprints(app):
    from .controllers.admin_controller import admin_bp
    from .controllers.analisis_controller import analisis_bp
    from .controllers.api_controller import api_bp
    from .controllers.auth_controller import auth_bp
    from .controllers.tablero_controller import tablero_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(tablero_bp)
    app.register_blueprint(analisis_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(api_bp)


# ----------------------------------------------------------------------
def _registrar_filtros(app):
    """Formatos usados en todas las plantillas."""
    from .utils.formato import formato_fecha, formato_numero, formato_porcentaje

    app.add_template_filter(formato_numero, "numero")
    app.add_template_filter(formato_porcentaje, "pct")
    app.add_template_filter(formato_fecha, "fecha")
    app.add_template_filter(lambda v: "" if v is None else str(v), "texto")


# ----------------------------------------------------------------------
def _registrar_context(app):
    from .controllers.seguridad import roles_requeridos, usuario_actual
    from .utils.filtros import Filtros, desde_request

    @app.context_processor
    def _inyectar():
        config = app.config["SIBS_CONFIG"]
        return {
            "app_nombre": config.APP_NAME,
            "app_titulo": config.APP_TITULO,
            "app_subtitulo": config.APP_SUBTITULO,
            "roles_disponibles": config.ROLES,
            "usuario": usuario_actual(),
            "tiene_rol": roles_requeridos,
            "filtros": getattr(g, "filtros", None),
            "anio_actual": date.today().year,
        }

    @app.template_global()
    def url_filtros(endpoint, **extra):
        """url_for conservando los filtros activos de la peticion.

        Los valores explicitos de `extra` pisan a los del filtro, de modo que
        `url_filtros('analisis.territorio', nivel='provincia')` no choque con
        el `nivel` que ya trae el filtro.
        """
        from flask import url_for as _url_for

        parametros = {}
        filtros = getattr(g, "filtros", None)
        if filtros is not None:
            parametros = {
                clave: valor
                for clave, valor in filtros.to_dict().items()
                if valor not in (None, "")
            }
        parametros.update(extra)
        return _url_for(endpoint, **parametros)

    @app.before_request
    def _cargar_filtros():
        """Todo request que lleva filtros los normaliza una sola vez.

        Se capturan los errores aqui para responder 400 con un mensaje claro
        en lugar de una excepcion en el controlador.
        """
        from .utils.filtros import FiltrosError

        if request.endpoint in (None, "static", "auth.login", "auth.logout"):
            g.filtros = None
            return
        try:
            g.filtros = desde_request(request.args, app.config["SIBS_CONFIG"])
        except FiltrosError as exc:
            g.filtros = Filtros(
                fecha_inicio=date(2023, 1, 1), fecha_fin=date(2023, 12, 31)
            )
            g.filtros_error = str(exc)


def _registrar_errores(app):
    from .controllers.seguridad import ControlAccesoDenegado
    from .utils.filtros import FiltrosError

    @app.errorhandler(FiltrosError)
    def _filtros_invalidos(exc):
        return render_template("errores/400.html", mensaje=str(exc)), 400

    @app.errorhandler(ControlAccesoDenegado)
    def _acceso_denegado(exc):
        return render_template(
            "errores/403.html", mensaje=getattr(exc, "mensaje", str(exc))
        ), 403

    @app.errorhandler(413)
    def _demasiado_grande(_exc):
        limite = app.config["SIBS_CONFIG"].MAX_CONTENT_LENGTH // (1024 * 1024)
        return render_template(
            "errores/400.html",
            mensaje=f"El archivo supera el limite permitido de {limite} MB.",
        ), 413

    @app.errorhandler(CSRFError)
    def _csrf_invalido(exc):
        # Un token caducado no debe perder el trabajo del usuario: se avisa con
        # un mensaje claro en lugar de un error 500 generico.
        app.logger.warning("Token CSRF rechazado en %s: %s", request.path, exc)
        return render_template(
            "errores/400.html",
            mensaje=(
                "La sesion de seguridad caduco o el formulario no es valido. "
                "Actualice la pagina e intentelo nuevamente."
            ),
        ), 400

    @app.errorhandler(404)
    def _no_encontrado(_exc):
        return render_template(
            "errores/404.html",
            mensaje="La pagina solicitada no existe o fue movida.",
        ), 404

    @app.errorhandler(500)
    def _error_interno(exc):
        app.logger.exception("Error interno: %s", exc)
        return render_template(
            "errores/500.html",
            mensaje="Ocurrio un error inesperado. Intente nuevamente.",
        ), 500


def _registrar_seguridad(app):
    """Proteccion CSRF, cookies de sesion y cabeceras de seguridad.

    CSRFProtect se activa salvo en el ambiente de pruebas, donde el cliente de
    pruebas no resuelve tokens. Los formularios deben incluir el token con
    ``{{ csrf_token() }}``; tambien se acepta la cabecera X-CSRFToken para
    clientes que no usan formularios HTML.
    """
    config = app.config["SIBS_CONFIG"]

    app.config["WTF_CSRF_ENABLED"] = not config.TESTING
    app.config["WTF_CSRF_TIME_LIMIT"] = 3600
    app.config["WTF_CSRF_HEADERS"] = ["X-CSRFToken", "X-CSRF-Token"]
    CSRFProtect(app)

    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    app.config["SESSION_COOKIE_SECURE"] = not config.DEBUG
    app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(hours=8)

    @app.after_request
    def _cabeceras(respuesta):
        respuesta.headers.setdefault("X-Content-Type-Options", "nosniff")
        respuesta.headers.setdefault("X-Frame-Options", "DENY")
        respuesta.headers.setdefault("Referrer-Policy", "same-origin")
        return respuesta
