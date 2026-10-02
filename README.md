# SIBS — Sistema de Información para la Identificación y Priorización de Brechas de Capacidad Sanitaria

Aplicación web (Flask, arquitectura MVC) para consultar brechas entre la demanda
asegurada (SIS) y la capacidad instalada de los establecimientos de salud del
Perú, con ranking de priorización configurable, monitoreo de alertas y
exportación de resultados.

---

## 1. Requisitos

- Python 3.10 o superior
- SQL Server 2017 o superior (o SQL Server Express)
- Driver ODBC 17 o 18 para SQL Server

## 2. Instalación

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

## 3. Configuración

Todo se configura por variables de entorno (ver `config.py`). Los valores por
defecto apuntan a la base local `SaludBrechasDB` con autenticación de Windows.

| Variable | Por defecto | Descripción |
|---|---|---|
| `SIBS_ENV` | `desarrollo` | `produccion`, `desarrollo` o `pruebas` |
| `SIBS_SECRET_KEY` | *(definida)* | Clave de firma de sesiones. **Cámbiela en producción.** |
| `SIBS_DB_SERVER` | `DESKTOP-VN86FJO\SQLEXPRESS` | Servidor SQL Server |
| `SIBS_DB_NAME` | `SaludBrechasDB` | Base de datos |
| `SIBS_DB_TRUSTED` | `yes` | `no` para usar usuario y contraseña |
| `SIBS_DB_UID` / `SIBS_DB_PWD` | *(vacío)* | Credenciales si `SIBS_DB_TRUSTED=no` |
| `SIBS_DB_POOL_SIZE` | `8` | Conexiones del pool |
| `SIBS_FECHA_INICIO` / `SIBS_FECHA_FIN` | `2023-01-01` / `2023-12-31` | Periodo por defecto |
| `SIBS_UMBRAL_OCUPACION` | `85` | Umbral de ocupación crítica (%) |
| `SIBS_MAX_UPLOAD_MB` | `60` | Tamaño máximo de archivo cargado |
| `SIBS_FILAS_PAGINA` | `50` | Filas por página |
| `SIBS_MAX_EXPORTAR` | `50000` | Tope de filas por exportación |

La cookie de sesión es `HttpOnly` y `SameSite=Lax`; en producción se marca
además `Secure` (solo HTTPS). Los formularios POST incorporan un token CSRF
(`flask-wtf`), obligatorio fuera del ambiente de pruebas.

Para autenticación con SQL Server:

```powershell
$env:SIBS_DB_TRUSTED = "no"
$env:SIBS_DB_UID = "sa"
$env:SIBS_DB_PWD = "clave"
```

## 4. Ejecución

```powershell
python run.py
```

La aplicación queda en <http://127.0.0.1:5000>.

Al arrancar se aplican los scripts de `app/database/migrations/` (idempotentes)
y, si `sys_usuarios` está vacía, se crea el usuario `admin` con contraseña
`admin123`. **Cámbiela en el primer acceso.**

Comando adicional:

```powershell
flask --app run.py reconstruir-dim-ipress   # regenera dbo.dim_ipress_ext
```

## 5. Arquitectura

```
config.py                      Configuración por ambiente
run.py                         Punto de entrada
app/
  __init__.py                  Fábrica de la aplicación (create_app)
  database/
    bd.py                      Pool de conexiones pyodbc
    migraciones.py             Ejecución de migraciones y semilla
    migrations/*.sql           Esquema, funciones y procedimientos
  models/                      Capa de datos (todo el SQL vive aquí)
    base_model.py              Consultas parametrizadas y conversión de tipos
    territorio_model.py         Catálogos, geografía y alias
    indicadores_model.py       Indicadores globales, territoriales y series
    ranking_model.py           Motor de priorización por reglas
    procedimientos_model.py    Ejecución de procedimientos almacenados
    admin_model.py             Usuarios, auditoría, cargas y perfiles
  controllers/                 Traducen HTTP a llamadas de modelo
    seguridad.py               Autenticación y control por rol
    auth_controller.py         Login y logout
    tablero_controller.py      Panel y resumen
    analisis_controller.py     Territorio, ranking, EESS, evolución, alertas
    admin_controller.py        Usuarios, auditoría, cargas, perfiles, calidad
    api_controller.py          API JSON de solo lectura
    exportar.py                Descargas CSV y XLSX
  utils/
    filtros.py                 Normalización y WHERE común
    formato.py                 Formatos de presentación
  views/
    templates/                 Plantillas Jinja2
      _macros.html             KPI, estados y macros de gráficos SVG
    static/                    CSS y JS propios (sin CDN)
```

**Regla de la separación:** los controladores no contienen SQL. Toda consulta
SQL está en `app/models/` y se apoya en `app/utils/filtros.py` para construir el
`WHERE`, de modo que los filtros se validan una sola vez.

Los controladores tampoco transforman datos para las plantillas: arman las
listas que alimentan los gráficos (`brechas_grafico`, `departamentos_grafico`)
y la plantilla se limita a presentarlas.

## 6. Roles

