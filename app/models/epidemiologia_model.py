"""Modelo epidemiologico: vigilancia de IRA y fallecidos por COVID-19.

Consume las dos dimensiones nuevas de la base:

  * dbo.dim_vigilancia_iras  - vigilancia semanal de IRA (265 963 filas,
    2021-2023, 25 departamentos): IRA no neumonia, neumonias, hospitalizaciones
    y defunciones por menor de 5 anos y por 60+, por departamento.
  * dbo.dim_fallecidos_covid - personas fallecidas por COVID-19 (124 000
    filas, 2021-2023): fecha de fallecimiento, edad, sexo, criterio de caso,
    banderas de hospitalizacion/UCI/vacuna y ubigeo de residencia.

Ambas fuentes traen su propia geografia (departamento/provincia/distrito con
nombres canonicos), por eso NO se unen con dim_ipress_ext: el filtro
territorial se aplica directo sobre sus columnas. La convencion del sistema
asimila region -> departamento, y el periodo reutiliza el objeto Filtros
(fecha_inicio/fecha_fin): en IRA sobre la fecha de la semana epidemiologica y
en COVID sobre la fecha de fallecimiento.
"""

from .base_model import BaseModel, normalizar_filas

FALLBACK_DPTO = "COALESCE(NULLIF(dep_domicilio, N''), NULLIF(dpt_cdc, N''), N'SIN REGISTRO')"


def _where(condiciones):
    return ("WHERE " + " AND ".join(condiciones)) if condiciones else ""


