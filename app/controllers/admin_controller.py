"""Administracion: usuarios, auditoria, cargas de datos y reglas de prioridad."""

import os
from datetime import datetime

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    g,
    redirect,
    render_template,
    request,
    url_for,
)
from werkzeug.utils import secure_filename

from ..models.admin_model import (
    AdminModel,
    AuditoriaModel,
    CargaModel,
    PerfilNoEncontrado,
    PrioridadModel,
    UsuarioInvalido,
)
from ..models.ranking_model import (
    CATALOGO_INDICADORES,
    codigos_equivalentes,
    nombre_indicador,
    resolver_indicador,
)
from ..models.territorio_model import TerritorioModel
from .exportar import construir_exportacion
from .seguridad import exigir_admin

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")


@admin_bp.before_request
def _exigir_administrador():
    """Todo el modulo admin es exclusivo del administrador."""
    g.usuario_admin = exigir_admin()


# ----------------------------------------------------------------------
# Usuarios
# ----------------------------------------------------------------------
@admin_bp.route("/usuarios")
def usuarios():
    contexto = {
        "titulo": "Gestion de usuarios",
        "usuarios": AdminModel.listar_usuarios(),
        "roles": current_app.config["SIBS_CONFIG"].ROLES,
        "total_administradores": AdminModel.total_administradores_activos(),
    }
    return render_template("admin/usuarios.html", **contexto)


@admin_bp.route("/usuarios/nuevo", methods=["GET", "POST"])
def usuario_nuevo():
    if request.method == "POST":
        try:
            nuevo = AdminModel.crear_usuario(
                request.form.get("usuario"),
                request.form.get("password"),
                request.form.get("nombre_completo"),
                request.form.get("rol"),
                request.form.get("email") or None,
                request.form.get("cargo") or None,
                activo=bool(request.form.get("activo")),
            )
        except UsuarioInvalido as exc:
            flash(str(exc), "error")
        else:
            AuditoriaModel.registrar(
                "USUARIOS", "CREAR",
                f"Usuario '{nuevo['usuario']}' con rol {nuevo['rol']}",
                g.usuario_admin["id_usuario"], g.usuario_admin["usuario"],
            )
            flash(f"Usuario '{nuevo['usuario']}' creado.", "ok")
            return redirect(url_for("admin.usuarios"))
    contexto = {
        "titulo": "Nuevo usuario",
        "roles": current_app.config["SIBS_CONFIG"].ROLES,
        "formulario": {},
    }
    return render_template("admin/usuario_form.html", **contexto)


@admin_bp.route("/usuarios/<int:id_usuario>/editar", methods=["GET", "POST"])
def usuario_editar(id_usuario):
    usuario = AdminModel.obtener_usuario(id_usuario)
    if not usuario:
        abort(404)

    if request.method == "POST":
        try:
            AdminModel.actualizar_usuario(
                id_usuario,
                request.form.get("nombre_completo"),
                request.form.get("rol"),
                request.form.get("email") or None,
                request.form.get("cargo") or None,
                activo=bool(request.form.get("activo")),
            )
            password = request.form.get("password") or ""
            if password:
                AdminModel.cambiar_password(id_usuario, password)
        except UsuarioInvalido as exc:
            flash(str(exc), "error")
        else:
            AuditoriaModel.registrar(
                "USUARIOS", "EDITAR", f"Actualizacion de '{usuario['usuario']}'",
                g.usuario_admin["id_usuario"], g.usuario_admin["usuario"],
            )
            flash("Usuario actualizado.", "ok")
            return redirect(url_for("admin.usuarios"))

    contexto = {
        "titulo": f"Editar {usuario['usuario']}",
        "roles": current_app.config["SIBS_CONFIG"].ROLES,
        "formulario": usuario,
        "es_yo": g.usuario_admin["id_usuario"] == id_usuario,
    }
    return render_template("admin/usuario_form.html", **contexto)


