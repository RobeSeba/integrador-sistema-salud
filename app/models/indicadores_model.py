"""Modelo de indicadores: afiliados, atenciones, capacidad y brechas.

Este modelo implementa el nucleo analitico del sistema sobre la estrella de
hechos:

  * fact_afiliados_sis     -> poblacion afiliada (mensual, foto de corte)
  * fact_atenciones        -> demanda registrada (mensual, flujo)
  * fact_capacidad_diaria  -> oferta instalada (diaria)

Los filtros territoriales se aplican sobre dbo.dim_ipress_ext, que resuelve la
geografia de los hechos que no estan catalogados en dim_ipress.

Convencion importante: cada CTE devuelve su fragmento SQL *y* la lista de
parametros en el mismo orden en que aparecen los '?' dentro del fragmento.
Quien arma la consulta final concatena los parametros en el mismo orden.
"""

from .base_model import BaseModel, normalizar_filas
from ..utils.filtros import SERVICIOS

VISTA_GEO = "dbo.dim_ipress_ext"


def _columnas_servicio(servicio):
    """Columnas reales del bloque de recurso elegido.

    No todos los bloques de fact_capacidad_diaria usan los mismos sufijos, por
    lo que se resuelve el nombre completo de cada columna en lugar de componer
    prefijos. Los sufijos inexistentes (p.ej. inoperativas en el bloque global
    de camas) se omiten de la consulta.
    """
    bloque = SERVICIOS.get(servicio, SERVICIOS["CAMAS"])
    columnas = {}
    for clave in ("total", "operativas", "disponibles", "ocupadas", "inoperativas"):
        nombre = bloque.get(clave)
        if nombre:
            columnas[clave] = nombre
    return columnas


def _where(condiciones):
    if not condiciones:
        return ""
    return "WHERE " + " AND ".join(condiciones)


