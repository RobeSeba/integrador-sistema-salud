/* ============================================================================
   SIBS - Migracion 004: permisos por usuario (control de modulos por rol)

   El administrador define que modulos (secciones y graficos) ve cada usuario.
   La tabla guarda el conjunto completo de modulos del sistema con un bit de
   permiso por fila, de modo que el efectivo del usuario es simplemente la
   suma de los permitidos. Si el usuario no tiene filas, rige el default de
   su rol (app/controllers/seguridad.py -> MODULOS_POR_ROL).

   La lista de modulos vive en seguridad.py: la base solo guarda claves, asi
   agregar un modulo nuevo no obliga a alterar la tabla.
   ============================================================================ */

SET NOCOUNT ON;
GO

IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'sys_permisos_usuario')
BEGIN
    CREATE TABLE dbo.sys_permisos_usuario (
        id_usuario   INT           NOT NULL,
        modulo       NVARCHAR(50)  NOT NULL,
        permitido    BIT           NOT NULL DEFAULT 0,
        fecha_cambio DATETIME      NOT NULL DEFAULT GETDATE(),
        CONSTRAINT pk_permisos_usuario PRIMARY KEY (id_usuario, modulo),
        CONSTRAINT fk_permisos_usuario FOREIGN KEY (id_usuario)
            REFERENCES dbo.sys_usuarios(id_usuario)
            ON DELETE CASCADE
    );
    CREATE INDEX idx_permisos_modulo
        ON dbo.sys_permisos_usuario(modulo);
    PRINT 'Tabla sys_permisos_usuario creada con exito.';
END
GO

PRINT 'Migracion 004 completada.';
GO
