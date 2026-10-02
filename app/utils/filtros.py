"""Normalizacion de filtros de consulta y construccion del WHERE comun.

Los filtros son los exigidos por los requerimientos: periodo, region,
provincia, distrito, establecimiento (IPRESS), categoria, nivel y plan de
seguro. Este modulo los valida, aplica valores por defecto y produce el
fragmento SQL parametrizado que consumen los modelos.
"""

from datetime import date, datetime

# Bloques de recursos disponibles para el selector "servicio".
# Cada entrada declara el nombre real de las columnas en fact_capacidad_diaria:
# no todos los bloques usan los mismos sufijos (por ejemplo, el bloque global de
# camas se llama `total_camas` y no tiene equivalente `inoperativas`), y los
# ventiladores y monitores reportan "en uso" en lugar de "ocupadas".
SERVICIOS = {
    "CAMAS": {
        "nombre": "Camas (global)",
        "total": "total_camas",
        "operativas": "total_camas_operativas",
        "disponibles": "total_camas_disponibles",
        "ocupadas": "total_camas_ocupadas",
        "inoperativas": None,
    },
    "HOSPITALIZACION": {
        "nombre": "Hospitalizacion",
        "total": "hosp_total",
        "operativas": "hosp_operativas",
        "disponibles": "hosp_disponibles",
        "ocupadas": "hosp_ocupadas",
        "inoperativas": "hosp_inoperativas",
    },
    "UCI": {
        "nombre": "UCI",
        "total": "uci_total",
        "operativas": "uci_operativas",
        "disponibles": "uci_disponibles",
        "ocupadas": "uci_ocupadas",
        "inoperativas": "uci_inoperativas",
    },
    "UCIN": {
        "nombre": "UCIN (cuidado intermedio)",
        "total": "ucin_total",
        "operativas": "ucin_operativas",
        "disponibles": "ucin_disponibles",
        "ocupadas": "ucin_ocupadas",
        "inoperativas": None,
    },
    "EMERGENCIA": {
        "nombre": "Emergencia",
        "total": "emer_total",
        "operativas": "emer_operativas",
        "disponibles": "emer_disponibles",
        "ocupadas": "emer_ocupadas",
        "inoperativas": None,
    },
    "VENTILADORES": {
        "nombre": "Ventiladores",
        "total": "vent_total",
        "operativas": "vent_operativos",
        "disponibles": "vent_disponibles",
        "ocupadas": "vent_en_uso",
        "inoperativas": "vent_inoperativos",
    },
    "MONITORIZACION": {
        "nombre": "Monitorizacion",
        "total": "monito_total",
        "operativas": "monito_operativos",
        "disponibles": "monito_disponibles",
        "ocupadas": "monito_en_uso",
        "inoperativas": None,
    },
}

PLANES_SEGURO = {
    "GRATUITO": {"columna": "afiliados_sis_gratuito", "nombre": "SIS Gratuito"},
    "INDEPENDIENTE": {"columna": "afiliados_sis_independiente", "nombre": "SIS Independiente"},
    "PARA_TODOS": {"columna": "afiliados_sis_para_todos", "nombre": "SIS Para Todos"},
    "TOTAL": {"columna": "total_afiliados", "nombre": "Total afiliados"},
}

GRANULARIDADES = {
    "DIARIO": "Dia",
    "MENSUAL": "Mes",
    "TRIMESTRAL": "Trimestre",
    "ANUAL": "Anio",
}

# Columnas por las que se permite ordenar en las tablas del sistema
ORDENES_PERMITIDOS = {
    "region", "provincia", "distrito", "nombre_establecimiento", "categoria",
    "nivel", "institucion", "macroregion", "total_afiliados", "total_atenciones",
    "camas_operativas", "camas_disponibles", "camas_ocupadas", "tasa_ocupacion",
    "uci_operativas", "vent_operativos", "ratio_afiliados_cama", "puntaje",
    "prioridad", "codigo_ipress", "ultima_fecha", "dias_sobre_umbral",
    "tasa_inoperatividad", "pico_ocupacion", "afiliados_rurales",
    "presion_atencion", "poblacion_vulnerable", "dias_sin_reporte",
}


