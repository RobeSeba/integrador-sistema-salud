"""Autenticacion y administracion de la sesion."""

from flask import (
    Blueprint,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from ..models.admin_model import AdminModel, AuditoriaModel, UsuarioInvalido
from .seguridad import requiere_login, usuario_actual

auth_bp = Blueprint("auth", __name__, url_prefix="/")


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if session.get("id_usuario"):
        return redirect(url_for("tablero.panel"))

    error = None
    usuario_input = ""
    if request.method == "POST":
        usuario_input = (request.form.get("usuario") or "").strip()
        password = request.form.get("password") or ""
        usuario = AdminModel.autenticar(usuario_input, password)
        if usuario is None:
            error = "Usuario o contrasena incorrectos."
            AuditoriaModel.registrar(
                "ACCESO", "FALLO", f"Intento fallido para '{usuario_input}'",
                usuario=usuario_input,
            )
        else:
            session.clear()
            session["id_usuario"] = usuario["id_usuario"]
            session["rol"] = usuario["rol"]
            session.permanent = True
            AdminModel.registrar_acceso(usuario["id_usuario"])
            AuditoriaModel.registrar(
                "ACCESO", "INGRESO", "Inicio de sesion", usuario["id_usuario"],
                usuario["usuario"],
            )
            destino = request.args.get("siguiente") or url_for("tablero.panel")
            # Solo se admiten rutas internas para evitar redireccion abierta.
            if not destino.startswith("/") or destino.startswith("//"):
                destino = url_for("tablero.panel")
            return redirect(destino)

    return render_template(
        "auth/login.html",
        error=error,
        usuario_input=usuario_input,
        siguiente=request.args.get("siguiente", ""),
    )


@auth_bp.route("/logout")
def logout():
    usuario = usuario_actual()
    if usuario:
        AuditoriaModel.registrar(
            "ACCESO", "SALIDA", "Cierre de sesion", usuario["id_usuario"],
            usuario["usuario"],
        )
    session.clear()
    flash("Sesion cerrada correctamente.", "info")
    return redirect(url_for("auth.login"))


@auth_bp.route("/perfil", methods=["GET", "POST"])
@requiere_login
def perfil():
    """Datos personales y cambio de contrasena para cualquier usuario con sesion.

    El usuario solo puede modificar sus propios datos: el rol y el estado de la
    cuenta siguen siendo competencia del administrador.
    """
    usuario = usuario_actual()
    if not usuario:
        return redirect(url_for("auth.login"))

    if request.method == "POST":
        accion = request.form.get("accion", "datos")

        if accion == "password":
            actual = request.form.get("password_actual") or ""
            nueva = request.form.get("password") or ""
            confirmacion = request.form.get("password_confirmacion") or ""

            if not AdminModel.verificar_password(usuario["id_usuario"], actual):
                flash("La contrasena actual es incorrecta.", "error")
            elif nueva != confirmacion:
                flash("La contrasena nueva y su confirmacion no coinciden.", "error")
            elif nueva == actual:
                flash("La contrasena nueva debe ser distinta de la actual.", "error")
            else:
                try:
                    AdminModel.cambiar_password(usuario["id_usuario"], nueva)
                except UsuarioInvalido as exc:
                    flash(str(exc), "error")
                else:
                    AuditoriaModel.registrar(
                        "USUARIOS", "PASSWORD",
                        f"Cambio de contrasena de '{usuario['usuario']}'",
                        usuario["id_usuario"], usuario["usuario"],
                    )
                    flash("Contrasena actualizada correctamente.", "ok")
                    return redirect(url_for("auth.perfil"))
        else:
            nombre = (request.form.get("nombre_completo") or "").strip()
            if not nombre:
                flash("El nombre completo es obligatorio.", "error")
            else:
                AdminModel.actualizar_datos_propios(
                    usuario["id_usuario"], nombre,
                    request.form.get("email") or None,
                    request.form.get("cargo") or None,
                )
                AuditoriaModel.registrar(
                    "USUARIOS", "PERFIL",
                    f"Actualizacion de datos de '{usuario['usuario']}'",
                    usuario["id_usuario"], usuario["usuario"],
                )
                flash("Datos personales actualizados.", "ok")
                return redirect(url_for("auth.perfil"))

    return render_template(
        "auth/perfil.html",
        titulo="Mi perfil",
        formulario=AdminModel.obtener_usuario(usuario["id_usuario"]),
    )