class EpidemiologiaModel(BaseModel):
    """Consultas de vigilancia epidemiologica (IRA y COVID-19)."""

    # ==================================================================
    # Vigilancia de IRA
    # ==================================================================
    @classmethod
    def _condiciones_ira(cls, filtros):
        """WHERE de dim_vigilancia_iras. `region` equivale a departamento."""
        condiciones = [
            "fecha_semana >= ?", "fecha_semana <= ?",
        ]
        params = [filtros.fecha_inicio, filtros.fecha_fin]
        if filtros.region:
            condiciones.append("departamento = ?")
            params.append(filtros.region)
        return condiciones, params

    @classmethod
    def resumen_ira(cls, filtros):
        """Panorama del periodo por semana epidemiologica."""
        condiciones, params = cls._condiciones_ira(filtros)
        sql = f"""
            SELECT COUNT(*) AS semanas_reportadas,
                   COUNT(DISTINCT ano) AS anios_cubiertos,
                   ISNULL(SUM(total_ira_no_neumonia), 0) AS ira_no_neumonia,
                   ISNULL(SUM(total_neumonias_men5), 0)  AS neumonias_men5,
                   ISNULL(SUM(total_neumonias_60mas), 0) AS neumonias_60mas,
                   ISNULL(SUM(total_neumonias_men5) + SUM(total_neumonias_60mas), 0)
                       AS neumonias,
                   ISNULL(SUM(total_hosp_men5) + SUM(total_hosp_60mas), 0)
                       AS hospitalizaciones,
                   ISNULL(SUM(total_def_men5) + SUM(total_def_60mas), 0)
                       AS defunciones
            FROM dbo.dim_vigilancia_iras
            {_where(condiciones)}
        """
        return cls.consultar_uno(sql, params) or {}

    @classmethod
    def serie_ira_mensual(cls, filtros):
        """Series mensuales: neumonias, hospitalizaciones y defunciones."""
        condiciones, params = cls._condiciones_ira(filtros)
        sql = f"""
            SELECT CONVERT(CHAR(7), fecha_semana, 126) AS periodo,
                   ISNULL(SUM(total_neumonias_men5) + SUM(total_neumonias_60mas), 0)
                       AS neumonias,
                   ISNULL(SUM(total_hosp_men5) + SUM(total_hosp_60mas), 0)
                       AS hospitalizaciones,
                   ISNULL(SUM(total_def_men5) + SUM(total_def_60mas), 0)
                       AS defunciones
            FROM dbo.dim_vigilancia_iras
            {_where(condiciones)}
            GROUP BY CONVERT(CHAR(7), fecha_semana, 126)
            ORDER BY periodo
        """
        return normalizar_filas(cls.consultar(sql, params))

    @classmethod
    def comparativo_ira_anual(cls, filtros):
        """Totales por ano para comparar la evolucion interanual.

        Se agrupa por YEAR(fecha_semana) y no por la columna `ano`: una
        semana 53 reportada en enero clasificaria en el ano anterior y
        dejaria filas en cero dentro del periodo filtrado (ademas, con el
        GROUP BY YEAR la pantalla solo muestra anos con semanas del periodo).
        """
        condiciones, params = cls._condiciones_ira(filtros)
        sql = f"""
            SELECT YEAR(fecha_semana) AS ano,
                   ISNULL(SUM(total_ira_no_neumonia), 0) AS ira_no_neumonia,
                   ISNULL(SUM(total_neumonias_men5) + SUM(total_neumonias_60mas), 0)
                       AS neumonias,
                   ISNULL(SUM(total_hosp_men5) + SUM(total_hosp_60mas), 0)
                       AS hospitalizaciones,
                   ISNULL(SUM(total_def_men5) + SUM(total_def_60mas), 0)
                       AS defunciones
            FROM dbo.dim_vigilancia_iras
            {_where(condiciones)}
            GROUP BY YEAR(fecha_semana)
            ORDER BY ano
        """
        return normalizar_filas(cls.consultar(sql, params))

    @classmethod
    def ira_por_departamento(cls, filtros, limite=25):
        """Detalle por departamento, ordenado por carga de neumonias."""
        condiciones, params = cls._condiciones_ira(filtros)
        sql = f"""
            SELECT TOP (?) departamento,
                   COUNT(DISTINCT fecha_semana) AS semanas,
                   ISNULL(SUM(total_ira_no_neumonia), 0) AS ira_no_neumonia,
                   ISNULL(SUM(total_neumonias_men5) + SUM(total_neumonias_60mas), 0)
                       AS neumonias,
                   ISNULL(SUM(total_neumonias_men5), 0)  AS neumonias_men5,
                   ISNULL(SUM(total_neumonias_60mas), 0) AS neumonias_60mas,
                   ISNULL(SUM(total_hosp_men5) + SUM(total_hosp_60mas), 0)
                       AS hospitalizaciones,
                   ISNULL(SUM(total_def_men5) + SUM(total_def_60mas), 0)
                       AS defunciones,
                   ROUND(CAST(ISNULL(SUM(total_def_men5) + SUM(total_def_60mas), 0)
                       AS FLOAT) / NULLIF(ISNULL(SUM(total_neumonias_men5)
                           + SUM(total_neumonias_60mas), 0), 0) * 100.0, 2)
                       AS letalidad_neumonia
            FROM dbo.dim_vigilancia_iras
            {_where(condiciones)}
            GROUP BY departamento
            ORDER BY neumonias DESC, departamento
        """
        return normalizar_filas(cls.consultar(sql, [limite] + params))

    # ==================================================================
    # Fallecidos por COVID-19
    # ==================================================================
    @classmethod
    def _condiciones_covid(cls, filtros):
        """WHERE de dim_fallecidos_covid. `region` sobre domicilio (con
        respaldo del campo CDC cuando el domicilio no esta reportado)."""
        condiciones = [
            "fecha_fallecimiento >= ?", "fecha_fallecimiento <= ?",
        ]
        params = [filtros.fecha_inicio, filtros.fecha_fin]
        if filtros.region:
            condiciones.append(f"{FALLBACK_DPTO} = ?")
            params.append(filtros.region)
        return condiciones, params

    @classmethod
    def resumen_covid(cls, filtros):
        """Panorama del periodo: totales y banderas de severidad."""
        condiciones, params = cls._condiciones_covid(filtros)
        sql = f"""
            SELECT COUNT(*) AS fallecidos,
                   CAST(AVG(CAST(edad AS FLOAT)) AS DECIMAL(5,1)) AS edad_promedio,
                   MAX(edad) AS edad_maxima,
                   ISNULL(SUM(CASE WHEN flag_vacuna = 1 THEN 1 ELSE 0 END), 0)
                       AS vacunados,
                   ISNULL(SUM(CASE WHEN flag_hospitalizado = 1 THEN 1 ELSE 0 END), 0)
                       AS hospitalizados,
                   ISNULL(SUM(CASE WHEN flag_uci = 1 THEN 1 ELSE 0 END), 0)
                       AS en_uci,
                   ISNULL(SUM(CASE WHEN sexo = N'M' THEN 1 ELSE 0 END), 0)
                       AS hombres,
                   ISNULL(SUM(CASE WHEN sexo = N'F' THEN 1 ELSE 0 END), 0)
                       AS mujeres
            FROM dbo.dim_fallecidos_covid
            {_where(condiciones)}
        """
        return cls.consultar_uno(sql, params) or {}

    @classmethod
    def serie_covid_mensual(cls, filtros):
        """Serie mensual de fallecidos (con desglose de vacunados)."""
        condiciones, params = cls._condiciones_covid(filtros)
        sql = f"""
            SELECT CONVERT(CHAR(7), fecha_fallecimiento, 126) AS periodo,
                   COUNT(*) AS fallecidos,
                   SUM(CASE WHEN flag_vacuna = 1 THEN 1 ELSE 0 END) AS vacunados,
                   SUM(CASE WHEN flag_vacuna IS NULL OR flag_vacuna = 0 THEN 1 ELSE 0 END)
                       AS no_vacunados
            FROM dbo.dim_fallecidos_covid
            {_where(condiciones)}
            GROUP BY CONVERT(CHAR(7), fecha_fallecimiento, 126)
            ORDER BY periodo
        """
        return normalizar_filas(cls.consultar(sql, params))

    @classmethod
    def covid_por_departamento(cls, filtros, limite=25):
        """Detalle por departamento de residencia del fallecido."""
        condiciones, params = cls._condiciones_covid(filtros)
        sql = f"""
            SELECT TOP (?) {FALLBACK_DPTO} AS departamento,
                   COUNT(*) AS fallecidos,
                   SUM(CASE WHEN flag_vacuna = 1 THEN 1 ELSE 0 END) AS vacunados,
                   ROUND(SUM(CASE WHEN flag_vacuna = 1 THEN 1.0 ELSE 0 END)
                       / COUNT(*) * 100.0, 1) AS porc_vacunados,
                   SUM(CASE WHEN flag_hospitalizado = 1 THEN 1.0 ELSE 0 END)
                       / COUNT(*) * 100.0 AS porc_hospitalizados,
                   SUM(CASE WHEN flag_uci = 1 THEN 1.0 ELSE 0 END)
                       / COUNT(*) * 100.0 AS porc_uci,
                   CAST(AVG(CAST(edad AS FLOAT)) AS DECIMAL(5,1)) AS edad_promedio
            FROM dbo.dim_fallecidos_covid
            {_where(condiciones)}
            GROUP BY {FALLBACK_DPTO}
            ORDER BY fallecidos DESC, departamento
        """
        return normalizar_filas(cls.consultar(sql, [limite] + params))

    @classmethod
    def covid_por_criterio(cls, filtros):
        """Distribucion por criterio de defuncion (virologico, SINADEF...)."""
        condiciones, params = cls._condiciones_covid(filtros)
        sql = f"""
            SELECT ISNULL(NULLIF(criterio_fallecido, N''), N'NO REPORTADO') AS criterio,
                   COUNT(*) AS casos
            FROM dbo.dim_fallecidos_covid
            {_where(condiciones)}
            GROUP BY ISNULL(NULLIF(criterio_fallecido, N''), N'NO REPORTADO')
            ORDER BY casos DESC
        """
        filas = normalizar_filas(cls.consultar(sql, params))
        total = sum(f["casos"] for f in filas) or 1
        for fila in filas:
            fila["porc"] = round(fila["casos"] / total * 100.0, 1)
        return filas

    @classmethod
    def covid_por_sexo_edad(cls, filtros):
        """Distribucion por sexo y grupos de edad (para el grafico de barras)."""
        condiciones, params = cls._condiciones_covid(filtros)
        sql = f"""
            SELECT CASE
                       WHEN edad IS NULL THEN N'SIN EDAD'
                       WHEN edad < 20 THEN N'0-19'
                       WHEN edad < 40 THEN N'20-39'
                       WHEN edad < 60 THEN N'40-59'
                       WHEN edad < 80 THEN N'60-79'
                       ELSE N'80+'
                   END AS grupo_edad,
                   sexo,
                   COUNT(*) AS casos
            FROM dbo.dim_fallecidos_covid
            {_where(condiciones)}
            GROUP BY CASE
                       WHEN edad IS NULL THEN N'SIN EDAD'
                       WHEN edad < 20 THEN N'0-19'
                       WHEN edad < 40 THEN N'20-39'
                       WHEN edad < 60 THEN N'40-59'
                       WHEN edad < 80 THEN N'60-79'
                       ELSE N'80+'
                   END,
                   sexo
        """
        filas = normalizar_filas(cls.consultar(sql, params))
        filas.sort(key=lambda f: f["grupo_edad"], reverse=True)
        return filas

    @classmethod
    def covid_comparativo_anual(cls, filtros):
        """Totales por ano para comparar la evolucion interanual."""
        condiciones, params = cls._condiciones_covid(filtros)
        sql = f"""
            SELECT YEAR(fecha_fallecimiento) AS ano,
                   COUNT(*) AS fallecidos,
                   SUM(CASE WHEN flag_uci = 1 THEN 1 ELSE 0 END) AS en_uci,
                   ROUND(SUM(CASE WHEN flag_vacuna = 1 THEN 1.0 ELSE 0 END)
                       / COUNT(*) * 100.0, 1) AS porc_vacunados
            FROM dbo.dim_fallecidos_covid
            {_where(condiciones)}
            GROUP BY YEAR(fecha_fallecimiento)
            ORDER BY ano
        """
        return normalizar_filas(cls.consultar(sql, params))
