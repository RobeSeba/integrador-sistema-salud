"""Consultas de analisis: territorio, ranking, establecimiento, evolucion y alertas."""

from flask import Blueprint, abort, g, render_template, request

from ..models.admin_model import PrioridadModel
from ..models.indicadores_model import IndicadoresModel
from ..models.procedimientos_model import ProcedimientosModel
from ..models.ranking_model import RankingError, RankingModel
from ..models.territorio_model import TerritorioModel
from ..utils.filtros import PLANES_SEGURO, SERVICIOS
from .exportar import construir_exportacion
from .seguridad import requiere_login

analisis_bp = Blueprint("analisis", __name__, url_prefix="/analisis")

NIVELES_TERRITORIO = {
    "region": "Regiones",
    "provincia": "Provincias",
    "distrito": "Distritos",
}


def _base_contexto(extra):
    contexto = {
        "catalogo_regiones": TerritorioModel.regiones(),
        "planes_disponibles": PLANES_SEGURO,
        "servicios_disponibles": SERVICIOS,
        "perfiles": PrioridadModel.listar_perfiles(),
        "niveles_territorio": NIVELES_TERRITORIO,
    }
    contexto.update(extra)
    return contexto


@analisis_bp.route("/territorio")
@requiere_login
def territorio():
    filtros = g.filtros
    nivel = request.args.get("nivel", "region")
    if nivel not in NIVELES_TERRITORIO:
        nivel = "region"

    filas = IndicadoresModel.indicadores_territorio(filtros, nivel=nivel)
    orden = request.args.get("orden")
    if orden in ("tasa_ocupacion", "ratio_afiliados_cama", "total_afiliados"):
        filas.sort(key=lambda f: (f.get(orden) is None, -(f.get(orden) or 0)))

    contexto = _base_contexto(
        {
            "titulo": "Analisis territorial",
            "nivel": nivel,
            "nivel_etiqueta": NIVELES_TERRITORIO[nivel],
            "filas": filas,
            "categorias": IndicadoresModel.distribucion_por_categoria(filtros),
            "series": IndicadoresModel.serie_temporal(filtros),
            "alertas": IndicadoresModel.distribucion_alerta(filtros),
        }
    )
    return render_template("analisis/territorio.html", **contexto)


@analisis_bp.route("/ranking")
@requiere_login
def ranking():
    filtros = g.filtros
    perfil = request.args.get("perfil") or "BRECHA_CAPACIDAD"
    ambito = request.args.get("ambito", "eess")
    nivel = request.args.get("nivel", "region")
    limite = request.args.get("limite", type=int) or 25

    resultado = None
    error = None
    try:
        if ambito == "territorio":
            resultado = RankingModel.ranking_territorios(
                filtros, perfil, nivel=nivel, limite=limite
            )
        else:
            resultado = RankingModel.ranking_establecimientos(
                filtros, perfil, limite=limite
            )
        brechas = RankingModel.brechas_por_departamento(filtros, limite=25)
    except (RankingError, ValueError) as exc:
        error = str(exc)
        brechas = []

    contexto = _base_contexto(
        {
            "titulo": "Ranking de priorizacion",
            "perfil_sel": perfil,
            "ambito": ambito,
            "nivel": nivel,
            "nivel_etiqueta": NIVELES_TERRITORIO.get(nivel, "Territorios"),
            "limite": limite,
            "resultado": resultado,
            "brechas": brechas,
            "error": error,
        }
    )
    return render_template("analisis/ranking.html", **contexto)


@analisis_bp.route("/establecimiento/<int:codigo_ipress>")
@requiere_login
def establecimiento(codigo_ipress):
    filtros = g.filtros
    # Se fija el codigo en el objeto de filtros para que todos los bloques de
    # la pagina (y los enlaces de exportacion) queden acotados al EESS.
    #
    # Los filtros territoriales se descartan a proposito: la ficha ya esta
    # acotada a un solo establecimiento, de modo que un "Region: Lima" previo
    # no hacia falta para acotarla pero si provocaba un 404 al abrir un EESS de
    # otra region desde una lista filtrada. El periodo si se conserva, porque
    # si cambia los indicadores de la ficha.
    filtros.codigo_ipress = codigo_ipress
    filtros.region = None
    filtros.provincia = None
    filtros.distrito = None
    filtros.categoria = None
    filtros.nivel = None
    filtros.institucion = None
    filtros.macroregion = None

    ficha = IndicadoresModel.ficha_establecimiento(filtros, codigo_ipress)
    if not ficha:
        abort(404)

    contexto = _base_contexto(
        {
            "titulo": ficha.get("nombre_establecimiento"),
            "ficha": ficha,
            "capacidad": IndicadoresModel.capacidad_diaria(
                codigo_ipress, filtros.fecha_inicio, filtros.fecha_fin
            ),
            "poblacion": IndicadoresModel.composicion_poblacional(codigo_ipress),
            "atenciones": IndicadoresModel.composicion_atenciones(
                codigo_ipress, filtros.fecha_inicio, filtros.fecha_fin
            ),
            "series": IndicadoresModel.serie_temporal(filtros),
        }
    )
    return render_template("analisis/establecimiento.html", **contexto)