class FiltrosError(ValueError):
    """Filtros invalidos articulate 400."""


_FORMATOS_FECHA = ("%Y-%m-%d", "%d/%m/%Y", "%Y/%m/%d", "%d-%m-%Y")


def _a_fecha(valor, nombre_campo="fecha", por_defecto=None):
    """Convierte a `date` aceptando date, datetime o texto ISO/espanol.

    Los filtros llegan desde la capa web como cadenas y desde los servicios
    internos como `date`; normalizar aqui evita restas entre cadenas.
    """
    if valor in (None, "", "None"):
        return por_defecto
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    texto = str(valor).strip()
    # Se recorta la parte horaria si viene un ISO completo.
    if "T" in texto:
        texto = texto.split("T", 1)[0]
    elif " " in texto:
        texto = texto.split(" ", 1)[0]
    if not texto:
        return por_defecto
    for formato in _FORMATOS_FECHA:
        try:
            return datetime.strptime(texto, formato).date()
        except ValueError:
            continue
    raise FiltrosError(f"Fecha invalida en '{nombre_campo}': {valor}")


def _a_int(valor, nombre_campo, por_defecto=None, minimo=None, maximo=None):
    if valor in (None, "", "None"):
        return por_defecto
    try:
        numero = int(str(valor).strip())
    except (TypeError, ValueError):
        raise FiltrosError(f"Valor numerico invalido en '{nombre_campo}': {valor}")
    if minimo is not None and numero < minimo:
        numero = minimo
    if maximo is not None and numero > maximo:
        numero = maximo
    return numero


def _a_texto(valor, por_defecto=None, maximo=200):
    if valor in (None, "", "None"):
        return por_defecto
    texto = str(valor).strip()
    if not texto:
        return por_defecto
    return texto[:maximo]


