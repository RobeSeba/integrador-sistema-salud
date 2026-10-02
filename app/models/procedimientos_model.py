"""Modelo de procedimientos almacenados.

Envuelve los tres procedimientos existentes en SaludBrechasDB:

  * dbo.usp_Salud_PresionAfiliados
  * dbo.usp_Salud_UtilizacionCamas
  * dbo.usp_Salud_InoperatividadRecursos

Cada procedimiento devuelve varios conjuntos de resultados; este modelo los
normaliza a listas de diccionarios para que las vistas los pinten y el
exportador los convierta a CSV/XLSX.
"""

from .base_model import BaseModel, normalizar_filas

PROCEDIMIENTOS = {
    "presion_afiliados": {
        "nombre": "usp_Salud_PresionAfiliados",
        "titulo": "Presion de afiliados",
        "descripcion": (
            "Compara la poblacion afiliada con las atenciones registradas. "
            "Devuelve totales del periodo y la serie por fecha de corte."
        ),
        "parametros": ["FechaInicio", "FechaFin", "CodigoIpress", "Region"],
    },
    "utilizacion_camas": {
        "nombre": "usp_Salud_UtilizacionCamas",
        "titulo": "Utilizacion de camas",
        "descripcion": (
            "Calcula el uso de camas del periodo y lista los dias en que la "
            "ocupacion alcanzo o supero el umbral definido."
        ),
        "parametros": ["FechaInicio", "FechaFin", "CodigoIpress", "Region", "UmbralOcupacion"],
    },
    "inoperatividad_recursos": {
        "nombre": "usp_Salud_InoperatividadRecursos",
        "titulo": "Inoperatividad de recursos",
        "descripcion": (
            "Resume los recursos inoperativos (ventiladores, UCI, hospitalizacion) "
            "del periodo y su porcentaje sobre el total operativo."
        ),
        "parametros": ["FechaInicio", "FechaFin", "CodigoIpress", "Region"],
    },
}


