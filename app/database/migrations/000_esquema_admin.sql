/* ============================================================================
   SIBS - Migracion 000: esquema de administracion (usuarios, auditoria,
   cargas y perfiles/reglas de priorizacion)

   Estas tablas las usan app/models/admin_model.py y app/database/migraciones.py
   (siembra del usuario admin) pero no venian creadas en ningun script del
   proyecto. Esta migracion las agrega de forma idempotente (IF NOT EXISTS).
   ============================================================================ */

SET NOCOUNT ON;
GO

-- ---------------------------------------------------------------------------
-- sys_usuarios
-- ---------------------------------------------------------------------------
IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'sys_usuarios')
BEGIN
    CREATE TABLE dbo.sys_usuarios (
        id_usuario        INT IDENTITY(1,1) PRIMARY KEY,
        usuario           NVARCHAR(100)  NOT NULL UNIQUE,
        password_hash     NVARCHAR(255)  NOT NULL,
        nombre_completo   NVARCHAR(200)  NOT NULL,
        rol               NVARCHAR(50)   NOT NULL,
        email             NVARCHAR(200)  NULL,
        cargo             NVARCHAR(200)  NULL,
        activo            BIT            NOT NULL DEFAULT 1,
        fecha_creacion    DATETIME       NOT NULL DEFAULT GETDATE(),
        ultimo_acceso     DATETIME       NULL
    );
    PRINT 'Tabla sys_usuarios creada con éxito.';
END
GO

-- ---------------------------------------------------------------------------
-- sys_auditoria
-- ---------------------------------------------------------------------------
IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'sys_auditoria')
BEGIN
    CREATE TABLE dbo.sys_auditoria (
        id_auditoria   INT IDENTITY(1,1) PRIMARY KEY,
        fecha_evento   DATETIME       NOT NULL DEFAULT GETDATE(),
        id_usuario     INT            NULL,
        usuario        NVARCHAR(100)  NULL,
        modulo         NVARCHAR(100)  NULL,
        accion         NVARCHAR(100)  NULL,
        detalle        NVARCHAR(1000) NULL,
        CONSTRAINT fk_auditoria_usuario FOREIGN KEY (id_usuario)
            REFERENCES dbo.sys_usuarios(id_usuario)
    );
    CREATE INDEX idx_auditoria_fecha ON dbo.sys_auditoria(fecha_evento);
    PRINT 'Tabla sys_auditoria creada con éxito.';
END
GO

-- ---------------------------------------------------------------------------
-- sys_cargas
-- ---------------------------------------------------------------------------
IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'sys_cargas')
BEGIN
    CREATE TABLE dbo.sys_cargas (
        id_carga               INT IDENTITY(1,1) PRIMARY KEY,
        nombre_archivo         NVARCHAR(255)  NOT NULL,
        ruta_archivo           NVARCHAR(500)  NULL,
        fuente                 NVARCHAR(100)  NULL,
        tabla_destino          NVARCHAR(100)  NOT NULL,
        fecha_dato             DATE           NULL,
        fecha_inicio_periodo   DATE           NULL,
        fecha_fin_periodo      DATE           NULL,
        fecha_carga            DATETIME       NOT NULL DEFAULT GETDATE(),
        filas_insertadas       INT            NOT NULL DEFAULT 0,
        filas_rechazadas       INT            NOT NULL DEFAULT 0,
        modo_carga             NVARCHAR(30)   NOT NULL DEFAULT 'INCREMENTAL',
        estado                 NVARCHAR(30)   NOT NULL DEFAULT 'PENDIENTE',
        mensaje                NVARCHAR(1000) NULL,
        id_usuario             INT            NULL,
        hash_archivo           NVARCHAR(100)  NULL,
        CONSTRAINT fk_cargas_usuario FOREIGN KEY (id_usuario)
            REFERENCES dbo.sys_usuarios(id_usuario)
    );
    CREATE INDEX idx_cargas_fecha  ON dbo.sys_cargas(fecha_carga);
    CREATE INDEX idx_cargas_tabla  ON dbo.sys_cargas(tabla_destino);
    PRINT 'Tabla sys_cargas creada con éxito.';
END
GO

-- ---------------------------------------------------------------------------
-- sys_perfiles_prioridad
-- ---------------------------------------------------------------------------
IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'sys_perfiles_prioridad')
BEGIN
    CREATE TABLE dbo.sys_perfiles_prioridad (
        id_perfil              INT IDENTITY(1,1) PRIMARY KEY,
        codigo                 NVARCHAR(50)   NOT NULL UNIQUE,
        nombre                 NVARCHAR(200)  NOT NULL,
        descripcion            NVARCHAR(1000) NULL,
        activo                 BIT            NOT NULL DEFAULT 1,
        es_base                BIT            NOT NULL DEFAULT 0,
        umbral_critico_pct     DECIMAL(5,2)   NOT NULL DEFAULT 75.00,
        umbral_alto_pct        DECIMAL(5,2)   NOT NULL DEFAULT 50.00,
        umbral_medio_pct       DECIMAL(5,2)   NOT NULL DEFAULT 25.00,
        fecha_creacion         DATETIME       NOT NULL DEFAULT GETDATE(),
        fecha_actualizacion    DATETIME       NULL
    );
    PRINT 'Tabla sys_perfiles_prioridad creada con éxito.';
END
GO

-- ---------------------------------------------------------------------------
-- sys_reglas_prioridad
-- ---------------------------------------------------------------------------
IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'sys_reglas_prioridad')
BEGIN
    CREATE TABLE dbo.sys_reglas_prioridad (
        id_regla        INT IDENTITY(1,1) PRIMARY KEY,
        id_perfil       INT            NOT NULL,
        codigo          NVARCHAR(50)   NOT NULL,
        nombre          NVARCHAR(200)  NOT NULL,
        descripcion     NVARCHAR(1000) NULL,
        peso            DECIMAL(6,3)   NOT NULL DEFAULT 0,
        umbral_minimo   FLOAT          NULL,
        umbral_maximo   FLOAT          NULL,
        direccion       NVARCHAR(10)   NOT NULL DEFAULT 'MAYOR',
        obligatorio     BIT            NOT NULL DEFAULT 0,
        activo          BIT            NOT NULL DEFAULT 1,
        orden           INT            NOT NULL DEFAULT 1,
        CONSTRAINT fk_reglas_perfil FOREIGN KEY (id_perfil)
            REFERENCES dbo.sys_perfiles_prioridad(id_perfil)
            ON DELETE CASCADE
    );
    CREATE INDEX idx_reglas_perfil ON dbo.sys_reglas_prioridad(id_perfil);
    PRINT 'Tabla sys_reglas_prioridad creada con éxito.';
END
GO

PRINT 'Migracion 000 completada.';
GO