@admin_bp.route("/usuarios/<int:id_usuario>/eliminar", methods=["POST"])
def usuario_eliminar(id_usuario):
    usuario = AdminModel.obtener_usuario(id_usuario)
    if not usuario:
        abort(404)
    try:
        AdminModel.eliminar_usuario(id_usuario, g.usuario_admin["id_usuario"])
    except UsuarioInvalido as exc:
        flash(str(exc), "error")
    else:
        AuditoriaModel.registrar(
            "USUARIOS", "ELIMINAR", f"Eliminacion de '{usuario['usuario']}'",
            g.usuario_admin["id_usuario"], g.usuario_admin["usuario"],
        )
        flash("Usuario eliminado.", "ok")
    return redirect(url_for("admin.usuarios"))


# ----------------------------------------------------------------------
# Auditoria
# ----------------------------------------------------------------------
@admin_bp.route("/auditoria")
def auditoria():
    contexto = {
        "titulo": "Auditoria del sistema",
        "registros": AuditoriaModel.listar(
            limite=request.args.get("limite", type=int) or 200,
            modulo=request.args.get("modulo") or None,
        ),
        "modulo_seleccionado": request.args.get("modulo", ""),
    }
    return render_template("admin/auditoria.html", **contexto)


@admin_bp.route("/auditoria/exportar")
def auditoria_exportar():
    registros = AuditoriaModel.listar(
        limite=current_app.config["SIBS_CONFIG"].MAXIMO_EXPORTAR,
        modulo=request.args.get("modulo") or None,
    )
    return construir_exportacion(
        registros, request.args.get("formato", "csv"), "sibs_auditoria",
        titulo="Registro de auditoria",
    )


# ----------------------------------------------------------------------
# Perfiles y reglas de prioridad
# ----------------------------------------------------------------------
@admin_bp.route("/perfiles")
def perfiles():
    contexto = {
        "titulo": "Perfiles de priorizacion",
        "perfiles": PrioridadModel.listar_perfiles(),
    }
    return render_template("admin/perfiles.html", **contexto)


@admin_bp.route("/perfiles/nuevo", methods=["POST"])
def perfil_nuevo():
    try:
        perfil = PrioridadModel.crear_perfil(
            request.form.get("codigo"),
            request.form.get("nombre"),
            request.form.get("descripcion") or None,
            _a_float(request.form.get("umbral_critico"), 75.0),
            _a_float(request.form.get("umbral_alto"), 50.0),
            _a_float(request.form.get("umbral_medio"), 25.0),
        )
    except Exception as exc:  # el modelo puede fallar por codigo duplicado
        flash(f"No se pudo crear el perfil: {exc}", "error")
    else:
        _auditar("PERFILES", "CREAR", f"Perfil '{perfil['codigo']}'")
        flash(f"Perfil '{perfil['nombre']}' creado. Agregue sus reglas.", "ok")
    return redirect(url_for("admin.perfiles"))


@admin_bp.route("/perfiles/<int:id_perfil>")
def perfil_detalle(id_perfil):
    try:
        perfil = PrioridadModel.obtener_perfil(id_perfil)
    except PerfilNoEncontrado:
        abort(404)
    contexto = {
        "titulo": f"Perfil: {perfil['nombre']}",
        "perfil": perfil,
        "reglas": PrioridadModel.listar_reglas(perfil["id_perfil"]),
        "catalogo_indicadores": CATALOGO_INDICADORES,
        "peso_total": sum(
            (r["peso"] or 0)
            for r in PrioridadModel.listar_reglas(perfil["id_perfil"])
            if r["activo"]
        ),
    }
    return render_template("admin/perfil_detalle.html", **contexto)


@admin_bp.route("/perfiles/<int:id_perfil>/editar", methods=["POST"])
def perfil_editar(id_perfil):
    try:
        PrioridadModel.actualizar_perfil(
            id_perfil,
            request.form.get("nombre"),
            request.form.get("descripcion") or None,
            bool(request.form.get("activo")),
            _a_float(request.form.get("umbral_critico"), 75.0),
            _a_float(request.form.get("umbral_alto"), 50.0),
            _a_float(request.form.get("umbral_medio"), 25.0),
        )
    except PerfilNoEncontrado:
        abort(404)
    _auditar("PERFILES", "EDITAR", f"Perfil {id_perfil} actualizado")
    flash("Perfil actualizado.", "ok")
    return redirect(url_for("admin.perfil_detalle", id_perfil=id_perfil))


