"""Catalogo de modulos (secciones y graficos) del sistema SIBS.

Define que puede ver cada usuario. Vive fuera de `controllers/` para que
modelos, controladores y plantillas lo importen sin ciclos.

Reglas de vigencia de un modulo:
  1. ADMINISTRADOR: siempre todo.
  2. Usuario con filas en dbo.sys_permisos_usuario: esas filas lo definen.
  3. Sin filas: aplica `MODULOS_POR_ROL[rol]`.

El orden del dict es el orden del menu y el orden de aterrizaje.
"""

MODULOS = {
    "tablero": {
        "nombre": "Panel",
        "endpoint": "tablero.panel",
        "url_args": {},
        "descripcion": "KPIs globales, brechas de capacidad y series resumidas.",
    },
    "territorio": {
        "nombre": "Territorio",
        "endpoint": "analisis.territorio",
        "url_args": {},
        "descripcion": "Analisis territorial: afiliados, atenciones y capacidad.",
    },
    "ranking": {
        "nombre": "Ranking",
        "endpoint": "analisis.ranking",
        "url_args": {},
        "descripcion": "Ranking de establecimientos por indice de brecha.",
    },
    "establecimiento": {
        "nombre": "Establecimientos",
        "menu": False,  # la ficha exige codigo_ipress: se abre desde las listas
        "endpoint": "analisis.establecimiento",
        "url_args": {},  # la ficha exige codigo_ipress (se abre desde las listas)
        "descripcion": "Fichas de detalle: afiliacion, demanda, ocupacion y disponibilidad.",
    },
    "evolucion": {
        "nombre": "Evolucion",
        "endpoint": "analisis.evolucion",
        "url_args": {},
        "descripcion": "Evolucion temporal de los indicadores del periodo.",
    },
    "alertas": {
        "nombre": "Alertas",
        "endpoint": "analisis.alertas",
        "url_args": {},
        "descripcion": "Monitoreo de ocupacion critica e inoperatividad de recursos.",
    },
    "procedimientos": {
        "nombre": "Procedimientos",
        "endpoint": "analisis.procedimiento",
        "url_args": {"clave": "presion_afiliados"},
        "descripcion": "Procedimientos analiticos almacenados en la base.",
    },
    "vigilancia": {
        "nombre": "Vigilancia IRA",
        "endpoint": "analisis.vigilancia",
        "url_args": {},
        "descripcion": (
            "Vigilancia epidemiologica de IRA (dbo.dim_vigilancia_iras): "
            "neumonias, hospitalizaciones y defunciones por semana, ano y territorio."
        ),
    },
    "mortalidad": {
        "nombre": "Mortalidad COVID",
        "endpoint": "analisis.mortalidad",
        "url_args": {},
        "descripcion": (
            "Fallecidos por COVID-19 (dbo.dim_fallecidos_covid): serie temporal, "
            "criterios de casos, sexo y edad, territorios y cobertura de vacunacion."
        ),
    },
    "exportar": {
        "nombre": None,  # permiso transversal: no genera entrada de menu
        "endpoint": "analisis.exportar",
        "url_args": {},
        "descripcion": "Exportar resultados (CSV/XLSX) y consumir la API JSON.",
    },
}

# Claves que aparecen en el menu de navegacion: con nombre y marcadas como
# navegables (la ficha de establecimiento se abre desde las listas, no hay
# URL de menu porque exige codigo_ipress).
MODULOS_NAVEGABLES = [
    clave for clave, meta in MODULOS.items()
    if meta["nombre"] and meta.get("menu", True)
]

# Default por rol: la semilla que el administrador ajusta usuario por usuario.
MODULOS_POR_ROL = {
    "ADMINISTRADOR": set(MODULOS),
    "ANALISTA_SANITARIO": {
        "tablero", "territorio", "establecimiento", "evolucion",
        "procedimientos", "vigilancia", "exportar",
    },
    "FUNCIONARIO": {
        "ranking", "establecimiento", "exportar",
    },
    "MONITOREO": {
        "alertas", "evolucion", "vigilancia", "mortalidad",
    },
}

# Pantalla de aterrizaje por rol: el primer modulo navegable del order
# generico puede no ser el natural (al monitoreo le aterriza Evolucion
# antes de Alertas). Se define explicito; si el rol carece de ese modulo
# se usa el orden generico.
ROL_INICIO = {
    "ADMINISTRADOR": "tablero",
    "ANALISTA_SANITARIO": "tablero",
    "FUNCIONARIO": "ranking",
    "MONITOREO": "alertas",
}
