/* ============================================================================
   SIBS - Migracion 002: perfiles de priorizacion y reglas base

   Cada regla representa un indicador calculado sobre el agregado de cada
   establecimiento. El motor de ranking (app/models/ranking_model.py) toma
   el valor del indicador, lo normaliza al rango [umbral_minimo,
   umbral_maximo], lo invierte si la direccion es MENOR y lo pondera por
   `peso`. El score resultante ordena el ranking.
   ============================================================================ */

SET NOCOUNT ON;
GO

/* ---------------------------- PERFILES BASE ------------------------------- */
IF NOT EXISTS (SELECT 1 FROM dbo.sys_perfiles_prioridad WHERE codigo = 'BRECHA_CAPACIDAD')
    INSERT INTO dbo.sys_perfiles_prioridad
        (codigo, nombre, descripcion, activo, es_base,
         umbral_critico_pct, umbral_alto_pct, umbral_medio_pct)
    VALUES
    ('BRECHA_CAPACIDAD', 'Brecha de capacidad',
     'Equilibrio entre demanda poblacional (afiliados y atenciones) y oferta instalada de camas, UCI y recursos. Perfil general para priorizacion territorial.',
     1, 1, 75.00, 50.00, 25.00);

IF NOT EXISTS (SELECT 1 FROM dbo.sys_perfiles_prioridad WHERE codigo = 'SOBRECARGA')
    INSERT INTO dbo.sys_perfiles_prioridad
        (codigo, nombre, descripcion, activo, es_base,
         umbral_critico_pct, umbral_alto_pct, umbral_medio_pct)
    VALUES
    ('SOBRECARGA', 'Sobrecarga y ocupacion critica',
     'Establecimientos con mayor riesgo de saturacion: nivel y pico de ocupacion, dias sobre umbral y presion de emergencia. Perfil para monitorizacion preventiva.',
     1, 1, 75.00, 50.00, 25.00);

IF NOT EXISTS (SELECT 1 FROM dbo.sys_perfiles_prioridad WHERE codigo = 'ACCESO_RURAL')
    INSERT INTO dbo.sys_perfiles_prioridad
        (codigo, nombre, descripcion, activo, es_base,
         umbral_critico_pct, umbral_alto_pct, umbral_medio_pct)
    VALUES
    ('ACCESO_RURAL', 'Acceso rural y vulnerabilidad',
     'Territorios con poblacion rural o vulnerable, baja cobertura de UCI y baja frecuencia de reporte. Perfil de someday para brechas de acceso.',
     1, 1, 75.00, 50.00, 25.00);
GO

/* ------------------------- REGLAS: BRECHA_CAPACIDAD ----------------------- */
IF NOT EXISTS (SELECT 1 FROM dbo.sys_reglas_prioridad r
               JOIN dbo.sys_perfiles_prioridad p ON p.id_perfil = r.id_perfil
               WHERE p.codigo = 'BRECHA_CAPACIDAD' AND r.codigo = 'presion_afiliados')
    INSERT INTO dbo.sys_reglas_prioridad
        (id_perfil, codigo, nombre, descripcion, peso, umbral_minimo, umbral_maximo, direccion, obligatorio, orden)
    SELECT p.id_perfil, v.codigo, v.nombre, v.descripcion, v.peso, v.umin, v.umax, v.dir, v.obl, v.orden
    FROM dbo.sys_perfiles_prioridad p
    CROSS APPLY (VALUES
        ('presion_afiliados', 'Presion de afiliados',
         'Afiliados SIS por cama operativa. Mide quanta poblacion asignada atiende cada cama disponible.',
         25.000, 0.0, NULL, 'MAYOR', 0, 1),
        ('tasa_ocupacion', 'Tasa de ocupacion global',
         'Porcentaje promedio de ocupacion de camas en el periodo.',
         20.000, 0.0, 100.0, 'MAYOR', 0, 2),
        ('dias_sobre_umbral', 'Dias sobre umbral de ocupacion',
         'Cantidad de dias con ocupacion igual o superior al 85 %.',
         10.000, 0.0, NULL, 'MAYOR', 0, 3),
        ('tasa_inoperatividad', 'Tasa de inoperatividad de recursos',
         'Porcentaje de recursos inoperativos (ventiladores, UCI, hospitalizacion) sobre el total instalado.',
         15.000, 0.0, 100.0, 'MAYOR', 0, 4),
        ('presion_atencion', 'Presion de atencion',
         'Atenciones registradas por cada 1000 afiliados en el periodo.',
         10.000, 0.0, NULL, 'MAYOR', 0, 5),
        ('poblacion_vulnerable', 'Poblacion vulnerable',
         'Porcentaje de afiliados pediatricos, adultos mayores y mujeres en edad fertil.',
         10.000, 0.0, 100.0, 'MAYOR', 0, 6),
        ('cobertura_uci', 'Cobertura de UCI',
         '1 si el establecimiento cuenta con UCI operativa, 0 si no. Direction MENOR: la ausencia de UCI eleva la brecha.',
         5.000, 0.0, 1.0, 'MENOR', 0, 7),
        ('dias_sin_reporte', 'Dias sin reporte de capacidad',
         'Dias del periodo sin registro de capacidad. Senal de opacidad del dato.',
         5.000, 0.0, NULL, 'MAYOR', 0, 8)
    ) AS v(codigo, nombre, descripcion, peso, umin, umax, dir, obl, orden)
    WHERE p.codigo = 'BRECHA_CAPACIDAD';
