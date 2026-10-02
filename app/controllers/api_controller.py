"""API JSON interna, pensada para refreshing de las graficas del panel.

No expone datos sensibles ni operaciones de escritura: es de solo lectura
para los roles que ya pueden ver la interfaz.
"""

from flask import Blueprint, abort, g, jsonify, request

from ..models.indicadores_model import IndicadoresModel
from ..models.procedimientos_model import ProcedimientosModel
from ..models.ranking_model import RankingError, RankingModel
from ..models.territorio_model import TerritorioModel
from .seguridad import requiere_login

api_bp = Blueprint("api", __name__, url_prefix="/api")

# Serializacion de los tipos que devuelve pyodbc y json no entiende.
_TIPOS = (int, float, str, bool, type(None))


def _jsonizable(valor):
    if isinstance(valor, dict):
        return {k: _jsonizable(v) for k, v in valor.items()}
    if isinstance(valor, (list, tuple)):
        return [_jsonizable(v) for v in valor]
    if isinstance(valor, _TIPOS):
        return valor
    if hasattr(valor, "isoformat"):
        return valor.isoformat()
    return str(valor)


def _respuesta(datos, **extra):
    cuerpo = {"ok": True, "datos": _jsonizable(datos)}
    cuerpo.update(_jsonizable(extra))
    return jsonify(cuerpo)


@api_bp.errorhandler(500)
def _error_json(exc):
    return jsonify({"ok": False, "error": "Error interno del servidor"}), 500


@api_bp.route("/catalogo/regiones")
@requiere_login
def catalogo_regiones():
    return _respuesta(TerritorioModel.regiones())


@api_bp.route("/catalogo/provincias")
@requiere_login
def catalogo_provincias():
    return _respuesta(TerritorioModel.provincias(request.args.get("region")))


@api_bp.route("/catalogo/distritos")
@requiere_login
def catalogo_distritos():
    return _respuesta(
        TerritorioModel.distritos(
            request.args.get("region"), request.args.get("provincia")
        )
    )


@api_bp.route("/catalogo/establecimientos")
@requiere_login
def catalogo_establecimientos():
    return _respuesta(
        TerritorioModel.buscar_establecimientos(
            request.args.get("q"), request.args.get("region"),
            limite=request.args.get("limite", type=int) or 50,
        )
    )


@api_bp.route("/indicadores/globales")
@requiere_login
def indicadores_globales():
    return _respuesta(
        IndicadoresModel.indicadores_globales(g.filtros),
        filtros=g.filtros.to_dict(),
    )


@api_bp.route("/indicadores/serie")
@requiere_login
def indicadores_serie():
    granularidad = request.args.get("granularidad") or g.filtros.granularidad
    return _respuesta(
        IndicadoresModel.serie_temporal(g.filtros, granularidad),
        granularidad=granularidad,
    )


@api_bp.route("/indicadores/territorio")
@requiere_login
def indicadores_territorio():
    nivel = request.args.get("nivel", "region")
    if nivel not in ("region", "provincia", "distrito"):
        abort(404)
    return _respuesta(
        IndicadoresModel.indicadores_territorio(g.filtros, nivel=nivel),
        nivel=nivel,
    )


@api_bp.route("/indicadores/establecimiento/<int:codigo_ipress>")
@requiere_login
def indicadores_establecimiento(codigo_ipress):
    ficha = IndicadoresModel.ficha_establecimiento(g.filtros, codigo_ipress)
    if not ficha:
        abort(404)
    return _respuesta(ficha)


@api_bp.route("/alertas/resumen")
@requiere_login
def alertas_resumen():
    return _respuesta(ProcedimientosModel.resumen_alertas(g.filtros))


@api_bp.route("/alertas/ocupacion")
@requiere_login
def alertas_ocupacion():
    limite = min(request.args.get("limite", type=int) or 50, 500)
    return _respuesta(ProcedimientosModel.ocupacion_critica(g.filtros, limite))


@api_bp.route("/ranking")
@requiere_login
def ranking():
    perfil = request.args.get("perfil") or "BRECHA_CAPACIDAD"
    try:
        if request.args.get("ambito") == "territorio":
            datos = RankingModel.ranking_territorios(
                g.filtros, perfil,
                nivel=request.args.get("nivel", "region"),
                limite=request.args.get("limite", type=int) or 25,
            )
        else:
            datos = RankingModel.ranking_establecimientos(
                g.filtros, perfil,
                limite=request.args.get("limite", type=int) or 25,
            )
    except RankingError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    return _respuesta(datos["filas"], perfil=datos["perfil"].get("nombre"),
                      total_evaluados=datos["total_evaluados"])
