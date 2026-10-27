"""Control de acceso por rol y por modulo.

Cada modulo (seccion o grafico del sistema) declara que roles lo traen por
defecto en ``MODULOS_POR_ROL``. Ademas, el administrador puede personalizar
los modulos de un usuario concreto desde Administracion > Usuarios; ese
ajuste se guarda en dbo.sys_permisos_usuario y pisa el default del rol.

Reglas:
  * ADMINISTRADOR tiene siempre todos los modulos (y el de administracion).
  * Un usuario sin filas en sys_permisos_usuario usa el default de su rol.
  * Un usuario con filas usa exactamente esas filas (conjunto completo).
"""

from functools import wraps

from flask import flash, redirect, request, session, url_for

from ..modulos import (
    MODULOS,
    MODULOS_NAVEGABLES,
    MODULOS_POR_ROL,
    ROL_INICIO,
)

# Modulos publicos: se acceden sin sesion iniciada.
RUTAS_LIBRES = {"auth.login", "auth.logout", "static"}


class ControlAccesoDenegado(Exception):
    """El usuario no tiene permiso para el modulo solicitado."""

    def __init__(self, mensaje="No cuenta con permisos para esta seccion."):
        super().__init__(mensaje)
        self.mensaje = mensaje


# ---------------------------------------------------------------------------
# Usuario en sesion
# ---------------------------------------------------------------------------
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


def _modulos_efectivos(id_usuario, rol):
    """Modulos habilitados del usuario (con cachÃ© por request).

    1. Si el rol es ADMINISTRADOR, todo.
    2. Si sys_permisos_usuario tiene filas, esas filas definen el conjunto.
    3. Si no hay filas, rige el default del rol.
    """
    cached = getattr(_cache(), "modulos", None)
    if cached is not None and cached[0] == id_usuario:
        return cached[1]

    if str(rol).upper() == "ADMINISTRADOR":
        modulos = set(MODULOS)
    else:
        filas = _permisos_db(id_usuario)
        if filas:
            modulos = {
                str(fila["modulo"]).lower()
                for fila in filas if fila.get("permitido")
            }
        else:
            modulos = set(MODULOS_POR_ROL.get(str(rol).upper(), set()))

    cache = _cache()
    cache.modulos = (id_usuario, modulos)
    return modulos


def _permisos_db(id_usuario):
    from ..models.base_model import BaseModel, normalizar_filas

    filas = normalizar_filas(BaseModel.consultar(
        "SELECT modulo, permitido FROM dbo.sys_permisos_usuario WHERE id_usuario = ?",
        [id_usuario],
    ))
    return filas


class _Cache:
    pass


def _cache():
    from flask import g

    if not hasattr(g, "_sibs_acceso"):
        g._sibs_acceso = _Cache()
    return g._sibs_acceso


def tiene_modulo(usuario, clave):
    """True si el usuario puede entrar al modulo indicado."""
    if not usuario or clave not in MODULOS:
        return False
    if str(usuario["rol"]).upper() == "ADMINISTRADOR":
        return True
    return clave in _modulos_efectivos(usuario["id_usuario"], usuario["rol"])


def pantalla_inicio(usuario):
    """Pantalla de aterrizaje: el inicio prefijado del rol o, si no tiene
    ese modulo habilitado, el primer modulo navegable permitido."""
    preferido = ROL_INICIO.get(str(usuario["rol"]).upper())
    if preferido and tiene_modulo(usuario, preferido):
        meta = MODULOS[preferido]
        return meta["endpoint"], dict(meta.get("url_args") or {})

    for clave in MODULOS_NAVEGABLES:
        if tiene_modulo(usuario, clave):
            meta = MODULOS[clave]
            return meta["endpoint"], dict(meta.get("url_args") or {})
    raise ControlAccesoDenegado(
        "El rol no tiene modulos asignados. Contacte al administrador."
    )


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


def requiere_modulo(clave):
    """Restringe una vista al modulo indicado (segÃºn rol o ajuste del admin).

    Si el usuario no tiene el modulo, se redirige a su pantalla inicial para
    no dejarlo varado en un 403 (a menos que la propia pantalla inicial sea
    la seccion restringida).
    """

    def decorador(funcion):
        @wraps(funcion)
        def envoltorio(*args, **kwargs):
            if request.endpoint not in RUTAS_LIBRES and not session.get("id_usuario"):
                return redirect(url_for("auth.login", siguiente=request.full_path.rstrip("?")))
            usuario = usuario_actual()
            if usuario is None:
                return redirect(url_for("auth.login", siguiente=request.full_path.rstrip("?")))
            if tiene_modulo(usuario, clave):
                return funcion(*args, **kwargs)
            try:
                endpoint, url_args = pantalla_inicio(usuario)
            except ControlAccesoDenegado:
                raise
            if endpoint == MODULOS.get(clave, {}).get("endpoint"):
                # El aterrizaje caeria otra vez aqui: sin salida, 403 claro.
                raise ControlAccesoDenegado(
                    f"El rol '{usuario.get('rol_nombre', usuario['rol'])}' "
                    "no puede acceder a esta seccion."
                )
            flash("La seccion solicitada no esta habilitada para su cuenta.", "aviso")
            return redirect(url_for(endpoint, **url_args))

        return envoltorio

    return decorador


def request_endpoint_publico():
    return request.endpoint in RUTAS_LIBRES


def request_endpoint_url():
    return request.full_path.rstrip("?")


def exigir_admin():
    from flask import abort

    usuario = usuario_actual()
    if usuario is None:
        abort(401)
    if usuario["rol"] != "ADMINISTRADOR":
        raise ControlAccesoDenegado("Seccion exclusiva del administrador.")
    return usuario
