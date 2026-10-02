"""Control de acceso por rol.

El login es simple (usuario y contrasena contra dbo.sys_usuarios) pero cada
modulo declara que roles lo habilitan, de modo que anadir un rol nuevo no
obliga a tocar cada controlador.
"""

from functools import wraps

from flask import redirect, request, session, url_for

# Modulos publicos: se acceden sin sesion iniciada.
RUTAS_LIBRES = {"auth.login", "auth.logout", "static"}

# Permisos por modulo. Un rol que no figure en la lista no puede entrar.
PERMISOS = {
    "tablero": {"ADMINISTRADOR", "FUNCIONARIO", "ANALISTA_SANITARIO",
                "ANALISTA_DATOS", "MONITOREO"},
    "analisis": {"ADMINISTRADOR", "FUNCIONARIO", "ANALISTA_SANITARIO",
                 "ANALISTA_DATOS", "MONITOREO"},
    "admin": {"ADMINISTRADOR"},
    "api": {"ADMINISTRADOR", "FUNCIONARIO", "ANALISTA_SANITARIO",
            "ANALISTA_DATOS", "MONITOREO"},
}


class ControlAccesoDenegado(Exception):
    """El usuario no tiene permiso para el modulo solicitado."""

    def __init__(self, mensaje="No cuenta con permisos para esta seccion."):
        super().__init__(mensaje)
        self.mensaje = mensaje


def roles_permitidos(modulo):
    return PERMISOS.get(modulo, set())


def usuario_actual():
    """Datos del usuario en sesion, o None."""
    from ..models.admin_model import AdminModel

    id_usuario = session.get("id_usuario")
    if not id_usuario:
        return None
    usuario = AdminModel.obtener_usuario(id_usuario)
    if not usuario or not usuario.get("activo"):
        session.clear()
        return None
    return usuario


def roles_requeridos(*roles):
    """Helper para las plantillas: `{{ 'texto' if tiene_rol('ADMINISTRADOR') }}`."""
    usuario = usuario_actual()
    if not usuario:
        return False
    return usuario["rol"] in roles


def requiere_login(funcion):
    @wraps(funcion)
    def envoltorio(*args, **kwargs):
        if request.endpoint not in RUTAS_LIBRES and not session.get("id_usuario"):
            return redirect(url_for("auth.login", siguiente=request.full_path.rstrip("?")))
        return funcion(*args, **kwargs)

    return envoltorio


def requiere_rol(*roles):
    """Restringe una vista a los roles indicados."""

    def decorador(funcion):
        @wraps(funcion)
        def envoltorio(*args, **kwargs):
            if request.endpoint not in RUTAS_LIBRES and not session.get("id_usuario"):
                return redirect(url_for("auth.login", siguiente=request.full_path.rstrip("?")))
            usuario = usuario_actual()
            if usuario is None:
                return redirect(url_for("auth.login", siguiente=request.full_path.rstrip("?")))
            permitidos = set(roles)
            for lista in PERMISOS.values():
                permitidos.update(lista)
            if permitidos and usuario["rol"] not in permitidos:
                raise ControlAccesoDenegado(
                    f"El rol '{usuario.get('rol_nombre', usuario['rol'])}' "
                    "no puede acceder a esta seccion."
                )
            return funcion(*args, **kwargs)

        return envoltorio

    return decorador


def request_endpoint_publico():
    return request.endpoint in RUTAS_LIBRES


def request_endpoint_url():
    return request.full_path.rstrip("?")


def exigir_admin():
    usuario = usuario_actual()
    if usuario is None:
        abort(401)
    if usuario["rol"] != "ADMINISTRADOR":
        raise ControlAccesoDenegado("Seccion exclusiva del administrador.")
    return usuario