@admin_bp.route("/reglas/<int:id_regla>/actualizar", methods=["POST"])
def regla_actualizar(id_regla):
    PrioridadModel.actualizar_regla(
        id_regla,
        _a_float(request.form.get("peso"), 0.0),
        _a_float(request.form.get("umbral_minimo")),
        _a_float(request.form.get("umbral_maximo")),
        request.form.get("direccion") or "MAYOR",
        bool(request.form.get("obligatorio")),
        bool(request.form.get("activo")),
    )
    _auditar("PERFILES", "REGLA", f"Regla {id_regla} actualizada")
    flash("Regla actualizada. El perfil se recalcula en el proximo ranking.", "ok")
    return redirect(url_for("admin.perfil_detalle",
                            id_perfil=request.form.get("id_perfil")))


@admin_bp.route("/perfiles/<int:id_perfil>/reglas/nueva", methods=["POST"])
def regla_nueva(id_perfil):
    codigo = (request.form.get("codigo") or "").strip().lower()
    # Se resuelve el alias: los perfiles sembrados usan nombres del dominio
    # ("presion_afiliados") que no estan en el catalogo pero si tienen soporte.
    indicador = resolver_indicador(codigo)
    if not indicador:
        flash(
            f"'{codigo}' no es un indicador válido. Elija uno de la lista; "
            "una regla con otro nombre se descartaría al calcular el ranking.",
            "error",
        )
        return redirect(url_for("admin.perfil_detalle", id_perfil=id_perfil))

    peso = _a_float(request.form.get("peso"), 10.0)
    if peso <= 0:
        flash("El peso debe ser mayor que cero.", "error")
        return redirect(url_for("admin.perfil_detalle", id_perfil=id_perfil))

    umbral_min = _a_float(request.form.get("umbral_minimo"))
    umbral_max = _a_float(request.form.get("umbral_maximo"))
    if umbral_min is not None and umbral_max is not None and umbral_min >= umbral_max:
        flash("El umbral mínimo debe ser menor que el umbral máximo.", "error")
        return redirect(url_for("admin.perfil_detalle", id_perfil=id_perfil))

    # La base tiene un UNIQUE (id_perfil, codigo): se avisa antes de llegar a el
    # para no dejar al usuario con una pagina de error. Se comparan todos los
    # nombres equivalentes al indicador, no solo el codigo literal, porque dos
    # nombres distintos que apuntan al mismo indicador duplicarian el peso al
    # calcular el ranking.
    for equivalente in codigos_equivalentes(codigo):
        if PrioridadModel.regla_existe(id_perfil, equivalente):
            flash(
                f"El indicador '{nombre_indicador(indicador)}' ya tiene una regla "
                "en este perfil. Edite la existente en lugar de agregar otra.",
                "error",
            )
            return redirect(url_for("admin.perfil_detalle", id_perfil=id_perfil))

    # Se guarda el alias canonico: el nombre del dominio queda solo como
    # legado historico y asi la base no mezcla dos nomenclaturas.
    PrioridadModel.crear_regla(
        id_perfil,
        indicador,
        CATALOGO_INDICADORES[indicador],
        None,
        peso,
        umbral_min,
        umbral_max,
        request.form.get("direccion") or "MAYOR",
        bool(request.form.get("obligatorio")),
        True,
    )
    _auditar("PERFILES", "REGLA", f"Regla '{indicador}' agregada al perfil {id_perfil}")
    flash(f"Regla '{CATALOGO_INDICADORES[indicador]}' agregada.", "ok")
    return redirect(url_for("admin.perfil_detalle", id_perfil=id_perfil))