class ProcedimientosModel(BaseModel):
    """Ejecucion segura de los procedimientos almacenados."""

    SQL = {
        "presion_afiliados": "{CALL dbo.usp_Salud_PresionAfiliados (?, ?, ?, ?)}",
        "utilizacion_camas": "{CALL dbo.usp_Salud_UtilizacionCamas (?, ?, ?, ?, ?)}",
        "inoperatividad_recursos": "{CALL dbo.usp_Salud_InoperatividadRecursos (?, ?, ?, ?)}",
    }

    @classmethod
    def catalogo(cls):
        return [
            {
                "clave": clave,
                "nombre": meta["nombre"],
                "titulo": meta["titulo"],
                "descripcion": meta["descripcion"],
                "parametros": meta["parametros"],
            }
            for clave, meta in PROCEDIMIENTOS.items()
        ]

    @classmethod
    def ejecutar(cls, clave, filtros):
        """Ejecuta un procedimiento y devuelve sus conjuntos de resultados.

        `filtros` es un objeto Filtros ya validado por la capa de entrada.
        Devuelve {"titulo", "nombre", "consulta_sql", "resultados": [
            {"nombre": ..., "columnas": [...], "filas": [...]}, ...
        ]}
        """
        if clave not in cls.SQL:
            raise ValueError(f"Procedimiento desconocido: {clave}")

        codigo_ipress = filtros.codigo_ipress
        region = filtros.region

        if clave == "utilizacion_camas":
            params = [
                filtros.fecha_inicio, filtros.fecha_fin,
                codigo_ipress, region, float(filtros.umbral_ocupacion),
            ]
        else:
            params = [filtros.fecha_inicio, filtros.fecha_fin, codigo_ipress, region]

        # No se usa str.format: las llamadas a procedimiento llevan la sintaxis
        # de escape de ODBC {CALL ...}, que `format` interpretaria como un
        # marcador de campo y fallaria con KeyError('CALL dbo').
        consulta = cls.SQL[clave]
        crudos = cls.conjuntos_multiples(consulta, params)

        nombres = {
            "presion_afiliados": ["Totales del periodo", "Serie por fecha de corte"],
            "utilizacion_camas": ["Resumen del periodo", "Dias sobre el umbral de ocupacion"],
            "inoperatividad_recursos": ["Resumen de inoperatividad"],
        }[clave]

        resultados = []
        for indice, (columnas, filas) in enumerate(crudos):
            filas_norm = [tuple(fila) for fila in filas]
            resultados.append({
                "nombre": nombres[indice] if indice < len(nombres) else f"Resultado {indice + 1}",
                "columnas": columnas,
                "filas": filas_norm,
                "total_filas": len(filas_norm),
            })

        meta = PROCEDIMIENTOS[clave]
        return {
            "clave": clave,
            "nombre": meta["nombre"],
            "titulo": meta["titulo"],
            "descripcion": meta["descripcion"],
            "consulta_sql": consulta,
            "parametros": {
                "FechaInicio": filtros.fecha_inicio,
                "FechaFin": filtros.fecha_fin,
                "CodigoIpress": codigo_ipress,
                "Region": region,
                "UmbralOcupacion": (
                    filtros.umbral_ocupacion if clave == "utilizacion_camas" else None
                ),
            },
            "resultados": resultados,
            "etiqueta_filtros": filtros.etiqueta_territorio(),
        }

    # ------------------------------------------------------------------
    # Consultas de apoyo para las pantallas de alertas y criticos
    # ------------------------------------------------------------------
    @classmethod
    def ocupacion_critica(cls, filtros, limite=500):
        """Establecimientos con ocupacion sobre el umbral (historia criticos)."""
        condiciones, params = filtros.where_tiempo("c")
        cond_geo, params_geo = filtros.where_geo("g")
        sql = f"""
            SELECT TOP (?) c.fecha_corte, c.codigo_ipress, g.nombre_establecimiento,
                   g.region, g.provincia, g.distrito, g.categoria, g.nivel,
                   c.total_camas_operativas, c.total_camas_ocupadas,
                   c.total_camas_disponibles, c.tasa_ocupacion_global,
                   c.uci_operativas, c.uci_ocupadas, c.tasa_ocupacion_uci,
                   c.hosp_operativas, c.hosp_ocupadas, c.tasa_ocupacion_hosp,
                   c.vent_operativos, c.vent_en_uso, c.vent_inoperativos,
                   c.nivel_alerta
            FROM dbo.fact_capacidad_diaria c
            INNER JOIN dbo.dim_ipress_ext g ON g.codigo_ipress = c.codigo_ipress
            WHERE c.tasa_ocupacion_global >= ?
            {"AND " + " AND ".join(condiciones + cond_geo) if condiciones or cond_geo else ""}
            ORDER BY c.tasa_ocupacion_global DESC, c.fecha_corte DESC
        """
        params = [limite, filtros.umbral_ocupacion] + params + params_geo
        return normalizar_filas(cls.consultar(sql, params))

    @classmethod
    def inoperatividad_critica(cls, filtros, limite=500):
        """Establecimientos con recursos clave inoperativos en el ultimo dia."""
        condiciones, params = filtros.where_tiempo("c")
        cond_geo, params_geo = filtros.where_geo("g")
        todo = condiciones + cond_geo
        if not todo:
            todo = ["c.fecha_corte = (SELECT MAX(fecha_corte) FROM dbo.fact_capacidad_diaria)"]
        sql = f"""
            SELECT TOP (?) c.fecha_corte, c.codigo_ipress, g.nombre_establecimiento,
                   g.region, g.provincia, g.distrito, g.categoria, g.nivel,
                   c.vent_total, c.vent_operativos, c.vent_inoperativos, c.tasa_uso_ventiladores,
                   c.uci_total, c.uci_operativas, c.uci_inoperativas, c.tasa_ocupacion_uci,
                   c.hosp_total, c.hosp_operativas, c.hosp_inoperativas, c.tasa_ocupacion_hosp,
                   c.emer_total, c.emer_operativas,
                   c.monito_total, c.monito_operativos,
                   c.total_camas, c.total_camas_operativas, c.total_camas_ocupadas,
                   c.tasa_ocupacion_global, c.nivel_alerta
            FROM dbo.fact_capacidad_diaria c
            INNER JOIN dbo.dim_ipress_ext g ON g.codigo_ipress = c.codigo_ipress
            WHERE (c.vent_inoperativos > 0 OR c.uci_inoperativas > 0
                   OR c.hosp_inoperativas > 0 OR c.tasa_ocupacion_global >= ?)
            {"AND " + " AND ".join(todo) if todo else ""}
            ORDER BY (ISNULL(c.vent_inoperativos, 0) + ISNULL(c.uci_inoperativas, 0)
                      + ISNULL(c.hosp_inoperativas, 0)) DESC,
                     c.tasa_ocupacion_global DESC
        """
        params = [limite, filtros.umbral_ocupacion] + params + params_geo
        return normalizar_filas(cls.consultar(sql, params))

    @classmethod
    def resumen_alertas(cls, filtros):
        """Panorama de alertas para la pantalla de monitoreo."""
        cond_fecha, params_fecha = filtros.where_tiempo("c")
        cond_geo, params_geo = filtros.where_geo("g")
        todo = cond_fecha + cond_geo
        where = ("WHERE " + " AND ".join(todo)) if todo else ""
        sql = f"""
            SELECT COUNT(DISTINCT c.codigo_ipress) AS establecimientos_reportando,
                   COUNT(DISTINCT c.fecha_corte)   AS dias_reporte,
                   SUM(CASE WHEN c.nivel_alerta = N'ROJO' THEN 1 ELSE 0 END)     AS dias_rojo,
                   SUM(CASE WHEN c.nivel_alerta = N'AMARILLO' THEN 1 ELSE 0 END) AS dias_amarillo,
                   SUM(CASE WHEN c.nivel_alerta = N'VERDE' THEN 1 ELSE 0 END)    AS dias_verde,
                   SUM(CASE WHEN c.tasa_ocupacion_global >= ? THEN 1 ELSE 0 END) AS registros_sobre_umbral,
                   SUM(ISNULL(c.vent_inoperativos, 0))   AS vent_inoperativos,
                   SUM(ISNULL(c.vent_operativos, 0))     AS vent_operativos,
                   SUM(ISNULL(c.uci_inoperativas, 0))     AS uci_inoperativas,
                   SUM(ISNULL(c.uci_operativas, 0))       AS uci_operativas,
                   SUM(ISNULL(c.hosp_inoperativas, 0))    AS hosp_inoperativas,
                   SUM(ISNULL(c.hosp_operativas, 0))      AS hosp_operativas,
                   ROUND(AVG(CAST(ISNULL(c.tasa_ocupacion_global, 0) AS FLOAT)), 2) AS ocupacion_promedio,
                   MAX(ISNULL(c.tasa_ocupacion_global, 0)) AS ocupacion_maxima,
                   MAX(c.fecha_corte) AS ultima_fecha
            FROM dbo.fact_capacidad_diaria c
            INNER JOIN dbo.dim_ipress_ext g ON g.codigo_ipress = c.codigo_ipress
            {where}
        """
        return cls.consultar_uno(sql, [filtros.umbral_ocupacion] + params_fecha + params_geo) or {}

    @classmethod
    def alertas_por_departamento(cls, filtros):
        """Distribucion de alertas por departamento en el periodo."""
        cond_fecha, params_fecha = filtros.where_tiempo("c")
        cond_geo, params_geo = filtros.where_geo("g")
        sql = f"""
            SELECT g.region AS departamento,
                   COUNT(DISTINCT c.codigo_ipress) AS establecimientos,
                   SUM(CASE WHEN c.nivel_alerta = N'ROJO' THEN 1 ELSE 0 END)     AS dias_rojo,
                   SUM(CASE WHEN c.nivel_alerta = N'AMARILLO' THEN 1 ELSE 0 END) AS dias_amarillo,
                   SUM(CASE WHEN c.nivel_alerta = N'VERDE' THEN 1 ELSE 0 END)    AS dias_verde,
                   SUM(CASE WHEN c.tasa_ocupacion_global >= ? THEN 1 ELSE 0 END) AS registros_sobre_umbral,
                   ROUND(AVG(CAST(ISNULL(c.tasa_ocupacion_global, 0) AS FLOAT)), 2) AS ocupacion_promedio,
                   ROUND(CAST(SUM(ISNULL(c.vent_inoperativos, 0)) AS FLOAT)
                       / NULLIF(SUM(ISNULL(c.vent_operativos, 0)), 0) * 100.0, 2) AS porc_vent_inoperativo
            FROM dbo.fact_capacidad_diaria c
            INNER JOIN dbo.dim_ipress_ext g ON g.codigo_ipress = c.codigo_ipress
            WHERE 1 = 1
            {"AND " + " AND ".join(cond_fecha + cond_geo) if cond_fecha or cond_geo else ""}
            GROUP BY g.region
            ORDER BY dias_rojo DESC, ocupacion_promedio DESC
        """
        return normalizar_filas(cls.consultar(sql, [filtros.umbral_ocupacion] + params_fecha + params_geo))