| Rol | Puede hacer |
|---|---|
| `ADMINISTRADOR` | Todo, incluido el módulo de administración |
| `FUNCIONARIO` | Consultas, rankings, reportes y exportaciones |
| `ANALISTA_SANITARIO` | Consulta territorial, fichas y series |
| `ANALISTA_DATOS` | Análisis comparativo y exploración de datos |
| `MONITOREO` | Vigilancia de ocupación crítica e inoperatividad |

El control se aplica en `app/controllers/seguridad.py`: `@requiere_login`
exige sesión y el blueprint `admin` exige rol `ADMINISTRADOR`.

### Perfil propio

Cualquier usuario con sesión accede a **Mi perfil** (`/perfil`) para actualizar
sus datos y cambiar su contraseña. El cambio de contraseña exige la contraseña
actual, y el usuario no puede modificar su propio rol ni su estado: esos campos
solo los toca un administrador.

El sistema impide además quedarse sin administración: no se puede desactivar ni
eliminar la propia cuenta, ni dejar al último administrador activo sin rol
`ADMINISTRADOR`. La comprobación es `AdminModel._verificar_admin_restante()` y
cubre tanto desactivar la cuenta como degradarla a otro rol, porque en ambos
casos el usuario deja de ser administrador.

## 7. Modelo de datos

Estrella con tres hechos y una dimensión:

- `dbo.dim_ipress` — catálogo de establecimientos (591 registros)
- `dbo.fact_afiliados_sis` — afiliación por corte (8 322 registros)
- `dbo.fact_atenciones` — atenciones por corte (86 registros)
- `dbo.fact_capacidad_diaria` — capacidad y ocupación diaria (8 550 registros)

La geografía no se toma de una sola fuente porque cada hecho la trae con
formato propio. `dbo.dim_ipress_ext` la unifica:

- Toma la unión de **todos** los códigos presentes en los tres hechos (8 999),
  no solo los catalogados, para no perder establecimientos que solo reporten
  afiliación o atenciones.
- Resuelve la geografía con precedencia catálogo → afiliados → atenciones,
  quedándose con el registro más reciente.
- Normaliza tildes y mayúsculas con `dbo.fn_normaliza_texto` y unifica las
  variantes de Lima (`LIMA METROPOLITANA`, `LIMA REGION`, `LIMA PROVINCIAS`,
  `CALLAO-LIMA`…) a `LIMA` mediante `dbo.fn_canonico_territorio`.

Los sinónimos de `dbo.fn_canonico_territorio` se leen de
`dbo.sys_territorios_alias`, que se administra desde
**Administración → Calidad de datos**: un alias agregado se aplica en la
siguiente reconstrucción de `dim_ipress_ext` sin tocar código.

### Semántica de los indicadores

| Indicador | Cálculo |
|---|---|
| Afiliados | Último corte del periodo (no promedio) |
| Atenciones | Suma de flujos del periodo |
| Recursos | Promedio diario de los días con reporte |
| Ocupación | Recursos ocupados / recursos operativos |
| Ratio afiliados/cama | Afiliados / recursos operativos |
| Presión de atención | Atenciones por mil afiliados |
| Población vulnerable | 0-4 años + 60+ años + mujeres en edad fértil |

Las métricas de capacidad se expresan como promedio sobre los **días con
reporte**, no sobre todos los días del periodo: un establecimiento que solo
reporta 10 de 365 días no debe diluir su ocupación.

## 8. Ranking de priorización

Los perfiles y sus reglas viven en `dbo.sys_perfiles_prioridad` y
`dbo.sys_reglas_prioridad`, y se editan desde **Administración → Perfiles**.

Cada regla tiene un código de indicador, un peso, un rango de normalización
(`umbral_minimo` / `umbral_maximo`), una dirección (`MAYOR` o `MENOR`) y un
indicador de obligatoriedad. El indicador se elige de una lista cerrada
(`CATALOGO_INDICADORES` en `app/models/ranking_model.py`): el formulario no
acepta texto libre porque una regla con un nombre que el motor no calcula se
descartaría en silencio y su peso no sumaría. El cálculo:

1. Cada indicador se normaliza a `[0, 1]` dentro de su rango. Si la dirección
   es `MENOR`, se invierte: `1` significa peor.
2. Se multiplica por el peso de la regla y se suma.
3. El puntaje se relativiza al máximo del conjunto y se clasifica en `CRITICA`,
   `ALTA`, `MEDIA` o `BAJA` con los umbrales del perfil.
4. Si falta un indicador **obligatorio**, el registro queda `NO_EVALUABLE` y se
   informa el motivo; no se le asigna puntaje.

### Nombres de indicador y equivalencias

Los perfiles sembrados en `002_perfiles_prioridad.sql` usan nombres del dominio
(`presion_afiliados`, `poblacion_rural`, `poblacion_vulnerable`) que no coinciden
con los alias que exponen las consultas (`ratio_afiliados_cama`, `porc_rural`,
`porc_vulnerable`). En lugar de forzar un único nombre en la base, la
equivalencia se resuelve en código:

- `resolver_indicador(codigo)` devuelve el alias canónico o `None` si la regla
  no tiene soporte en el motor.
- `nombre_indicador(codigo)` devuelve la etiqueta legible.
- `codigos_equivalentes(codigo)` devuelve **todos** los nombres que apuntan al
  mismo indicador.

La última función es la que evita el error más silencioso de este módulo: si el
perfil ya tiene la regla `presion_afiliados` y el administrador elige
`ratio_afiliados_cama` en el formulario, ambas se resuelven al mismo indicador y
su peso se sumaría **dos veces** en el ranking. El controlador de alta rechaza el
segundo caso como duplicado. Las reglas nuevas se guardan siempre con el alias
canónico; las antiguas conservan su nombre histórico y siguen resolviéndose.

## 9. API JSON de solo lectura

Requiere sesión iniciada. Devuelve `{"ok": true, "datos": [...]}`.

```
GET /api/catalogo/regiones
GET /api/catalogo/provincias?region=LIMA
GET /api/catalogo/distritos?region=LIMA&provincia=LIMA
GET /api/catalogo/establecimientos?q=hospital&region=LIMA
GET /api/indicadores/globales
GET /api/indicadores/serie?granularidad=MENSUAL
GET /api/indicadores/territorio?nivel=region
GET /api/indicadores/establecimiento/<codigo_ipress>
GET /api/alertas/resumen
GET /api/alertas/ocupacion?limite=50
GET /api/ranking?perfil=BRECHA_CAPACIDAD&limite=25
```

Los filtros de análisis (`fecha_inicio`, `fecha_fin`, `region`, `provincia`,
`distrito`, `categoria`, `plan_seguro`, `servicio`, `umbral_ocupacion`,
`granularidad`) se aceptan como query string en cualquier endpoint.

## 10. Carga de datos

**Administración → Cargas de datos** registra el archivo (CSV o XLSX) con su
fuente, fecha del dato, tabla destino y modo de carga. El sistema valida la
extensión, guarda el archivo en `instance/cargas/`, calcula el hash SHA-256 y
deja el registro en estado `VALIDADO`. Al eliminar el registro también se
borra el archivo del disco.

La aplicación de los datos al hecho correspondiente no es automática: la realiza
el administrador mediante los procedimientos almacenados, desde
**Análisis → Alertas**, lo que garantiza que cada cambio quede auditado.

## 11. Notas de operación

- Toda escritura pasa por `BaseModel.ejecutar()` (o `consultar(..., commit=True)`).
  `consultar()` rechaza `INSERT/UPDATE/DELETE/MERGE` a propósito: el pool hace
  `rollback` al devolver la conexión, así que una escritura sin commit se
  perdería en silencio.
- Los catálogos, la ficha de establecimiento y el mapa de alias se derivan de
  `dbo.dim_ipress_ext`. Si un código aparece con provincia o región vacía,
  reconstruya la dimensión desde **Administración → Calidad de datos**.
- La auditoría (`dbo.sys_auditoria`) registra accesos, cambios de usuarios,
  reglas de prioridad, cargas y reconstrucciones. No debe truncarse.
- La carga de archivos queda en `VALIDADO` aunque no se haya aplicado a la tabla
  destino; ese paso es manual y deliberado.
- `sys_usuarios.activo = 0` es una baja lógica: los usuarios desactivados siguen
  en la tabla y conservan su auditoría. Para un borrado real hay que eliminar
  antes sus filas de `dbo.sys_auditoria`, porque la FK lo impide.
- Los gráficos son SVG generado en las plantillas (`_macros.html`), sin ninguna
  librería JavaScript externa. `grafico_barras` normaliza sobre el máximo de los
  datos recibidos (salvo que se pase uno explícito) para que las barras comparen
  entre sí, y `grafico_lineas` normaliza **cada serie sobre su propio rango**:
  lo relevante en un panel con indicadores de unidades distintas es la
  tendencia, no la magnitud.

## 12. Pruebas

Los scripts de verificación se ejecutan contra la base real con el
cliente de pruebas de Flask (`WTF_CSRF_ENABLED` desactivado en el ambiente
`pruebas`):

```powershell
python C:\...\test_web.py        # vistas, filtros, exportaciones, API y roles
python C:\...\test_web_post.py   # formularios POST, CSRF, permisos y cargas
python C:\...\test_modelos3.py   # modelos: catálogos, rankings, series, alertas
```

`test_web.py` y `test_web_post.py` crean usuarios temporales (`smkweb*`,
`smkpost*`) y los eliminan al terminar, dejando solo `admin`.
`test_modelos3.py` crea un usuario `t*` que **no** se autoclimpia: hay que
desactivarlo o borrarlo al terminar (junto con sus filas de auditoría).

Los tresborran los registros de `sys_reglas_prioridad` que crean, así que el
perfil queda con sus reglas originales.

Conviene ejecutar `test_web_post.py` **antes** que `test_modelos3.py`: el segundo
consulta `poblacion_rural` para elegir indicadores de prueba y puede elegir uno
distinto según qué reglas existan en ese momento.