@analisis_bp.route("/evolucion")
@requiere_login
def evolucion():
    filtros = g.filtros
    granularidad = filtros.granularidad
    contexto = _base_contexto(
        {
            "titulo": "Evolucion temporal",
            "granularidad": granularidad,
            "series": IndicadoresModel.serie_temporal(filtros, granularidad),
            "alertas": IndicadoresModel.distribucion_alerta(filtros),
        }
    )
    return render_template("analisis/evolucion.html", **contexto)


@analisis_bp.route("/alertas")
@requiere_login
def alertas():
    filtros = g.filtros
    departamentos = ProcedimientosModel.alertas_por_departamento(filtros)
    contexto = _base_contexto(
        {
            "titulo": "Monitoreo de alertas",
            "catalogo": ProcedimientosModel.catalogo(),
            "resumen": ProcedimientosModel.resumen_alertas(filtros),
            "ocupacion": ProcedimientosModel.ocupacion_critica(filtros),
            "inoperatividad": ProcedimientosModel.inoperatividad_critica(filtros),
            "departamentos": departamentos,
            "distribucion": IndicadoresModel.distribucion_alerta(filtros),
            # El grafico se arma en el controlador, no en la plantilla.
            "departamentos_grafico": [
                {"etiqueta": d["departamento"], "valor": d["registros_sobre_umbral"] or 0}
                for d in departamentos[:10]
            ],
        }
    )
    return render_template("analisis/alertas.html", **contexto)


@analisis_bp.route("/procedimientos/<clave>")
@requiere_login
def procedimiento(clave):
    if clave not in ProcedimientosModel.SQL:
        abort(404)
    filtros = g.filtros
    resultado = ProcedimientosModel.ejecutar(clave, filtros)
    contexto = _base_contexto(
        {
            "titulo": resultado["titulo"],
            "resultado": resultado,
            "catalogo": ProcedimientosModel.catalogo(),
            "clave": clave,
        }
    )
    return render_template("analisis/procedimiento.html", **contexto)


@analisis_bp.route("/exportar/<recurso>")
@requiere_login
def exportar(recurso):
    """Descarga CSV o XLSX del recurso solicitado con los filtros activos."""
    filtros = g.filtros
    formato = request.args.get("formato", "csv")
    recurso = recurso.lower()
    nivel = request.args.get("nivel", "region")
    perfil = request.args.get("perfil", "BRECHA_CAPACIDAD")

    if recurso == "territorio":
        datos = IndicadoresModel.indicadores_territorio(
            filtros, nivel=nivel if nivel in NIVELES_TERRITORIO else "region"
        )
        nombre_archivo = f"sibs_territorio_{nivel}_{filtros.fecha_inicio}_{filtros.fecha_fin}"
    elif recurso == "ranking":
        if request.args.get("ambito") == "territorio":
            datos = RankingModel.ranking_territorios(filtros, perfil, nivel=nivel)["filas"]
        else:
            datos = RankingModel.ranking_establecimientos(filtros, perfil)["filas"]
        nombre_archivo = f"sibs_ranking_{perfil}_{filtros.fecha_inicio}_{filtros.fecha_fin}"
    elif recurso == "alertas":
        datos = ProcedimientosModel.ocupacion_critica(filtros)
        nombre_archivo = f"sibs_alertas_{filtros.fecha_inicio}_{filtros.fecha_fin}"
    elif recurso == "serie":
        datos = IndicadoresModel.serie_temporal(filtros)
        nombre_archivo = f"sibs_serie_{filtros.fecha_inicio}_{filtros.fecha_fin}"
    else:
        abort(404)

    return construir_exportacion(datos, formato, nombre_archivo)