GO

/* --------------------------- REGLAS: SOBRECARGA --------------------------- */
IF NOT EXISTS (SELECT 1 FROM dbo.sys_reglas_prioridad r
               JOIN dbo.sys_perfiles_prioridad p ON p.id_perfil = r.id_perfil
               WHERE p.codigo = 'SOBRECARGA' AND r.codigo = 'tasa_ocupacion')
    INSERT INTO dbo.sys_reglas_prioridad
        (id_perfil, codigo, nombre, descripcion, peso, umbral_minimo, umbral_maximo, direccion, obligatorio, orden)
    SELECT p.id_perfil, v.codigo, v.nombre, v.descripcion, v.peso, v.umin, v.umax, v.dir, v.obl, v.orden
    FROM dbo.sys_perfiles_prioridad p
    CROSS APPLY (VALUES
        ('tasa_ocupacion', 'Tasa de ocupacion global',
         'Porcentaje promedio de ocupacion de camas en el periodo.',
         30.000, 0.0, 100.0, 'MAYOR', 0, 1),
        ('pico_ocupacion', 'Pico de ocupacion',
         'Maximo de ocupacion diaria registrado en el periodo.',
         25.000, 0.0, 100.0, 'MAYOR', 0, 2),
        ('dias_sobre_umbral', 'Dias sobre umbral de ocupacion',
         'Cantidad de dias con ocupacion igual o superior al 85 %.',
         25.000, 0.0, NULL, 'MAYOR', 0, 3),
        ('presion_emergencia', 'Presion de emergencia',
         'Atenciones de emergencia por cada cama operativa de emergencia.',
         15.000, 0.0, NULL, 'MAYOR', 0, 4),
        ('tasa_inoperatividad', 'Tasa de inoperatividad de recursos',
         'Porcentaje de recursos inoperativos sobre el total instalado.',
         5.000, 0.0, 100.0, 'MAYOR', 0, 5)
    ) AS v(codigo, nombre, descripcion, peso, umin, umax, dir, obl, orden)
    WHERE p.codigo = 'SOBRECARGA';
GO

/* --------------------------- REGLAS: ACCESO_RURAL ------------------------- */
IF NOT EXISTS (SELECT 1 FROM dbo.sys_reglas_prioridad r
               JOIN dbo.sys_perfiles_prioridad p ON p.id_perfil = r.id_perfil
               WHERE p.codigo = 'ACCESO_RURAL' AND r.codigo = 'poblacion_rural')
    INSERT INTO dbo.sys_reglas_prioridad
        (id_perfil, codigo, nombre, descripcion, peso, umbral_minimo, umbral_maximo, direccion, obligatorio, orden)
    SELECT p.id_perfil, v.codigo, v.nombre, v.descripcion, v.peso, v.umin, v.umax, v.dir, v.obl, v.orden
    FROM dbo.sys_perfiles_prioridad p
    CROSS APPLY (VALUES
        ('poblacion_rural', 'Poblacion rural',
         'Porcentaje de afiliados residentes en areas rurales.',
         30.000, 0.0, 100.0, 'MAYOR', 0, 1),
        ('presion_afiliados', 'Presion de afiliados',
         'Afiliados SIS por cama operativa.',
         25.000, 0.0, NULL, 'MAYOR', 0, 2),
        ('dias_sin_reporte', 'Dias sin reporte de capacidad',
         'Dias del periodo sin registro de capacidad.',
         15.000, 0.0, NULL, 'MAYOR', 0, 3),
        ('poblacion_vulnerable', 'Poblacion vulnerable',
         'Porcentaje de afiliados pediatricos, adultos mayores y mujeres en edad fertile.',
         15.000, 0.0, 100.0, 'MAYOR', 0, 4),
        ('cobertura_uci', 'Cobertura de UCI',
         '1 si cuenta con UCI operativa, 0 si no. Direction MENOR.',
         10.000, 0.0, 1.0, 'MENOR', 0, 5),
        ('tasa_inoperatividad', 'Tasa de inoperatividad de recursos',
         'Porcentaje de recursos inoperativos sobre el total instalado.',
         5.000, 0.0, 100.0, 'MAYOR', 0, 6)
    ) AS v(codigo, nombre, descripcion, peso, umin, umax, dir, obl, orden)
    WHERE p.codigo = 'ACCESO_RURAL';
GO

PRINT 'Migracion 002 completada.';
GO