class Filtros:
    """Contenedor normalizado de los filtros de analisis."""

    def __init__(
        self,
        fecha_inicio=None,
        fecha_fin=None,
        region=None,
        provincia=None,
        distrito=None,
        codigo_ipress=None,
        categoria=None,
        nivel=None,
        institucion=None,
        macroregion=None,
        plan_seguro=None,
        servicio=None,
        nivel_eess=None,
        granularidad="MENSUAL",
        umbral_ocupacion=85.0,
        pagina=1,
        por_pagina=50,
        orden=None,
        direccion="DESC",
    ):
        self.fecha_inicio = _a_fecha(fecha_inicio, "fecha_inicio")
        self.fecha_fin = _a_fecha(fecha_fin, "fecha_fin")
        if self.fecha_inicio and self.fecha_fin and self.fecha_fin < self.fecha_inicio:
            raise FiltrosError(
                "La fecha final no puede ser anterior a la fecha inicial."
            )
        self.region = _a_texto(region)
        self.provincia = _a_texto(provincia)
        self.distrito = _a_texto(distrito)
        self.codigo_ipress = _a_int(codigo_ipress, "codigo_ipress")
        self.categoria = _a_texto(categoria)
        self.nivel = _a_texto(nivel)
        self.institucion = _a_texto(institucion)
        self.macroregion = _a_texto(macroregion)
        self.plan_seguro = _a_texto(plan_seguro)
        self.servicio = _a_texto(servicio)
        self.nivel_eess = _a_texto(nivel_eess)
        granularidad = _a_texto(granularidad, "MENSUAL").upper()
        if granularidad not in GRANULARIDADES:
            granularidad = "MENSUAL"
        self.granularidad = granularidad
        try:
            self.umbral_ocupacion = float(umbral_ocupacion)
        except (TypeError, ValueError):
            self.umbral_ocupacion = 85.0
        if not 0 < self.umbral_ocupacion <= 100:
            self.umbral_ocupacion = 85.0
        self.pagina = _a_int(pagina, "pagina", 1, minimo=1) or 1
        self.por_pagina = _a_int(por_pagina, "por_pagina", 50, minimo=1, maximo=500) or 50
        self.orden = _a_texto(orden)
        direccion = _a_texto(direccion, "DESC").upper()
        self.direccion = direccion if direccion in ("ASC", "DESC") else "DESC"

    # -- acceso como diccionario (util para templates y JSON) ---------------
    def to_dict(self):
        return {
            "fecha_inicio": self.fecha_inicio,
            "fecha_fin": self.fecha_fin,
            "region": self.region,
            "provincia": self.provincia,
            "distrito": self.distrito,
            "codigo_ipress": self.codigo_ipress,
            "categoria": self.categoria,
            "nivel": self.nivel,
            "institucion": self.institucion,
            "macroregion": self.macroregion,
            "plan_seguro": self.plan_seguro,
            "servicio": self.servicio,
            "nivel_eess": self.nivel_eess,
            "granularidad": self.granularidad,
            "umbral_ocupacion": self.umbral_ocupacion,
            "pagina": self.pagina,
            "por_pagina": self.por_pagina,
            "orden": self.orden,
            "direccion": self.direccion,
        }

    @property
    def columna_afiliados(self):
        """Columna de afiliados segun el plan de seguro seleccionado."""
        plan = PLANES_SEGURO.get(self.plan_seguro, PLANES_SEGURO["TOTAL"])
        return plan["columna"]

    @property
    def nombre_plan(self):
        return PLANES_SEGURO.get(self.plan_seguro, PLANES_SEGURO["TOTAL"])["nombre"]

    @property
    def nombre_servicio(self):
        return SERVICIOS.get(self.servicio, SERVICIOS["CAMAS"])["nombre"]

    def dias_periodo(self):
        if not (self.fecha_inicio and self.fecha_fin):
            return 0
        return max(1, (self.fecha_fin - self.fecha_inicio).days + 1)

    def etiqueta_territorio(self):
        partes = []
        if self.region:
            partes.append(f"Region: {self.region}")
        if self.provincia:
            partes.append(f"Provincia: {self.provincia}")
        if self.distrito:
            partes.append(f"Distrito: {self.distrito}")
        if self.codigo_ipress:
            partes.append(f"IPRESS: {self.codigo_ipress}")
        if not partes:
            return "Todo el territorio"
        return " | ".join(partes)

    # -- construccion del WHERE sobre la vista geografica -------------------
    def where_geo(self, alias="g"):
        """Fragmento WHERE + parametros para filtrar por dim_ipress_ext."""
        condiciones = []
        params = []
        if self.region:
            condiciones.append(f"[{alias}].[region] = ?")
            params.append(self.region)
        if self.provincia:
            condiciones.append(f"[{alias}].[provincia] = ?")
            params.append(self.provincia)
        if self.distrito:
            condiciones.append(f"[{alias}].[distrito] = ?")
            params.append(self.distrito)
        if self.codigo_ipress:
            condiciones.append(f"[{alias}].[codigo_ipress] = ?")
            params.append(self.codigo_ipress)
        if self.categoria:
            condiciones.append(f"[{alias}].[categoria] = ?")
            params.append(self.categoria)
        if self.nivel:
            condiciones.append(f"[{alias}].[nivel] = ?")
            params.append(self.nivel)
        if self.institucion:
            condiciones.append(f"[{alias}].[institucion] = ?")
            params.append(self.institucion)
        if self.macroregion:
            condiciones.append(f"[{alias}].[macroregion] = ?")
            params.append(self.macroregion)
        return condiciones, params

    def where_tiempo(self, alias="t"):
        condiciones = []
        params = []
        if self.fecha_inicio:
            condiciones.append(f"[{alias}].[fecha_corte] >= ?")
            params.append(self.fecha_inicio)
        if self.fecha_fin:
            condiciones.append(f"[{alias}].[fecha_corte] <= ?")
            params.append(self.fecha_fin)
        return condiciones, params

    def es_territorial(self):
        return bool(self.region or self.provincia or self.distrito or self.codigo_ipress)