class IndicadoresModel(BaseModel):
    """Consultas analiticas combinando los tres hechos."""

    # ==================================================================
    # CTEs reutilizables
    # ==================================================================
    @staticmethod
    def cte_afiliados(filtros):
        """Ultimo corte de afiliados dentro del periodo, por establecimiento.

        Los afiliados son un saldo de poblacion (no un flujo), por lo que se
        toma la foto mas reciente del periodo en lugar de sumar los cortes.
        El plan de seguro seleccionado define el denominador poblacional y se
        aplica aqui para que todo el calculo posterior sea coherente.
        La columna `rn` permite filtrar el ultimo corte al hacer el join.
        """
        plan = filtros.columna_afiliados
        condiciones, params = filtros.where_tiempo("f")
        condiciones_geo, params_geo = filtros.where_geo("g")
        sql = f"""
        af AS (
            SELECT f.codigo_ipress,
                   {plan}                                  AS afiliados,
                   ISNULL(f.afiliados_hombres, 0)          AS afiliados_hombres,
                   ISNULL(f.afiliados_mujeres, 0)          AS afiliados_mujeres,
                   ISNULL(f.afiliados_0_4_pediatrico, 0)    AS afiliados_0_4_pediatrico,
                   ISNULL(f.afiliados_5_14, 0)              AS afiliados_5_14,
                   ISNULL(f.afiliados_15_59_adultos, 0)     AS afiliados_15_59_adultos,
                   ISNULL(f.afiliados_60_mas_adulto_mayor, 0) AS afiliados_60_mas_adulto_mayor,
                   ISNULL(f.afiliados_mujeres_edad_fertil, 0) AS afiliados_mujeres_edad_fertil,
                   ISNULL(f.afiliados_urbano, 0)            AS afiliados_urbano,
                   ISNULL(f.afiliados_rural, 0)             AS afiliados_rural,
                   ISNULL(f.afiliados_vraem, 0)             AS afiliados_vraem,
                   f.fecha_corte                            AS fecha_afiliados,
                   ROW_NUMBER() OVER (
                       PARTITION BY f.codigo_ipress ORDER BY f.fecha_corte DESC
                   ) AS rn
            FROM dbo.fact_afiliados_sis f
            INNER JOIN {VISTA_GEO} g ON g.codigo_ipress = f.codigo_ipress
            {_where(condiciones + condiciones_geo)}
        )"""
        return sql, params + params_geo

    @staticmethod
    def cte_atenciones(filtros):
        """Atenciones del periodo agregadas por establecimiento (si es flujo)."""
        condiciones, params = filtros.where_tiempo("at")
        condiciones_geo, params_geo = filtros.where_geo("g")
        if filtros.nivel_eess:
            condiciones.append("at.nivel_eess = ?")
            params.append(filtros.nivel_eess)
        sql = f"""
        at AS (
            SELECT at.codigo_ipress,
                   SUM(ISNULL(at.total_atenciones, 0))           AS total_atenciones,
                   SUM(ISNULL(at.atenciones_emergencia, 0))      AS atenciones_emergencia,
                   SUM(ISNULL(at.atenciones_consulta_externa, 0)) AS atenciones_consulta_externa,
                   SUM(ISNULL(at.atenciones_hombres, 0))         AS atenciones_hombres,
                   SUM(ISNULL(at.atenciones_mujeres, 0))         AS atenciones_mujeres,
                   SUM(ISNULL(at.atenciones_00_04, 0))           AS atenciones_00_04,
                   SUM(ISNULL(at.atenciones_05_11, 0))           AS atenciones_05_11,
                   SUM(ISNULL(at.atenciones_12_17, 0))           AS atenciones_12_17,
                   SUM(ISNULL(at.atenciones_18_29, 0))           AS atenciones_18_29,
                   SUM(ISNULL(at.atenciones_30_59, 0))           AS atenciones_30_59,
                   SUM(ISNULL(at.atenciones_60_mas, 0))          AS atenciones_60_mas
            FROM dbo.fact_atenciones at
            INNER JOIN {VISTA_GEO} g ON g.codigo_ipress = at.codigo_ipress
            {_where(condiciones + condiciones_geo)}
            GROUP BY at.codigo_ipress
        )"""
        return sql, params + params_geo

    @staticmethod
    def cte_capacidad(filtros):
        """Capacidad del periodo por establecimiento.

        Los recursos (camas, UCI, ventiladores) son inventarios: se promedian
        los valores diarios en lugar de sumarlos, para que el resultado sea
        comparable entre periodos de distinta longitud. Los conteos de dias
        si se acumulan.
        """
        condiciones, params = filtros.where_tiempo("c")
        condiciones_geo, params_geo = filtros.where_geo("g")
        col = _columnas_servicio(filtros.servicio)
        col_inoperativas = (
            f"AVG(CAST(ISNULL(c.{col['inoperativas']}, 0) AS FLOAT)) AS recursos_inoperativos,"
            if col.get("inoperativas") else
            "CAST(NULL AS FLOAT) AS recursos_inoperativos,"
        )
        sql = f"""
        cp AS (
            SELECT c.codigo_ipress,
                   AVG(CAST(ISNULL(c.{col['total']}, 0) AS FLOAT))          AS recursos_instalados,
                   AVG(CAST(ISNULL(c.{col['operativas']}, 0) AS FLOAT))      AS recursos_operativos,
                   AVG(CAST(ISNULL(c.{col['disponibles']}, 0) AS FLOAT))     AS recursos_disponibles,
                   AVG(CAST(ISNULL(c.{col['ocupadas']}, 0) AS FLOAT))        AS recursos_ocupados,
                   {col_inoperativas}
                   AVG(CAST(ISNULL(c.tasa_ocupacion_global, 0) AS FLOAT))  AS tasa_ocupacion,
                   MAX(CAST(ISNULL(c.tasa_ocupacion_global, 0) AS FLOAT))  AS pico_ocupacion,
                   SUM(CASE WHEN c.tasa_ocupacion_global >= ? THEN 1 ELSE 0 END) AS dias_sobre_umbral,
                   COUNT(DISTINCT c.fecha_corte)            AS dias_reportados,
                   MAX(c.fecha_corte)                       AS ultima_fecha,
                   CAST(SUM(ISNULL(c.vent_inoperativos, 0)) AS FLOAT)
                       / NULLIF(SUM(ISNULL(c.vent_operativos, 0)), 0) * 100.0  AS porc_vent_inoperativo,
                   CAST(SUM(ISNULL(c.uci_inoperativas, 0)) AS FLOAT)
                       / NULLIF(SUM(ISNULL(c.uci_operativas, 0)), 0) * 100.0    AS porc_uci_inoperativo,
                   CAST(SUM(ISNULL(c.hosp_inoperativas, 0)) AS FLOAT)
                       / NULLIF(SUM(ISNULL(c.hosp_operativas, 0)), 0) * 100.0  AS porc_hosp_inoperativo,
                   CAST(SUM(ISNULL(c.vent_en_uso, 0)) AS FLOAT)
                       / NULLIF(SUM(ISNULL(c.vent_operativos, 0)), 0) * 100.0  AS tasa_uso_ventiladores,
                   SUM(ISNULL(c.uci_operativas, 0))         AS uci_operativas,
                   SUM(ISNULL(c.uci_ocupadas, 0))           AS uci_ocupadas,
                   SUM(ISNULL(c.emer_operativas, 0))        AS emer_operativas,
                   SUM(ISNULL(c.emer_ocupadas, 0))          AS emer_ocupadas,
                   SUM(ISNULL(c.covid_camas_ocupadas, 0))   AS covid_camas_ocupadas,
                   SUM(ISNULL(c.no_covid_camas_ocupadas, 0)) AS no_covid_camas_ocupadas,
                   SUM(CASE WHEN c.nivel_alerta = N'ROJO' THEN 1 ELSE 0 END)     AS dias_alerta_roja,
                   SUM(CASE WHEN c.nivel_alerta = N'AMARILLO' THEN 1 ELSE 0 END) AS dias_alerta_amarilla
            FROM dbo.fact_capacidad_diaria c
            INNER JOIN {VISTA_GEO} g ON g.codigo_ipress = c.codigo_ipress
            {_where(condiciones + condiciones_geo)}
            GROUP BY c.codigo_ipress
        )"""
        # El umbral aparece primero dentro del fragmento, luego las condiciones.
        return sql, [filtros.umbral_ocupacion] + params + params_geo

    @classmethod
    def _base_por_establecimiento(cls, filtros):
        """Devuelve (ctes, params) con af + at + cp listos para componer."""
        cte_af, params_af = cls.cte_afiliados(filtros)
        cte_at, params_at = cls.cte_atenciones(filtros)
        cte_cp, params_cp = cls.cte_capacidad(filtros)
        ctes = ",\n        ".join(
            p.strip().rstrip(",") for p in (cte_af, cte_at, cte_cp)
        )
        return ctes, params_af + params_at + params_cp

    # ==================================================================
    # Indicadores por establecimiento (base del ranking)
    # ==================================================================
    @classmethod
    def indicadores_establecimiento(cls, filtros, codigo_ipress=None):
        """Un registro por establecimiento con todos los indicadores.

        Los tres hechos se combinan con LEFT JOIN desde la vista geografica
        para no perder establecimientos que solo reporten uno de los tres
        (por ejemplo, presion de afiliados sin reporte de capacidad).
        """
        ctes, params = cls._base_por_establecimiento(filtros)

        # Los filtros territoriales ya se aplicaron dentro de los CTE; aqui se
        # repiten sobre el conjunto final para no perder EESS que solo tengan
        # algun hecho con datos.
        condiciones, params_extra = filtros.where_geo("g")
        if codigo_ipress:
            condiciones.append("[g].[codigo_ipress] = ?")
            params_extra.append(codigo_ipress)
        params = params + params_extra

        sql = f"""
        WITH {ctes}
        , base AS (
            SELECT g.codigo_ipress, g.nombre_establecimiento, g.categoria, g.nivel,
                   g.institucion, g.grupo, g.sub_grupo, g.macroregion, g.ubigeo,
                   g.region, g.provincia, g.distrito, g.en_dim_ipress,
                   af.afiliados, af.afiliados_hombres, af.afiliados_mujeres,
                   af.afiliados_0_4_pediatrico, af.afiliados_5_14,
                   af.afiliados_15_59_adultos, af.afiliados_60_mas_adulto_mayor,
                   af.afiliados_mujeres_edad_fertil, af.afiliados_urbano,
                   af.afiliados_rural, af.afiliados_vraem, af.fecha_afiliados,
                   at.total_atenciones, at.atenciones_emergencia,
                   at.atenciones_consulta_externa, at.atenciones_hombres,
                   at.atenciones_mujeres, at.atenciones_00_04, at.atenciones_05_11,
                   at.atenciones_12_17, at.atenciones_18_29, at.atenciones_30_59,
                   at.atenciones_60_mas,
                   cp.recursos_instalados, cp.recursos_operativos,
                   cp.recursos_disponibles, cp.recursos_ocupados,
                   cp.recursos_inoperativos, cp.tasa_ocupacion, cp.pico_ocupacion,
                   cp.dias_sobre_umbral, cp.dias_reportados, cp.ultima_fecha,
                   cp.porc_vent_inoperativo, cp.porc_uci_inoperativo,
                   cp.porc_hosp_inoperativo, cp.tasa_uso_ventiladores,
                   cp.uci_operativas, cp.uci_ocupadas, cp.emer_operativas,
                   cp.emer_ocupadas, cp.covid_camas_ocupadas,
                   cp.no_covid_camas_ocupadas, cp.dias_alerta_roja,
                   cp.dias_alerta_amarilla
            FROM {VISTA_GEO} g
            LEFT JOIN af ON af.codigo_ipress = g.codigo_ipress AND af.rn = 1
            LEFT JOIN at ON at.codigo_ipress = g.codigo_ipress
            LEFT JOIN cp ON cp.codigo_ipress = g.codigo_ipress
            WHERE 1 = 1
        )
        SELECT *,
               CAST(ISNULL(afiliados, 0) AS FLOAT)
                   / NULLIF(recursos_operativos, 0)                    AS ratio_afiliados_cama,
               CAST(ISNULL(total_atenciones, 0) AS FLOAT)
                   / NULLIF(afiliados, 0) * 1000.0                      AS presion_atencion,
               CAST(ISNULL(atenciones_emergencia, 0) AS FLOAT)
                   / NULLIF(emer_operativas, 0)                         AS presion_emergencia,
               CAST(ISNULL(afiliados_rural, 0) AS FLOAT)
                   / NULLIF(afiliados, 0) * 100.0                       AS porc_rural,
               CAST(ISNULL(afiliados_0_4_pediatrico, 0)
                     + ISNULL(afiliados_60_mas_adulto_mayor, 0)
                     + ISNULL(afiliados_mujeres_edad_fertil, 0) AS FLOAT)
                   / NULLIF(afiliados, 0) * 100.0                       AS porc_vulnerable,
               ROUND((ISNULL(porc_vent_inoperativo, 0)
                    + ISNULL(porc_uci_inoperativo, 0)
                    + ISNULL(porc_hosp_inoperativo, 0)) / 3.0, 2)      AS tasa_inoperatividad,
               CASE WHEN ISNULL(uci_operativas, 0) > 0 THEN 1.0 ELSE 0.0 END AS cobertura_uci,
               CAST({filtros.dias_periodo()} - ISNULL(dias_reportados, 0) AS FLOAT) AS dias_sin_reporte
        FROM base g
        {_where(condiciones)}
        """
        return normalizar_filas(cls.consultar(sql, params))

    # ==================================================================
    # Indicadores agregados por territorio
    # ==================================================================
    @classmethod
    def indicadores_territorio(cls, filtros, nivel="region", solo_con_capacidad=False):
        """Agrega los tres hechos en el nivel territorial solicitado."""
        columnas = {
            "region": "[g].[region]",
            "provincia": "[g].[provincia]",
            "distrito": "[g].[distrito]",
            "categoria": "[g].[categoria]",
            "nivel": "[g].[nivel]",
            "institucion": "[g].[institucion]",
            "macroregion": "[g].[macroregion]",
        }
        nivel = nivel.lower()
        columna = columnas.get(nivel, columnas["region"])

        ctes, params = cls._base_por_establecimiento(filtros)
        condiciones, params_extra = filtros.where_geo("g")
        params = params + params_extra

        join_cp = "LEFT JOIN cp ON cp.codigo_ipress = g.codigo_ipress"
        if solo_con_capacidad:
            join_cp = "INNER JOIN cp ON cp.codigo_ipress = g.codigo_ipress"

        sql = f"""
        WITH {ctes}
        , territorio AS (
            SELECT g.codigo_ipress,
                   {columna} AS territorio,
                   -- Se replican las columnas geograficas para que el WHERE
                   -- externo (filtros.where_geo) pueda referirse a [g].[region],
                   -- [g].[provincia], etc. sobre esta CTE.
                   g.region, g.provincia, g.distrito,
                   g.categoria, g.nivel, g.institucion, g.macroregion,
                   af.afiliados, af.afiliados_rural,
                   af.afiliados_0_4_pediatrico,
                   af.afiliados_60_mas_adulto_mayor, af.afiliados_mujeres_edad_fertil,
                   at.total_atenciones, at.atenciones_emergencia,
                   at.atenciones_consulta_externa,
                   cp.recursos_instalados, cp.recursos_operativos,
                   cp.recursos_disponibles, cp.recursos_ocupados,
                   cp.tasa_ocupacion, cp.pico_ocupacion, cp.dias_sobre_umbral,
                   cp.dias_reportados, cp.uci_operativas, cp.emer_operativas,
                   cp.porc_vent_inoperativo, cp.porc_uci_inoperativo,
                   cp.porc_hosp_inoperativo
            FROM {VISTA_GEO} g
            LEFT JOIN af ON af.codigo_ipress = g.codigo_ipress AND af.rn = 1
            LEFT JOIN at ON at.codigo_ipress = g.codigo_ipress
            {join_cp}
        )
        SELECT g.territorio AS territorio,
               COUNT(*)                                          AS establecimientos,
               SUM(ISNULL(g.dias_reportados, 0))                  AS dias_reporte,
               SUM(ISNULL(g.afiliados, 0))                        AS total_afiliados,
               SUM(ISNULL(g.total_atenciones, 0))                AS total_atenciones,
               SUM(ISNULL(g.atenciones_emergencia, 0))           AS atenciones_emergencia,
               SUM(ISNULL(g.atenciones_consulta_externa, 0))     AS atenciones_consulta_externa,
               SUM(ISNULL(g.afiliados_rural, 0))                 AS afiliados_rural,
               SUM(ISNULL(g.afiliados_0_4_pediatrico, 0)
                   + ISNULL(g.afiliados_60_mas_adulto_mayor, 0)
                   + ISNULL(g.afiliados_mujeres_edad_fertil, 0)) AS poblacion_vulnerable,
               ROUND(SUM(ISNULL(g.recursos_instalados, 0)), 2)    AS recursos_instalados,
               ROUND(SUM(ISNULL(g.recursos_operativos, 0)), 2)    AS recursos_operativos,
               ROUND(SUM(ISNULL(g.recursos_disponibles, 0)), 2)   AS recursos_disponibles,
               ROUND(SUM(ISNULL(g.recursos_ocupados, 0)), 2)      AS recursos_ocupados,
               SUM(ISNULL(g.uci_operativas, 0))                  AS uci_operativas,
               SUM(ISNULL(g.emer_operativas, 0))                 AS emer_operativas,
               SUM(ISNULL(g.dias_sobre_umbral, 0))                AS dias_sobre_umbral,
               ROUND(CAST(SUM(ISNULL(g.recursos_ocupados, 0)) AS FLOAT)
                   / NULLIF(SUM(ISNULL(g.recursos_operativos, 0)), 0) * 100.0, 2) AS tasa_ocupacion,
               ROUND(MAX(ISNULL(g.pico_ocupacion, 0)), 2)         AS pico_ocupacion,
               ROUND(CAST(SUM(ISNULL(g.afiliados, 0)) AS FLOAT)
                   / NULLIF(SUM(ISNULL(g.recursos_operativos, 0)), 0), 2)          AS ratio_afiliados_cama,
               ROUND(CAST(SUM(ISNULL(g.total_atenciones, 0)) AS FLOAT)
                   / NULLIF(SUM(ISNULL(g.afiliados, 0)), 0) * 1000.0, 2)            AS presion_atencion,
               ROUND(CAST(SUM(ISNULL(g.atenciones_emergencia, 0)) AS FLOAT)
                   / NULLIF(SUM(ISNULL(g.emer_operativas, 0)), 0), 2)               AS presion_emergencia,
               ROUND(CAST(SUM(ISNULL(g.afiliados_rural, 0)) AS FLOAT)
                   / NULLIF(SUM(ISNULL(g.afiliados, 0)), 0) * 100.0, 2)             AS porc_rural,
               ROUND(CAST(SUM(ISNULL(g.afiliados_0_4_pediatrico, 0)
                          + ISNULL(g.afiliados_60_mas_adulto_mayor, 0)
                          + ISNULL(g.afiliados_mujeres_edad_fertil, 0)) AS FLOAT)
                   / NULLIF(SUM(ISNULL(g.afiliados, 0)), 0) * 100.0, 2)             AS porc_vulnerable,
               ROUND(CAST(SUM(ISNULL(g.porc_vent_inoperativo, 0)
                          + ISNULL(g.porc_uci_inoperativo, 0)
                          + ISNULL(g.porc_hosp_inoperativo, 0)) AS FLOAT)
                   / NULLIF(COUNT(CASE WHEN ISNULL(g.recursos_instalados, 0) > 0
                                       THEN 1 END), 0), 2)                           AS tasa_inoperatividad
        FROM territorio g
        WHERE g.territorio IS NOT NULL AND LEN(TRIM(g.territorio)) > 0
        {("AND " + " AND ".join(condiciones)) if condiciones else ""}
        GROUP BY g.territorio
        """
        return normalizar_filas(cls.consultar(sql, params))

    # ==================================================================
    # Series temporales
    # ==================================================================
    @staticmethod
    def _expresion_periodo(alias, granularidad):
        grano = {
            "DIARIO": f"CONVERT(CHAR(10), {alias}.fecha_corte, 23)",
            "MENSUAL": f"CONVERT(CHAR(7), {alias}.fecha_corte, 120)",
            "TRIMESTRAL": (
                f"CONVERT(CHAR(4), {alias}.fecha_corte, 112) + '-T' + "
                f"CONVERT(CHAR(1), DATEPART(QQ, {alias}.fecha_corte), 1)"
            ),
            "ANUAL": f"CONVERT(CHAR(4), {alias}.fecha_corte, 112)",
        }
        return grano.get((granularidad or "MENSUAL").upper(), grano["MENSUAL"])

    @classmethod
    def serie_temporal(cls, filtros, granularidad="MENSUAL"):
        """Serie temporal de los indicadores principales del territorio."""
        g_af = cls._expresion_periodo("f", granularidad)
        g_at = cls._expresion_periodo("at", granularidad)
        g_cp = cls._expresion_periodo("c", granularidad)

        cond_af, params_af = filtros.where_tiempo("f")
        cond_at, params_at = filtros.where_tiempo("at")
        cond_cp, params_cp = filtros.where_tiempo("c")
        cond_geo, params_geo = filtros.where_geo("g")

        # Los filtros territoriales se combinan por hecho; se repiten porque
        # cada CTE declara su propio JOIN contra la vista geografica.
        sql = f"""
        WITH af AS (
            SELECT {g_af} AS periodo,
                   SUM(ISNULL(f.{filtros.columna_afiliados}, 0)) AS afiliados,
                   SUM(ISNULL(f.afiliados_rural, 0))              AS afiliados_rural,
                   SUM(ISNULL(f.afiliados_0_4_pediatrico, 0)
                       + ISNULL(f.afiliados_60_mas_adulto_mayor, 0)
                       + ISNULL(f.afiliados_mujeres_edad_fertil, 0)) AS poblacion_vulnerable
            FROM dbo.fact_afiliados_sis f
            INNER JOIN {VISTA_GEO} g ON g.codigo_ipress = f.codigo_ipress
            {_where(cond_af + cond_geo)}
            GROUP BY {g_af}
        ),
        at AS (
            SELECT {g_at} AS periodo,
                   SUM(ISNULL(at.total_atenciones, 0))       AS total_atenciones,
                   SUM(ISNULL(at.atenciones_emergencia, 0))  AS atenciones_emergencia
            FROM dbo.fact_atenciones at
            INNER JOIN {VISTA_GEO} g ON g.codigo_ipress = at.codigo_ipress
            {_where(cond_at + cond_geo)}
            GROUP BY {g_at}
        ),
        cp AS (
            SELECT {g_cp} AS periodo,
                   AVG(CAST(ISNULL(c.total_camas_operativas, 0) AS FLOAT))   AS camas_operativas,
                   AVG(CAST(ISNULL(c.total_camas_disponibles, 0) AS FLOAT))  AS camas_disponibles,
                   AVG(CAST(ISNULL(c.total_camas_ocupadas, 0) AS FLOAT))     AS camas_ocupadas,
                   AVG(CAST(ISNULL(c.tasa_ocupacion_global, 0) AS FLOAT))    AS tasa_ocupacion,
                   MAX(CAST(ISNULL(c.tasa_ocupacion_global, 0) AS FLOAT))    AS pico_ocupacion,
                   SUM(CASE WHEN c.tasa_ocupacion_global >= ? THEN 1 ELSE 0 END) AS dias_sobre_umbral,
                   SUM(CAST(ISNULL(c.vent_inoperativos, 0) AS FLOAT))        AS vent_inoperativos,
                   SUM(CAST(ISNULL(c.vent_operativos, 0) AS FLOAT))          AS vent_operativos,
                   COUNT(*)                                                 AS registros
            FROM dbo.fact_capacidad_diaria c
            INNER JOIN {VISTA_GEO} g ON g.codigo_ipress = c.codigo_ipress
            {_where(cond_cp + cond_geo)}
            GROUP BY {g_cp}
        ),
        periodos AS (
            SELECT periodo FROM af
            UNION SELECT periodo FROM at
            UNION SELECT periodo FROM cp
        )
        SELECT p.periodo,
               ISNULL(a.afiliados, 0)                AS total_afiliados,
               ISNULL(a.afiliados_rural, 0)          AS afiliados_rural,
               ISNULL(a.poblacion_vulnerable, 0)     AS poblacion_vulnerable,
               ISNULL(d.total_atenciones, 0)         AS total_atenciones,
               ISNULL(d.atenciones_emergencia, 0)    AS atenciones_emergencia,
               ROUND(ISNULL(c.camas_operativas, 0), 2)  AS camas_operativas,
               ROUND(ISNULL(c.camas_disponibles, 0), 2) AS camas_disponibles,
               ROUND(ISNULL(c.camas_ocupadas, 0), 2)    AS camas_ocupadas,
               ROUND(ISNULL(c.tasa_ocupacion, 0), 2)    AS tasa_ocupacion,
               ROUND(ISNULL(c.pico_ocupacion, 0), 2)    AS pico_ocupacion,
               ISNULL(c.vent_inoperativos, 0)        AS vent_inoperativos,
               ISNULL(c.vent_operativos, 0)          AS vent_operativos,
               ISNULL(c.dias_sobre_umbral, 0)        AS dias_sobre_umbral,
               ISNULL(c.registros, 0)                AS registros_capacidad,
               ROUND(CAST(ISNULL(d.total_atenciones, 0) AS FLOAT)
                   / NULLIF(ISNULL(a.afiliados, 0), 0) * 1000.0, 2)         AS presion_atencion,
               ROUND(CAST(ISNULL(a.afiliados_rural, 0) AS FLOAT)
                   / NULLIF(ISNULL(a.afiliados, 0), 0) * 100.0, 2)           AS porc_rural
        FROM periodos p
        LEFT JOIN af a ON a.periodo = p.periodo
        LEFT JOIN at d ON d.periodo = p.periodo
        LEFT JOIN cp c ON c.periodo = p.periodo
        ORDER BY p.periodo
        """
        params = (
            params_af
            + params_geo
            + params_at
            + params_geo
            + [filtros.umbral_ocupacion]
            + params_cp
            + params_geo
        )
        return normalizar_filas(cls.consultar(sql, params))

    # ==================================================================
    # Distribuciones para el dashboard
    # ==================================================================
    @classmethod
    def distribucion_alerta(cls, filtros):
        condiciones, params = filtros.where_tiempo("c")
        cond_geo, params_geo = filtros.where_geo("g")
        sql = f"""
            SELECT ISNULL(c.nivel_alerta, 'SIN DATO') AS nivel_alerta,
                   COUNT(*) AS registros,
                   COUNT(DISTINCT c.codigo_ipress) AS establecimientos
            FROM dbo.fact_capacidad_diaria c
            INNER JOIN {VISTA_GEO} g ON g.codigo_ipress = c.codigo_ipress
            {_where(condiciones + cond_geo)}
            GROUP BY c.nivel_alerta
            ORDER BY CASE c.nivel_alerta
                        WHEN 'ROJO' THEN 1 WHEN 'AMARILLO' THEN 2
                        WHEN 'VERDE' THEN 3 ELSE 4 END
        """
        return normalizar_filas(cls.consultar(sql, params + params_geo))

    @classmethod
    def distribucion_afiliados_por_plan(cls, filtros):
        condiciones, params = filtros.where_tiempo("f")
        cond_geo, params_geo = filtros.where_geo("g")
        sql = f"""
            SELECT SUM(ISNULL(f.afiliados_sis_gratuito, 0))     AS gratuito,
                   SUM(ISNULL(f.afiliados_sis_independiente, 0)) AS independiente,
                   SUM(ISNULL(f.afiliados_sis_para_todos, 0))    AS para_todos,
                   SUM(ISNULL(f.total_afiliados, 0))            AS total,
                   SUM(ISNULL(f.afiliados_urbano, 0))           AS urbano,
                   SUM(ISNULL(f.afiliados_rural, 0))            AS rural,
                   SUM(ISNULL(f.afiliados_vraem, 0))            AS vraem
            FROM dbo.fact_afiliados_sis f
            INNER JOIN {VISTA_GEO} g ON g.codigo_ipress = f.codigo_ipress
            {_where(condiciones + cond_geo)}
        """
        return normalizar_filas(cls.consultar(sql, params + params_geo))

    @classmethod
    def distribucion_por_categoria(cls, filtros):
        """Camas y ocupacion promedio por categoria de establecimiento."""
        condiciones, params = filtros.where_tiempo("c")
        cond_geo, params_geo = filtros.where_geo("g")
        sql = f"""
            SELECT g.categoria,
                   COUNT(DISTINCT c.codigo_ipress) AS establecimientos,
                   ROUND(AVG(CAST(ISNULL(c.total_camas_operativas, 0) AS FLOAT)), 2) AS camas_promedio,
                   ROUND(AVG(CAST(ISNULL(c.tasa_ocupacion_global, 0) AS FLOAT)), 2) AS ocupacion_promedio
            FROM dbo.fact_capacidad_diaria c
            INNER JOIN {VISTA_GEO} g ON g.codigo_ipress = c.codigo_ipress
            {_where(condiciones + cond_geo)}
            GROUP BY g.categoria
            ORDER BY g.categoria
        """
        return normalizar_filas(cls.consultar(sql, params + params_geo))

    @classmethod
    def top_brechas_territorio(cls, filtros, nivel="region", limite=10):
        """Territorios con mayor razon de afiliados por cama operativa."""
        filas = cls.indicadores_territorio(filtros, nivel=nivel)
        filas = [f for f in filas if (f.get("ratio_afiliados_cama") or 0) > 0]
        filas.sort(key=lambda f: f["ratio_afiliados_cama"], reverse=True)
        return filas[:limite]

    # ==================================================================
    # Ficha completa de un establecimiento
    # ==================================================================
    @classmethod
    def ficha_establecimiento(cls, filtros, codigo_ipress):
        """Indicadores de afiliacion, demanda, ocupacion y disponibilidad."""
        registros = cls.indicadores_establecimiento(filtros, codigo_ipress)
        return registros[0] if registros else None

    @classmethod
    def composicion_poblacional(cls, codigo_ipress):
        """Distribucion de afiliados por sexo, edad y plan (ultimo corte)."""
        sql = """
            SELECT TOP 1 fecha_corte, total_afiliados,
                   afiliados_hombres, afiliados_mujeres,
                   afiliados_0_4_pediatrico, afiliados_5_14,
                   afiliados_15_59_adultos, afiliados_60_mas_adulto_mayor,
                   afiliados_mujeres_edad_fertil,
                   afiliados_sis_gratuito, afiliados_sis_independiente,
                   afiliados_sis_para_todos,
                   afiliados_urbano, afiliados_rural, afiliados_vraem
            FROM dbo.fact_afiliados_sis
            WHERE codigo_ipress = ?
            ORDER BY fecha_corte DESC
        """
        return cls.consultar_uno(sql, [codigo_ipress])

    @classmethod
    def composicion_atenciones(cls, codigo_ipress, fecha_inicio, fecha_fin):
        """Distribucion de atenciones por sexo y grupo etario del EESS."""
        sql = """
            SELECT SUM(ISNULL(atenciones_hombres, 0))           AS hombres,
                   SUM(ISNULL(atenciones_mujeres, 0))           AS mujeres,
                   SUM(ISNULL(atenciones_00_04, 0))             AS edad_00_04,
                   SUM(ISNULL(atenciones_05_11, 0))             AS edad_05_11,
                   SUM(ISNULL(atenciones_12_17, 0))             AS edad_12_17,
                   SUM(ISNULL(atenciones_18_29, 0))             AS edad_18_29,
                   SUM(ISNULL(atenciones_30_59, 0))             AS edad_30_59,
                   SUM(ISNULL(atenciones_60_mas, 0))            AS edad_60_mas,
                   SUM(ISNULL(atenciones_emergencia, 0))        AS emergencia,
                   SUM(ISNULL(atenciones_consulta_externa, 0))  AS consulta_externa,
                   SUM(ISNULL(total_atenciones, 0))             AS total
            FROM dbo.fact_atenciones
            WHERE codigo_ipress = ? AND fecha_corte BETWEEN ? AND ?
        """
        return cls.consultar_uno(sql, [codigo_ipress, fecha_inicio, fecha_fin])

    @classmethod
    def capacidad_diaria(cls, codigo_ipress, fecha_inicio, fecha_fin):
        """Serie diaria de capacidad del establecimiento."""
        sql = """
            SELECT fecha_corte, uci_total, uci_operativas, uci_ocupadas,
                   uci_inoperativas, hosp_total, hosp_operativas, hosp_ocupadas,
                   hosp_inoperativas, emer_total, emer_operativas, emer_ocupadas,
                   total_camas, total_camas_operativas, total_camas_ocupadas,
                   total_camas_disponibles, tasa_ocupacion_global,
                   vent_total, vent_operativos, vent_en_uso, vent_inoperativos,
                   tasa_uso_ventiladores, nivel_alerta
            FROM dbo.fact_capacidad_diaria
            WHERE codigo_ipress = ? AND fecha_corte BETWEEN ? AND ?
            ORDER BY fecha_corte
        """
        return normalizar_filas(cls.consultar(sql, [codigo_ipress, fecha_inicio, fecha_fin]))

    @classmethod
    def capacidad_resumen(cls, codigo_ipress, fecha_inicio, fecha_fin):
        """Maximos, minimos y promedios de la capacidad diaria del EESS."""
        sql = """
            SELECT COUNT(*) AS dias_reporte,
                   MAX(fecha_corte) AS ultima_fecha,
                   ROUND(AVG(CAST(ISNULL(total_camas, 0) AS FLOAT)), 2)          AS camas_promedio,
                   MAX(ISNULL(total_camas, 0))                                   AS camas_maximo,
                   ROUND(AVG(CAST(ISNULL(total_camas_ocupadas, 0) AS FLOAT)), 2) AS ocupadas_promedio,
                   ROUND(AVG(CAST(ISNULL(tasa_ocupacion_global, 0) AS FLOAT)), 2) AS ocupacion_promedio,
                   MAX(ISNULL(tasa_ocupacion_global, 0))                        AS ocupacion_maxima,
                   ROUND(AVG(CAST(ISNULL(tasa_ocupacion_uci, 0) AS FLOAT)), 2)   AS ocupacion_uci_promedio,
                   ROUND(AVG(CAST(ISNULL(tasa_ocupacion_hosp, 0) AS FLOAT)), 2)  AS ocupacion_hosp_promedio,
                   SUM(CASE WHEN tasa_ocupacion_global >= 85 THEN 1 ELSE 0 END)  AS dias_sobre_85,
                   SUM(CASE WHEN nivel_alerta = 'ROJO' THEN 1 ELSE 0 END)        AS dias_alerta_roja,
                   SUM(CASE WHEN nivel_alerta = 'AMARILLO' THEN 1 ELSE 0 END)    AS dias_alerta_amarilla
            FROM dbo.fact_capacidad_diaria
            WHERE codigo_ipress = ? AND fecha_corte BETWEEN ? AND ?
        """
        return cls.consultar_uno(sql, [codigo_ipress, fecha_inicio, fecha_fin])

    # ==================================================================
    # Indicadores globales (tarjetas del dashboard)
    # ==================================================================
    @classmethod
    def indicadores_globales(cls, filtros):
        """Cifras clave del territorio y periodo seleccionados."""
        ctes, params = cls._base_por_establecimiento(filtros)
        condiciones, params_extra = filtros.where_geo("g")
        params = params + params_extra
        sql = f"""
        WITH {ctes}
        , base AS (
            SELECT g.codigo_ipress, g.region, g.provincia, g.distrito,
                   -- Se replican las columnas de la dimension que usa
                   -- filtros.where_geo (categoria, nivel, institucion,
                   -- macroregion): sin ellas el WHERE externo no podria
                   -- referirse a [g].[categoria] y la consulta fallaria.
                   g.categoria, g.nivel, g.institucion, g.macroregion,
                   af.afiliados, af.afiliados_rural, af.afiliados_urbano,
                   af.afiliados_0_4_pediatrico, af.afiliados_60_mas_adulto_mayor,
                   af.afiliados_mujeres_edad_fertil,
                   at.total_atenciones, at.atenciones_emergencia,
                   cp.recursos_instalados, cp.recursos_operativos,
                   cp.recursos_disponibles, cp.recursos_ocupados,
                   cp.tasa_ocupacion, cp.dias_reportados, cp.dias_sobre_umbral,
                   cp.uci_operativas, cp.uci_ocupadas,
                   cp.porc_vent_inoperativo, cp.porc_uci_inoperativo,
                   cp.porc_hosp_inoperativo, cp.dias_alerta_roja
            FROM {VISTA_GEO} g
            LEFT JOIN af ON af.codigo_ipress = g.codigo_ipress AND af.rn = 1
            LEFT JOIN at ON at.codigo_ipress = g.codigo_ipress
            LEFT JOIN cp ON cp.codigo_ipress = g.codigo_ipress
            WHERE 1 = 1
        )
        SELECT
            SUM(ISNULL(afiliados, 0))                                    AS total_afiliados,
            COUNT(CASE WHEN afiliados IS NOT NULL THEN 1 END)            AS ipress_con_afiliados,
            COUNT(*)                                                     AS ipress_territorio,
            SUM(ISNULL(total_atenciones, 0))                             AS total_atenciones,
            SUM(ISNULL(atenciones_emergencia, 0))                        AS atenciones_emergencia,
            ROUND(SUM(ISNULL(recursos_instalados, 0)), 2)                AS recursos_instalados,
            ROUND(SUM(ISNULL(recursos_operativos, 0)), 2)                AS recursos_operativos,
            ROUND(SUM(ISNULL(recursos_disponibles, 0)), 2)               AS recursos_disponibles,
            ROUND(SUM(ISNULL(recursos_ocupados, 0)), 2)                  AS recursos_ocupados,
            COUNT(CASE WHEN recursos_operativos IS NOT NULL THEN 1 END)  AS ipress_con_capacidad,
            ROUND(CAST(SUM(ISNULL(recursos_ocupados, 0)) AS FLOAT)
                 / NULLIF(SUM(ISNULL(recursos_operativos, 0)), 0) * 100.0, 2) AS tasa_ocupacion,
            SUM(ISNULL(dias_sobre_umbral, 0))                            AS dias_sobre_umbral,
            SUM(ISNULL(dias_alerta_roja, 0))                             AS dias_alerta_roja,
            SUM(ISNULL(uci_operativas, 0))                               AS uci_operativas,
            SUM(ISNULL(uci_ocupadas, 0))                                 AS uci_ocupadas,
            SUM(ISNULL(afiliados_rural, 0))                              AS afiliados_rural,
            ROUND(CAST(SUM(ISNULL(afiliados_rural, 0)) AS FLOAT)
                 / NULLIF(SUM(ISNULL(afiliados, 0)), 0) * 100.0, 2)      AS porc_rural,
            ROUND(CAST(SUM(ISNULL(total_atenciones, 0)) AS FLOAT)
                 / NULLIF(SUM(ISNULL(afiliados, 0)), 0) * 1000.0, 2)    AS presion_atencion,
            ROUND(CAST(SUM(ISNULL(afiliados, 0)) AS FLOAT)
                 / NULLIF(SUM(ISNULL(recursos_operativos, 0)), 0), 2)    AS ratio_afiliados_cama,
            ROUND(CAST(SUM(ISNULL(afiliados_0_4_pediatrico, 0)
                        + ISNULL(afiliados_60_mas_adulto_mayor, 0)
                        + ISNULL(afiliados_mujeres_edad_fertil, 0)) AS FLOAT)
                 / NULLIF(SUM(ISNULL(afiliados, 0)), 0) * 100.0, 2)      AS porc_vulnerable,
            ROUND((ISNULL(AVG(porc_vent_inoperativo), 0)
                 + ISNULL(AVG(porc_uci_inoperativo), 0)
                 + ISNULL(AVG(porc_hosp_inoperativo), 0)) / 3.0, 2)      AS tasa_inoperatividad
        FROM base g
        {_where(condiciones)}
        """
        return cls.consultar_uno(sql, params) or {}