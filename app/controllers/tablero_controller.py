"""Panel principal: indicadores globales y resumen territorial.

El contenido del panel DEPENDE de los modulos habilitados del usuario: las
secciones (y sus consultas) se cargan solo si el usuario tiene el modulo
correspondiente. Asi el administrador guarda, desde Administracion >
Usuarios, que graficos ve cada cuenta.
"""

from flask import Blueprint, g, render_template

from ..models.admin_model import PrioridadModel
from ..models.epidemiologia_model import EpidemiologiaModel
from ..models.indicadores_model import IndicadoresModel
from ..models.procedimientos_model import ProcedimientosModel
from ..models.territorio_model import TerritorioModel
from ..utils.filtros import PLANES_SEGURO, SERVICIOS
from .seguridad import requiere_login, requiere_modulo, tiene_modulo, usuario_actual

tablero_bp = Blueprint("tablero", __name__, url_prefix="/")


@tablero_bp.route("/")
@requiere_login
@requiere_modulo("tablero")
def panel():
    filtros = g.filtros
    usuario = usuario_actual()
    puede = lambda clave: tiene_modulo(usuario, clave)

    contexto = {
        "titulo": "Panel de indicadores",
        "catalogo_regiones": TerritorioModel.regiones(),
        "planes_disponibles": PLANES_SEGURO,
        "servicios_disponibles": SERVICIOS,
        "perfiles": PrioridadModel.listar_perfiles(),
        "global": IndicadoresModel.indicadores_globales(filtros),
        "planes": IndicadoresModel.distribucion_afiliados_por_plan(filtros),
        # Secciones condicionadas por modulo; si no esta habilitado, no se
        # consultan ni se renderizan ( menos consultas, menos datos expuestos).
        "ver_territorio": puede("territorio"),
        "ver_alertas": puede("alertas"),
        "ver_evolucion": puede("evolucion"),
        "ver_vigilancia": puede("vigilancia"),
        "ver_mortalidad": puede("mortalidad"),
    }

    if contexto["ver_territorio"]:
        brechas = IndicadoresModel.top_brechas_territorio(filtros, limite=10)
        contexto["brechas"] = brechas
        contexto["brechas_grafico"] = [
            {"etiqueta": f["territorio"], "valor": f["ratio_afiliados_cama"] or 0}
            for f in brechas
        ]

    if contexto["ver_alertas"]:
        contexto["alertas"] = IndicadoresModel.distribucion_alerta(filtros)
        contexto["criticos"] = ProcedimientosModel.ocupacion_critica(filtros, limite=10)
        contexto["inoperativos"] = ProcedimientosModel.inoperatividad_critica(
            filtros, limite=10
        )

    if contexto["ver_evolucion"]:
        contexto["series"] = IndicadoresModel.serie_temporal(filtros)

    # Mini-panoramas epidemiologicos de las dos dimensiones nuevas.
    if contexto["ver_vigilancia"]:
        dptos = EpidemiologiaModel.ira_por_departamento(filtros, limite=8)
        contexto["ira_departamentos"] = dptos
        contexto["ira_grafico"] = [
            {"etiqueta": d["departamento"], "valor": d["neumonias"] or 0}
            for d in dptos
        ]

    if contexto["ver_mortalidad"]:
        resumen = EpidemiologiaModel.resumen_covid(filtros)
        contexto["covid_resumen"] = resumen
        serie = EpidemiologiaModel.serie_covid_mensual(filtros)
        contexto["covid_grafico"] = [
            {"periodo": s["periodo"], "fallecidos": s["fallecidos"]}
            for s in serie
        ]

    return render_template("tablero/panel.html", **contexto)


@tablero_bp.route("/resumen")
@requiere_login
@requiere_modulo("tablero")
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