def desde_request(args, config, paginar=True):
    """Construye un objeto Filtros a partir de query string de Flask."""
    fecha_inicio = _a_fecha(args.get("fecha_inicio"), "fecha_inicio")
    fecha_fin = _a_fecha(args.get("fecha_fin"), "fecha_fin")

    if fecha_inicio is None and fecha_fin is None:
        fecha_inicio = _a_fecha(config.FECHA_INICIO_DEFECTO, "def", date(2023, 1, 1))
        fecha_fin = _a_fecha(config.FECHA_FIN_DEFECTO, "def", date(2023, 12, 31))
    elif fecha_inicio is None:
        fecha_inicio = fecha_fin
    elif fecha_fin is None:
        fecha_fin = fecha_inicio

    if fecha_inicio > fecha_fin:
        raise FiltrosError("La fecha de inicio no puede ser posterior a la fecha de fin.")

    servicio = _a_texto(args.get("servicio"), "CAMAS", 40)
    if servicio not in SERVICIOS:
        servicio = "CAMAS"

    plan = _a_texto(args.get("plan_seguro"), "TOTAL", 30)
    if plan not in PLANES_SEGURO:
        plan = "TOTAL"

    granularidad = _a_texto(args.get("granularidad"), "MENSUAL", 20).upper()
    if granularidad not in GRANULARIDADES:
        granularidad = "MENSUAL"

    nivel_eess = _a_texto(args.get("nivel_eess"), None, 20)
    direccion = _a_texto(args.get("direccion"), "DESC", 4).upper()
    if direccion not in ("ASC", "DESC"):
        direccion = "DESC"

    orden = _a_texto(args.get("orden"), None, 40)
    if orden and orden not in ORDENES_PERMITIDOS:
        orden = None

    por_pagina = config.FILAS_POR_PAGINA
    pagina = 1
    if paginar:
        por_pagina = _a_int(args.get("por_pagina"), "por_pagina", por_pagina, 10, 500)
        pagina = _a_int(args.get("pagina"), "pagina", 1, 1, None)

    return Filtros(
        fecha_inicio=fecha_inicio,
        fecha_fin=fecha_fin,
        region=_a_texto(args.get("region"), None),
        provincia=_a_texto(args.get("provincia"), None),
        distrito=_a_texto(args.get("distrito"), None),
        codigo_ipress=_a_int(args.get("codigo_ipress"), "codigo_ipress", None, 1),
        categoria=_a_texto(args.get("categoria"), None, 100),
        nivel=_a_texto(args.get("nivel"), None, 100),
        institucion=_a_texto(args.get("institucion"), None, 200),
        macroregion=_a_texto(args.get("macroregion"), None, 200),
        plan_seguro=plan,
        servicio=servicio,
        nivel_eess=nivel_eess,
        granularidad=granularidad,
        umbral_ocupacion=float(
            _a_int(args.get("umbral_ocupacion"), "umbral_ocupacion",
                   int(config.UMBRAL_OCUPACION_DEFECTO), 0, 100)
        ),
        pagina=pagina,
        por_pagina=por_pagina,
        orden=orden,
        direccion=direccion,
    )


def clausula_orden(filtros, columna, defecto="puntaje"):
    """Construye una clausula ORDER BY validada contra lista blanca."""
    columna = filtros.orden or columna or defecto
    if columna not in ORDENES_PERMITIDOS:
        columna = defecto if defecto in ORDENES_PERMITIDOS else "codigo_ipress"
    direccion = "ASC" if filtros.direccion == "ASC" else "DESC"
    return f"ORDER BY [{columna}] {direccion}"


def pagina_actual(total_filas, filtros):
    """Calcula la pagina efectiva tras paginar."""
    import math

    por_pagina = max(1, filtros.por_pagina)
    total_paginas = max(1, math.ceil((total_filas or 0) / por_pagina))
    pagina = min(filtros.pagina, total_paginas)
    return {
        "pagina": pagina,
        "total_paginas": total_paginas,
        "total_filas": total_filas or 0,
        "por_pagina": por_pagina,
        "desde": (pagina - 1) * por_pagina + 1 if (total_filas or 0) else 0,
        "hasta": min(pagina * por_pagina, total_filas or 0),
    }