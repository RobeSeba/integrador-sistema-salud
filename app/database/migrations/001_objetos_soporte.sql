/* ============================================================================
   SIBS - Sistema de Informacion para la Identificacion y Priorizacion de
   Brechas de Capacidad Sanitaria en Establecimientos de Salud del Peru

   Migracion 001: normalizacion territorial, dimension extendida de IPRESS y
   objetos de soporte del sistema (todas idempotentes).
   ============================================================================ */

SET NOCOUNT ON;
GO

/* ---------------------------------------------------------------------------
   1. Funciones de normalizacion territorial

   Los catalogos y los hechos usan convenciones distintas para los mismos
   territorios:

     dim_ipress      -> nombres oficiales sin tilde:  ANCASH, APURIMAC, LIMA
     fact_afiliados  -> nombres acentuados:           ÁNCASH, APURÍMAC
     fact_atenciones -> division sanitaria de Lima:   LIMA METROPOLITANA,
                                                     LIMA REGION, LIMA PROVINCIAS

   Sin normalizar, un filtro por region devuelve un solo hecho y deja el resto
   fuera. `fn_normaliza_texto` quita tildes, pasa a mayusculas y colapsa
   espacios; `fn_canonico_territorio` aplica ademas un mapa de sinonimos para
   unificar las variantes de Lima en el unico departamento "LIMA".
   --------------------------------------------------------------------------- */
IF OBJECT_ID('dbo.fn_normaliza_texto', 'FN') IS NOT NULL DROP FUNCTION dbo.fn_normaliza_texto;
GO

CREATE FUNCTION dbo.fn_normaliza_texto(@texto NVARCHAR(200))
RETURNS NVARCHAR(200)
AS
BEGIN
    DECLARE @r NVARCHAR(200) = UPPER(LTRIM(RTRIM(ISNULL(@texto, N''))));

    /* Se sustituyen ambas variantes (mayuscula y minuscula) porque el UPPER de
       esta collation no es simetrico: UPPER(N'i' acentuada) devuelve la forma
       en minuscula. NCHAR evita depender de la codificacion del .sql. */
    SET @r = REPLACE(@r, NCHAR(193), N'A');  SET @r = REPLACE(@r, NCHAR(225), N'A');
    SET @r = REPLACE(@r, NCHAR(201), N'E');  SET @r = REPLACE(@r, NCHAR(233), N'E');
    SET @r = REPLACE(@r, NCHAR(205), N'I');  SET @r = REPLACE(@r, NCHAR(237), N'I');
    SET @r = REPLACE(@r, NCHAR(211), N'O');  SET @r = REPLACE(@r, NCHAR(243), N'O');
    SET @r = REPLACE(@r, NCHAR(218), N'U');  SET @r = REPLACE(@r, NCHAR(250), N'U');
    SET @r = REPLACE(@r, NCHAR(220), N'U');  SET @r = REPLACE(@r, NCHAR(252), N'U');
    SET @r = REPLACE(@r, NCHAR(209), N'N');  SET @r = REPLACE(@r, NCHAR(241), N'N');

    -- Caracteres de control y puntuacion que generan duplicados
    SET @r = REPLACE(@r, CHAR(9),  N' ');
    SET @r = REPLACE(@r, CHAR(10), N' ');
    SET @r = REPLACE(@r, CHAR(13), N' ');
    SET @r = REPLACE(@r, N'.', N'');
    SET @r = REPLACE(@r, N',', N'');
    WHILE CHARINDEX(N'  ', @r) > 0
        SET @r = REPLACE(@r, N'  ', N' ');

    -- Tras la sustitucion solo quedan caracteres ASCII: el UPPER es seguro
    RETURN UPPER(TRIM(@r));
END
GO

/* Mapa declarativo de sinonimos. Se crea antes de la funcion porque esta lo
   consulta: cualquier alias agregado desde Administracion > Calidad de datos
   pasa a aplicarse sin recompilar nada. Las claves se guardan ya normalizadas
   (sin tildes, en mayusculas) porque asi es como las recibe la funcion. */