@admin_bp.route("/reglas/<int:id_regla>/eliminar", methods=["POST"])
def regla_eliminar(id_regla):
    PrioridadModel.eliminar_regla(id_regla)
    _auditar("PERFILES", "REGLA", f"Regla {id_regla} eliminada")
    flash("Regla eliminada.", "ok")
    return redirect(url_for("admin.perfil_detalle",
                            id_perfil=request.form.get("id_perfil")))


@admin_bp.route("/perfiles/<int:id_perfil>/duplicar", methods=["POST"])
def perfil_duplicar(id_perfil):
    try:
        nuevo = PrioridadModel.duplicar_perfil(
            id_perfil,
            request.form.get("codigo"),
            request.form.get("nombre"),
        )
    except Exception as exc:
        flash(f"No se pudo duplicar: {exc}", "error")
    else:
        _auditar("PERFILES", "DUPLICAR", f"Perfil {id_perfil} -> {nuevo['codigo']}")
        flash(f"Perfil '{nuevo['nombre']}' duplicado.", "ok")
        return redirect(url_for("admin.perfil_detalle", id_perfil=nuevo["id_perfil"]))
    return redirect(url_for("admin.perfil_detalle", id_perfil=id_perfil))


# ----------------------------------------------------------------------
# Cargas de archivos
# ----------------------------------------------------------------------
@admin_bp.route("/cargas")
def cargas():
    contexto = {
        "titulo": "Cargas de datos",
        "cargas": CargaModel.listar(limite=150),
        "resumen": CargaModel.resumen(),
        "por_tabla": CargaModel.por_tabla(),
        "tablas": CargaModel.TABLAS_PERMITIDAS,
    }
    return render_template("admin/cargas.html", **contexto)


@admin_bp.route("/cargas/nueva", methods=["GET", "POST"])
def carga_nueva():
    config = current_app.config["SIBS_CONFIG"]
    if request.method == "POST":
        archivo = request.files.get("archivo")
        if not archivo or not archivo.filename:
            flash("Seleccione un archivo CSV o XLSX.", "error")
            return redirect(url_for("admin.carga_nueva"))

        nombre = secure_filename(archivo.filename)
        extension = nombre.rsplit(".", 1)[-1].lower() if "." in nombre else ""
        if extension not in config.EXTENSIONES_PERMITIDAS:
            flash(
                f"Formato '{extension}' no permitido. Use: "
                f"{', '.join(sorted(config.EXTENSIONES_PERMITIDAS))}.",
                "error",
            )
            return redirect(url_for("admin.carga_nueva"))

        tabla_destino = CargaModel.normalizar_tabla_destino(request.form.get("tabla_destino"))
        if not tabla_destino:
            flash("Debe indicar una tabla destino valida.", "error")
            return redirect(url_for("admin.carga_nueva"))

        fecha_dato = request.form.get("fecha_dato") or datetime.now().strftime("%Y-%m-%d")
        ruta = os.path.join(config.UPLOAD_FOLDER, f"{datetime.now():%Y%m%d%H%M%S}_{nombre}")
        os.makedirs(config.UPLOAD_FOLDER, exist_ok=True)
        archivo.save(ruta)

        id_carga = CargaModel.registrar(
            nombre_archivo=archivo.filename,
            fuente=request.form.get("fuente") or "CARGA MANUAL",
            tabla_destino=tabla_destino,
            fecha_dato=fecha_dato,
            ruta_archivo=ruta,
            id_usuario=g.usuario_admin["id_usuario"],
            estado="PENDIENTE",
            modo_carga=request.form.get("modo_carga") or "INCREMENTAL",
            fecha_inicio_periodo=request.form.get("fecha_inicio_periodo") or None,
            fecha_fin_periodo=request.form.get("fecha_fin_periodo") or None,
            hash_archivo=CargaModel.hash_archivo(ruta),
        )

        # El archivo queda en PENDIENTE: la aplicacion no inserta hechos de
        # forma automatica. La validacion/aplicacion la realiza el operador
        # desde el procedimiento almacenado correspondiente.
        CargaModel.actualizar_resultado(
            id_carga, "VALIDADO",
            mensaje=(
                "Archivo recibido y almacenado. "
                "Pendiente de aplicacion mediante procedimiento almacenado."
            ),
        )
        _auditar("CARGAS", "REGISTRO",
                 f"Carga #{id_carga} de '{nombre}' hacia {tabla_destino}")
        flash(f"Archivo '{nombre}' registrado como carga #{id_carga}.", "ok")
        return redirect(url_for("admin.cargas"))

    contexto = {
        "titulo": "Registrar carga",
        "tablas": CargaModel.TABLAS_PERMITIDAS,
        "extensiones": sorted(config.EXTENSIONES_PERMITIDAS),
        "tamano_maximo_mb": config.MAX_CONTENT_LENGTH // (1024 * 1024),
    }
    return render_template("admin/carga_form.html", **contexto)


