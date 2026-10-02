/* ============================================================================
   SIBS - Migracion 003: procedimiento de refresco de la dimension extendida

   dbo.dim_ipress_ext materializa la geografia unificada de los tres hechos.
   Se refresca despues de cada carga de archivos para recoger codigos de IPRESS
   nuevos y reclasificaciones territoriales.
   ============================================================================ */

SET NOCOUNT ON;
GO

IF OBJECT_ID('dbo.usp_SIBS_RefrescarDimIpressExt', 'P') IS NOT NULL
    DROP PROCEDURE dbo.usp_SIBS_RefrescarDimIpressExt;
GO

CREATE PROCEDURE dbo.usp_SIBS_RefrescarDimIpressExt
AS
BEGIN
    SET NOCOUNT ON;
    BEGIN TRY
        TRUNCATE TABLE dbo.dim_ipress_ext;

        WITH codigos AS (
            SELECT codigo_ipress FROM dbo.dim_ipress
            UNION
            SELECT codigo_ipress FROM dbo.fact_afiliados_sis
            UNION
            SELECT codigo_ipress FROM dbo.fact_atenciones
        ),
        geo_af AS (
            SELECT codigo_ipress, ubigeo, region, provincia, distrito,
                   ROW_NUMBER() OVER (PARTITION BY codigo_ipress ORDER BY fecha_corte DESC) AS rn
            FROM dbo.fact_afiliados_sis
        ),
        geo_at AS (
            SELECT codigo_ipress, ubigeo, region, provincia, distrito,
                   ROW_NUMBER() OVER (PARTITION BY codigo_ipress ORDER BY fecha_corte DESC) AS rn
            FROM dbo.fact_atenciones
        )
        INSERT INTO dbo.dim_ipress_ext (
            codigo_ipress, nombre_establecimiento, nombre, categoria, nivel,
            institucion, grupo, sub_grupo, macroregion, cuenta_triaje, cuenta_zc,
            ubigeo, ubigeo_region, ubigeo_provincia, region, provincia, distrito,
            region_fuente, en_dim_ipress
        )
        SELECT c.codigo_ipress,
               ISNULL(d.nombre_establecimiento, CONCAT(N'IPRESS ', c.codigo_ipress)),
               ISNULL(d.nombre_establecimiento, CONCAT(N'IPRESS ', c.codigo_ipress)),
               ISNULL(d.categoria, 'SIN CATEGORIA'),
               ISNULL(d.nivel, 'Sin Categoria'),
               d.institucion, d.grupo, d.sub_grupo, d.macroregion,
               d.cuenta_triaje, d.cuenta_zc,
               ubi.ubigeo,
               CASE WHEN LEN(ubi.ubigeo) >= 2 THEN LEFT(ubi.ubigeo, 2) END,
               CASE WHEN LEN(ubi.ubigeo) >= 4 THEN LEFT(ubi.ubigeo, 4) END,
               dbo.fn_canonico_territorio(N'REGION',    reg.region),
               dbo.fn_canonico_territorio(N'PROVINCIA', pro.provincia),
               dbo.fn_canonico_territorio(N'DISTRITO',  dis.distrito),
               CASE WHEN d.codigo_ipress IS NOT NULL THEN N'DIM_IPRESS'
                    WHEN af.codigo_ipress IS NOT NULL THEN N'FACT_AFILIADOS'
                    ELSE N'FACT_ATENCIONES' END,
               CASE WHEN d.codigo_ipress IS NULL THEN 0 ELSE 1 END
        FROM codigos c
        LEFT JOIN dbo.dim_ipress d
               ON d.codigo_ipress = c.codigo_ipress
        LEFT JOIN geo_af af ON af.codigo_ipress = c.codigo_ipress AND af.rn = 1
        LEFT JOIN geo_at at1 ON at1.codigo_ipress = c.codigo_ipress AND at1.rn = 1
        CROSS APPLY (SELECT COALESCE(NULLIF(TRIM(d.ubigeo), ''), NULLIF(TRIM(af.ubigeo), ''),
                                    NULLIF(TRIM(at1.ubigeo), '')) AS ubigeo) ubi
        CROSS APPLY (SELECT COALESCE(d.region, af.region, at1.region) AS region) reg
        CROSS APPLY (SELECT COALESCE(d.provincia, af.provincia, at1.provincia) AS provincia) pro
        CROSS APPLY (SELECT COALESCE(d.distrito, af.distrito, at1.distrito) AS distrito) dis;

        UPDATE e SET tiene_afiliados = 1
        FROM dbo.dim_ipress_ext e
        WHERE EXISTS (SELECT 1 FROM dbo.fact_afiliados_sis f
                       WHERE f.codigo_ipress = e.codigo_ipress);

        UPDATE e SET tiene_atenciones = 1
        FROM dbo.dim_ipress_ext e
        WHERE EXISTS (SELECT 1 FROM dbo.fact_atenciones f
                       WHERE f.codigo_ipress = e.codigo_ipress);

        UPDATE e SET tiene_capacidad = 1
        FROM dbo.dim_ipress_ext e
        WHERE EXISTS (SELECT 1 FROM dbo.fact_capacidad_diaria f
                       WHERE f.codigo_ipress = e.codigo_ipress);

        SELECT COUNT(*) AS registros FROM dbo.dim_ipress_ext;
    END TRY
    BEGIN CATCH
        DECLARE @msg NVARCHAR(4000) = ERROR_MESSAGE();
        RAISERROR('usp_SIBS_RefrescarDimIpressExt error: %s', 16, 1, @msg);
    END CATCH
END
GO

PRINT 'Migracion 003 completada.';
GO