IF OBJECT_ID('dbo.sys_territorios_alias', 'U') IS NULL
BEGIN
    CREATE TABLE dbo.sys_territorios_alias (
        nivel            NVARCHAR(20)  NOT NULL,
        nombre_original  NVARCHAR(200) NOT NULL,
        nombre_canonico  NVARCHAR(200) NOT NULL,
        CONSTRAINT UQ_territorio_alias UNIQUE (nivel, nombre_original)
    );

    INSERT INTO dbo.sys_territorios_alias (nivel, nombre_original, nombre_canonico)
    VALUES
        (N'REGION', N'LIMA METROPOLITANA',            N'LIMA'),
        (N'REGION', N'LIMA REGION',                   N'LIMA'),
        (N'REGION', N'LIMA PROVINCIAS',               N'LIMA'),
        (N'REGION', N'PROVINCIA DE LIMA',             N'LIMA'),
        (N'REGION', N'LIMA METROPOLITANA Y CALLAO',   N'LIMA'),
        (N'REGION', N'CALLAO-LIMA',                   N'LIMA');
    PRINT 'Tabla dbo.sys_territorios_alias creada.';
END

/* Semilla idempotente de las variantes conocidas: si la tabla ya existia con
   solo algunas filas, se completan las que falten. */
INSERT INTO dbo.sys_territorios_alias (nivel, nombre_original, nombre_canonico)
SELECT v.nivel, v.nombre_original, v.nombre_canonico
FROM (VALUES
        (N'REGION', N'LIMA METROPOLITANA',          N'LIMA'),
        (N'REGION', N'LIMA REGION',                 N'LIMA'),
        (N'REGION', N'LIMA PROVINCIAS',             N'LIMA'),
        (N'REGION', N'PROVINCIA DE LIMA',           N'LIMA'),
        (N'REGION', N'LIMA METROPOLITANA Y CALLAO', N'LIMA'),
        (N'REGION', N'CALLAO-LIMA',                 N'LIMA')
     ) AS v(nivel, nombre_original, nombre_canonico)
WHERE NOT EXISTS (
    SELECT 1 FROM dbo.sys_territorios_alias a
    WHERE a.nivel = v.nivel AND a.nombre_original = v.nombre_original
);
GO

IF OBJECT_ID('dbo.fn_canonico_territorio', 'FN') IS NOT NULL DROP FUNCTION dbo.fn_canonico_territorio;
GO

CREATE FUNCTION dbo.fn_canonico_territorio(@nivel NVARCHAR(20), @texto NVARCHAR(200))
RETURNS NVARCHAR(200)
AS
BEGIN
    DECLARE @clave NVARCHAR(200) = dbo.fn_normaliza_texto(@texto);
    DECLARE @nivel_norm NVARCHAR(20) = UPPER(ISNULL(@nivel, N''));
    DECLARE @canonico NVARCHAR(200);

    IF @clave IS NULL OR @clave = '' RETURN NULL;

    /* 1. Alias declarados en dbo.sys_territorios_alias (editables desde la UI). */
    IF @nivel_norm IN (N'REGION', N'PROVINCIA', N'DISTRITO')
    BEGIN
        SELECT @canonico = a.nombre_canonico
        FROM dbo.sys_territorios_alias a
        WHERE a.nivel = @nivel_norm AND a.nombre_original = @clave;

        IF @canonico IS NOT NULL AND @canonico <> ''
            RETURN dbo.fn_normaliza_texto(@canonico);
    END

    /* 2. Red de seguridad para las variantes conocidas de Lima, en caso de que
          la tabla de alias se vacie. */
    IF @nivel_norm = N'REGION' AND @clave IN (
        N'LIMA METROPOLITANA', N'LIMA REGION', N'LIMA PROVINCIAS',
        N'PROVINCIA DE LIMA', N'LIMA METROPOLITANA Y CALLAO', N'CALLAO-LIMA'
    )
        SET @clave = N'LIMA';

    RETURN @clave;
END
GO

