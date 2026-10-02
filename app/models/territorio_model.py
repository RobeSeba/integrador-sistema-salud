"""Modelo de territorio: catalogos jerarquicos y busqueda de establecimientos.

Cubre la historia: "Como analista sanitario, quiero consultar afiliados,
atenciones y capacidad por region, provincia, distrito y establecimiento".
"""

from .base_model import BaseModel, normalizar_filas

VISTA_GEO = "dbo.dim_ipress_ext"


class TerritorioModel(BaseModel):
    # ------------------------------------------------------------------
    # Catalogos para los desplegables de filtros
    # ------------------------------------------------------------------
    # dim_ipress_ext tiene exactamente una fila por codigo_ipress, por lo que
    # COUNT(*) agrupado equivale al conteo de establecimientos distintos.
    # `con_capacidad` permite separar los EESS con camas de los codigos que solo
    # reportan afiliacion o atenciones.
    @classmethod
    def regiones(cls, con_afiliados=False):
        extra = " AND tiene_afiliados = 1" if con_afiliados else ""
        sql = f"""
            SELECT region AS valor,
                   COUNT(*) AS establecimientos,
                   SUM(CASE WHEN tiene_capacidad = 1 THEN 1 ELSE 0 END) AS con_capacidad,
                   SUM(CASE WHEN en_dim_ipress = 1 THEN 1 ELSE 0 END)  AS catalogados
            FROM {VISTA_GEO}
            WHERE region IS NOT NULL AND LEN(TRIM(region)) > 0{extra}
            GROUP BY region
            ORDER BY region
        """
        return normalizar_filas(cls.consultar(sql))

    @classmethod
    def provincias(cls, region=None):
        sql = f"""
            SELECT provincia AS valor,
                   COUNT(*) AS establecimientos,
                   SUM(CASE WHEN tiene_capacidad = 1 THEN 1 ELSE 0 END) AS con_capacidad
            FROM {VISTA_GEO}
            WHERE provincia IS NOT NULL AND LEN(TRIM(provincia)) > 0
        """
        params = []
        if region:
            sql += " AND region = ?"
            params.append(region)
        sql += " GROUP BY provincia ORDER BY provincia"
        return normalizar_filas(cls.consultar(sql, params))

    @classmethod
    def distritos(cls, region=None, provincia=None):
        sql = f"""
            SELECT distrito AS valor,
                   COUNT(*) AS establecimientos,
                   SUM(CASE WHEN tiene_capacidad = 1 THEN 1 ELSE 0 END) AS con_capacidad
            FROM {VISTA_GEO}
            WHERE distrito IS NOT NULL AND LEN(TRIM(distrito)) > 0
        """
        params = []
        if region:
            sql += " AND region = ?"
            params.append(region)
        if provincia:
            sql += " AND provincia = ?"
            params.append(provincia)
        sql += " GROUP BY distrito ORDER BY distrito"
        return normalizar_filas(cls.consultar(sql, params))

    @classmethod
    def categorias(cls):
        sql = f"""
            SELECT categoria AS valor, COUNT(*) AS establecimientos, SUM(CASE WHEN tiene_capacidad = 1 THEN 1 ELSE 0 END) AS con_capacidad
            FROM {VISTA_GEO}
            WHERE categoria IS NOT NULL AND LEN(TRIM(categoria)) > 0
            GROUP BY categoria
            ORDER BY categoria
        """
        return normalizar_filas(cls.consultar(sql))

    @classmethod
    def niveles(cls):
        sql = f"""
            SELECT nivel AS valor, COUNT(*) AS establecimientos, SUM(CASE WHEN tiene_capacidad = 1 THEN 1 ELSE 0 END) AS con_capacidad
            FROM {VISTA_GEO}
            WHERE nivel IS NOT NULL AND LEN(TRIM(nivel)) > 0
            GROUP BY nivel
            ORDER BY nivel
        """
        return normalizar_filas(cls.consultar(sql))

    @classmethod
    def instituciones(cls):
        sql = f"""
            SELECT institucion AS valor, COUNT(*) AS establecimientos, SUM(CASE WHEN tiene_capacidad = 1 THEN 1 ELSE 0 END) AS con_capacidad
            FROM {VISTA_GEO}
            WHERE institucion IS NOT NULL AND LEN(TRIM(institucion)) > 0
            GROUP BY institucion
            ORDER BY institucion
        """
        return normalizar_filas(cls.consultar(sql))

    @classmethod
    def macroregiones(cls):
        sql = f"""
            SELECT macroregion AS valor, COUNT(*) AS establecimientos, SUM(CASE WHEN tiene_capacidad = 1 THEN 1 ELSE 0 END) AS con_capacidad
            FROM {VISTA_GEO}
            WHERE macroregion IS NOT NULL AND LEN(TRIM(macroregion)) > 0
            GROUP BY macroregion
            ORDER BY macroregion
        """
        return normalizar_filas(cls.consultar(sql))

    @classmethod
    def niveles_eess(cls):
        sql = """
            SELECT nivel_eess AS valor, COUNT(*) AS registros
            FROM dbo.fact_atenciones
            WHERE nivel_eess IS NOT NULL AND LEN(TRIM(nivel_eess)) > 0
            GROUP BY nivel_eess
            ORDER BY nivel_eess
        """
        return normalizar_filas(cls.consultar(sql))

    @classmethod
    def catalogo_completo(cls):
        """Un solo viaje a la base de datos para todos los desplegables."""
        return {
            "regiones": cls.regiones(),
            "provincias": cls.provincias(),
            "distritos": cls.distritos(),
            "categorias": cls.categorias(),
            "niveles": cls.niveles(),
            "instituciones": cls.instituciones(),
            "macroregiones": cls.macroregiones(),
            "niveles_eess": cls.niveles_eess(),
        }

    # ------------------------------------------------------------------
    # Busqueda de establecimientos
    # ------------------------------------------------------------------
    @classmethod
    def buscar_establecimientos(cls, texto=None, region=None, limite=50):
        """Busqueda incremental para el selector de IPRESS."""
        sql = f"""
            SELECT TOP (?) codigo_ipress, nombre_establecimiento, categoria, nivel,
                   institucion, region, provincia, distrito, ubigeo, en_dim_ipress
            FROM {VISTA_GEO}
            WHERE 1 = 1
        """
        params = [limite]
        if texto:
            sql += """
                AND (
                    CONVERT(NVARCHAR(20), codigo_ipress) LIKE ?
                    OR nombre_establecimiento LIKE ?
                    OR ubigeo LIKE ?
                )
            """
            like = f"%{texto}%"
            params.extend([like, like, like])
        if region:
            sql += " AND region = ?"
            params.append(region)
        sql += " ORDER BY nombre_establecimiento"
        return normalizar_filas(cls.consultar(sql, params))

    @classmethod
    def obtener_establecimiento(cls, codigo_ipress):
        sql = f"""
            SELECT * FROM {VISTA_GEO} WHERE codigo_ipress = ?
        """
        return cls.consultar_uno(sql, [codigo_ipress])

    # ------------------------------------------------------------------
    # Cobertura geografica de los datos
    # ------------------------------------------------------------------
    @classmethod
    def refrescar_dim_ipress_ext(cls):
        """Regenera la dimension extendida (tras una carga de archivos)."""
        return cls.consultar_uno(
            "{CALL dbo.usp_SIBS_RefrescarDimIpressExt()}", commit=True
        )

    @classmethod
    def estadisticas_dim_ext(cls):
        sql = """
            SELECT COUNT(*) AS total,
                   SUM(CASE WHEN en_dim_ipress = 1 THEN 1 ELSE 0 END) AS catalogados,
                   SUM(CASE WHEN tiene_capacidad = 1 THEN 1 ELSE 0 END) AS con_capacidad,
                   SUM(CASE WHEN tiene_afiliados = 1 THEN 1 ELSE 0 END) AS con_afiliados,
                   SUM(CASE WHEN tiene_atenciones = 1 THEN 1 ELSE 0 END) AS con_atenciones,
                   SUM(CASE WHEN region IS NULL THEN 1 ELSE 0 END)     AS sin_region,
                   MAX(fecha_actualizacion) AS fecha_actualizacion
            FROM dbo.dim_ipress_ext
        """
        return cls.consultar_uno(sql) or {}

    @classmethod
    def alias_territorio(cls):
        """Alias configurados manualmente para regiones (mapa de sinonimos)."""
        return normalizar_filas(cls.consultar(
            "SELECT nivel, nombre_original, nombre_canonico "
            "FROM dbo.sys_territorios_alias ORDER BY nivel, nombre_original"
        ))

    @classmethod
    def agregar_alias(cls, nivel, nombre_original, nombre_canonico):
        """Registra o actualiza un alias territorial.

        Ambos nombres se guardan ya normalizados (sin tildes, en mayusculas)
        porque dbo.fn_canonico_territorio busca por la clave normalizada.
        La normalizacion se hace con la misma funcion del servidor para que
        Python y T-SQL no se desincronicen.
        """
        nivel = str(nivel or "").strip().upper()
        if nivel not in ("REGION", "PROVINCIA", "DISTRITO"):
            raise ValueError("El nivel debe ser REGION, PROVINCIA o DISTRITO.")

        original = cls._normalizar(nombre_original)
        if not original:
            raise ValueError("El nombre original es obligatorio.")
        canonico = cls._normalizar(nombre_canonico)
        if not canonico:
            raise ValueError("El nombre canónico es obligatorio.")

        existe = cls.consultar_uno(
            "SELECT 1 AS x FROM dbo.sys_territorios_alias "
            "WHERE nivel = ? AND nombre_original = ?",
            [nivel, original],
        )
        if existe:
            cls.ejecutar(
                "UPDATE dbo.sys_territorios_alias SET nombre_canonico = ? "
                "WHERE nivel = ? AND nombre_original = ?",
                [canonico, nivel, original],
            )
        else:
            cls.ejecutar(
                "INSERT INTO dbo.sys_territorios_alias (nivel, nombre_original, nombre_canonico) "
                "VALUES (?, ?, ?)",
                [nivel, original, canonico],
            )

    @classmethod
    def _normalizar(cls, texto):
        """Invoca dbo.fn_normaliza_texto; devuelve '' si el texto es vacío."""
        limpio = str(texto or "").strip()
        if not limpio:
            return ""
        return cls.consultar_valor(
            "SELECT dbo.fn_normaliza_texto(?)", [limpio], default=""
        ) or ""

    @classmethod
    def cobertura(cls):
        """Resumen de cobertura de datos por entidad de la estrella."""
        # dim_ipress no tiene columna de fecha, por eso se castea el NULL a
        # DATE: MIN(NULL) sin tipo es un error en SQL Server.
        sql = """
            SELECT 'dim_ipress' AS entidad, COUNT(*) AS registros,
                   COUNT(DISTINCT codigo_ipress) AS entidades,
                   CAST(NULL AS DATE) AS fecha_min, CAST(NULL AS DATE) AS fecha_max
            FROM dbo.dim_ipress
            UNION ALL
            SELECT 'fact_afiliados_sis', COUNT(*), COUNT(DISTINCT codigo_ipress),
                   MIN(fecha_corte), MAX(fecha_corte) FROM dbo.fact_afiliados_sis
            UNION ALL
            SELECT 'fact_atenciones', COUNT(*), COUNT(DISTINCT codigo_ipress),
                   MIN(fecha_corte), MAX(fecha_corte) FROM dbo.fact_atenciones
            UNION ALL
            SELECT 'fact_capacidad_diaria', COUNT(*), COUNT(DISTINCT codigo_ipress),
                   MIN(fecha_corte), MAX(fecha_corte) FROM dbo.fact_capacidad_diaria
            ORDER BY entidad
        """
        return normalizar_filas(cls.consultar(sql))