@admin_bp.route("/cargas/<int:id_carga>")
def carga_detalle(id_carga):
    carga = CargaModel.obtener(id_carga)
    if not carga:
        abort(404)
    contexto = {
        "titulo": f"Carga #{id_carga}",
        "carga": carga,
        "tabla": CargaModel.TABLAS_PERMITIDAS.get(carga["tabla_destino"], ""),
    }
    return render_template("admin/carga_detalle.html", **contexto)


@admin_bp.route("/cargas/<int:id_carga>/eliminar", methods=["POST"])
def carga_eliminar(id_carga):
    carga = CargaModel.obtener(id_carga)
    if not carga:
        abort(404)
    ruta = carga.get("ruta_archivo")
    if ruta and os.path.exists(ruta):
        try:
            os.remove(ruta)
        except OSError:
            current_app.logger.warning("No se pudo borrar el archivo %s", ruta)
    CargaModel.eliminar(id_carga)
    _auditar("CARGAS", "ELIMINAR", f"Carga #{id_carga} eliminada")
    flash("Registro de carga eliminado.", "ok")
    return redirect(url_for("admin.cargas"))


# ----------------------------------------------------------------------
# Calidad de datos
# ----------------------------------------------------------------------
@admin_bp.route("/calidad")
def calidad():
    contexto = {
        "titulo": "Calidad de datos",
        "cobertura": TerritorioModel.cobertura(),
        "dim_ext": TerritorioModel.estadisticas_dim_ext(),
        "aliases": TerritorioModel.alias_territorio(),
        "categorias": TerritorioModel.categorias(),
    }
    return render_template("admin/calidad.html", **contexto)


@admin_bp.route("/calidad/reconstruir-dim", methods=["POST"])
def reconstruir_dim():
    resultado = TerritorioModel.refrescar_dim_ipress_ext()
    _auditar("CALIDAD", "REBUILD", "Reconstruccion de dim_ipress_ext")
    flash(f"dim_ipress_ext reconstruida: {resultado}", "ok")
    return redirect(url_for("admin.calidad"))


@admin_bp.route("/calidad/alias", methods=["POST"])
def agregar_alias():
    try:
        TerritorioModel.agregar_alias(
            request.form.get("nivel"),
            request.form.get("nombre_original"),
            request.form.get("nombre_canonico"),
        )
    except ValueError as exc:
        flash(str(exc), "error")
    else:
        _auditar("CALIDAD", "ALIAS", "Alias territorial agregado")
        flash("Alias registrado.", "ok")
    return redirect(url_for("admin.calidad"))


# ----------------------------------------------------------------------
# helpers
# ----------------------------------------------------------------------
def _a_float(valor, defecto=None):
    if valor is None or str(valor).strip() == "":
        return defecto
    try:
        return float(str(valor).replace(",", "."))
    except (TypeError, ValueError):
        return defecto


def _auditar(modulo, accion, detalle):
    AuditoriaModel.registrar(
        modulo, accion, detalle,
        g.usuario_admin["id_usuario"], g.usuario_admin["usuario"],
    )