/* ---------------------------------------------------------------------------
   2. Dimension extendida de IPRESS (tabla materializada)

   Se materializa como tabla y no como vista porque las consultas analiticas la
   consultan siempre en combinacion con los tres hechos: resolver en cada
   consulta la geografia de los ~8.500 codigos de IPRESS que aparecen en los
   hechos pero no estan catalogados en dim_ipress seria demasiado costoso.

   Se refresca desde la aplicacion (Administracion > Mantenimiento).
   --------------------------------------------------------------------------- */
IF OBJECT_ID('dbo.dim_ipress_ext', 'U') IS NOT NULL DROP TABLE dbo.dim_ipress_ext;
GO

CREATE TABLE dbo.dim_ipress_ext (
    codigo_ipress        INT          NOT NULL PRIMARY KEY,
    nombre_establecimiento NVARCHAR(300) NULL,
    nombre               NVARCHAR(300) NULL,
    categoria            NVARCHAR(100) NULL,
    nivel                NVARCHAR(100) NULL,
    institucion          NVARCHAR(200) NULL,
    grupo                NVARCHAR(100) NULL,
    sub_grupo            NVARCHAR(200) NULL,
    macroregion          NVARCHAR(200) NULL,
    cuenta_triaje        NVARCHAR(20)  NULL,
    cuenta_zc            NVARCHAR(20)  NULL,
    ubigeo               NVARCHAR(20)  NULL,
    ubigeo_region        NVARCHAR(2)   NULL,
    ubigeo_provincia     NVARCHAR(4)   NULL,
    region               NVARCHAR(200) NULL,
    provincia            NVARCHAR(200) NULL,
    distrito             NVARCHAR(200) NULL,
    region_fuente        NVARCHAR(20)  NULL,
    en_dim_ipress        BIT           NOT NULL CONSTRAINT DF_ipress_ext_en_dim DEFAULT 1,
    tiene_afiliados      BIT           NOT NULL CONSTRAINT DF_ipress_ext_afil DEFAULT 0,
    tiene_atenciones     BIT           NOT NULL CONSTRAINT DF_ipress_ext_aten DEFAULT 0,
    tiene_capacidad      BIT           NOT NULL CONSTRAINT DF_ipress_ext_capa DEFAULT 0,
    fecha_actualizacion  DATETIME2     NOT NULL CONSTRAINT DF_ipress_ext_fecha DEFAULT SYSDATETIME()
);
GO

/* Fuente de geografia: dim_ipress tiene prioridad (es el catalogo oficial de
   establecimientos); los hechos se usan como respaldo para los codigos que no
   estan catalogados.

   El universo de codigos se construye con UNION y se resuelve con LEFT JOIN
   desde ese universo: garantiza exactamente una fila por codigo. Con
   FULL OUTER JOIN encadenado, los codigos presentes solo en atenciones se
   perdian (el ON exigia COALESCE(d,a) y ambos eran NULL) y ademas se
   generaban filas duplicadas. */
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
    codigo_ipress, nombre_establecimiento, nombre, categoria, nivel, institucion,
    grupo, sub_grupo, macroregion, cuenta_triaje, cuenta_zc, ubigeo,
    ubigeo_region, ubigeo_provincia, region, provincia, distrito,
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
GO

/* Marcas de presencia por hecho: permite saber que dimensiones de hecho
   existen para un EESS sin agregar COUNT(DISTINCT) en cada consulta. */
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
GO

CREATE INDEX IX_ipress_ext_region    ON dbo.dim_ipress_ext (region);
CREATE INDEX IX_ipress_ext_provincia ON dbo.dim_ipress_ext (region, provincia);
CREATE INDEX IX_ipress_ext_distrito  ON dbo.dim_ipress_ext (region, provincia, distrito);
CREATE INDEX IX_ipress_ext_nombre    ON dbo.dim_ipress_ext (nombre_establecimiento);
CREATE INDEX IX_ipress_ext_capacidad ON dbo.dim_ipress_ext (tiene_capacidad, region);
GO

/* Vista de compatibilidad para las vistas del usuario (v_brecha_... usa
   dim_ipress directamente y no necesita cambios). */
PRINT 'Migracion 001 completada.';
GO