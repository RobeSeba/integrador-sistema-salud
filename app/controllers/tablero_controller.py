"""Panel principal: indicadores globales, alertas y brechas highlights."""

from flask import Blueprint, g, render_template

from ..models.admin_model import PrioridadModel
from ..models.indicadores_model import IndicadoresModel
from ..models.procedimientos_model import ProcedimientosModel
from ..models.territorio_model import TerritorioModel
from ..utils.filtros import PLANES_SEGURO, SERVICIOS
from .seguridad import requiere_login

tablero_bp = Blueprint("tablero", __name__, url_prefix="/")


@tablero_bp.route("/")
@requiere_login
def panel():
    filtros = g.filtros
    brechas = IndicadoresModel.top_brechas_territorio(filtros, limite=10)
    contexto = {
        "titulo": "Panel de indicadores",
        "catalogo_regiones": TerritorioModel.regiones(),
        "planes_disponibles": PLANES_SEGURO,
        "servicios_disponibles": SERVICIOS,
        "perfiles": PrioridadModel.listar_perfiles(),
        "global": IndicadoresModel.indicadores_globales(filtros),
        "alertas": IndicadoresModel.distribucion_alerta(filtros),
        "brechas": brechas,
        # El grafico se arma en el controlador: la plantilla no debe hacer
        # transformaciones de datos, solo presentarlos.
        "brechas_grafico": [
            {"etiqueta": f["territorio"], "valor": f["ratio_afiliados_cama"] or 0}
            for f in brechas
        ],
        "criticos": ProcedimientosModel.ocupacion_critica(filtros, limite=10),
        "inoperativos": ProcedimientosModel.inoperatividad_critica(filtros, limite=10),
        "series": IndicadoresModel.serie_temporal(filtros),
        "planes": IndicadoresModel.distribucion_afiliados_por_plan(filtros),
    }
    return render_template("tablero/panel.html", **contexto)


@tablero_bp.route("/resumen")
@requiere_login
def resumen():
    """Vista compacta, pensada para imprimir o exportar."""
    filtros = g.filtros
    contexto = {
        "titulo": "Resumen territorial",
        "catalogo_regiones": TerritorioModel.regiones(),
        "planes_disponibles": PLANES_SEGURO,
        "servicios_disponibles": SERVICIOS,
        "perfiles": PrioridadModel.listar_perfiles(),
        "global": IndicadoresModel.indicadores_globales(filtros),
        "territorios": IndicadoresModel.indicadores_territorio(
            filtros, nivel="region"
        ),
        "categorias": IndicadoresModel.distribucion_por_categoria(filtros),
    }
    return render_template("tablero/resumen.html", **contexto)
