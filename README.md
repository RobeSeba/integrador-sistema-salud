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
`admin123`. Además siembran los usuarios funcionales `analista`,
`planificacion` y `monitoreo` con los módulos de su rol (ver sección 6).
**Cámbialas en el primer acceso.**

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
  modulos.py                   Catálogo de módulos y defaults por rol
  database/
    bd.py                      Pool de conexiones pyodbc
    migraciones.py             Ejecución de migraciones y semilla
    migrations/*.sql           Esquema, funciones y procedimientos
  models/                      Capa de datos (todo el SQL vive aquí)
    base_model.py              Consultas parametrizadas y conversión de tipos
    territorio_model.py         Catálogos, geografía y alias
    indicadores_model.py       Indicadores globales, territoriales y series
    epidemiologia_model.py     Vigilancia IRA y mortalidad COVID (dimensiones nuevas)
    ranking_model.py           Motor de priorización por reglas
    procedimientos_model.py    Ejecución de procedimientos almacenados
    admin_model.py             Usuarios, módulos, auditoría, cargas y perfiles
  controllers/                 Traducen HTTP a llamadas de modelo
    seguridad.py               Autenticación y control por rol y módulo
    auth_controller.py         Login, logout y aterrizaje por rol
    tablero_controller.py      Panel y resumen (secciones según módulos)
    analisis_controller.py     Territorio, ranking, EESS, evolución, alertas,
                               vigilancia IRA y mortalidad COVID
    admin_controller.py        Usuarios (+módulos), auditoría, cargas, perfiles, calidad
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

## 6. Roles y módulos por usuario

| Rol | Módulos por defecto |
|---|---|
| `ADMINISTRADOR` | Todos, más el módulo de administración |
| `ANALISTA_SANITARIO` | Panel, Territorio, Establecimientos, Evolución, Procedimientos, Vigilancia IRA y exportar |
| `FUNCIONARIO` (planificación) | Ranking, Establecimientos y exportar |
| `MONITOREO` | Alertas, Evolución, Vigilancia IRA y Mortalidad COVID |
| `ANALISTA_DATOS` | *(rol legado, sin semillas en el sistema nuevo)* |

El control fino es **por usuario**, no solo por rol. Cada módulo
(`tablero`, `territorio`, `ranking`, `establecimiento`, `evolucion`,
`alertas`, `procedimientos`, `vigilancia`, `mortalidad`, `exportar`) se
habilita o deshabilita desde **Administración → Usuarios → Editar**: el
formulario trae las casillas de módulos con los valores por defecto del rol,
y el ajuste se guarda en `dbo.sys_permisos_usuario` (un registro por usuario
y módulo, con el estado de **todo** el catálogo; sin filas para un usuario,
rige el default de su rol). El catálogo vive en `app/modulos.py`.

- El usuario sin acceso a una sección es redirigido a su pantalla inicial
  (Panel para el analista, Ranking para planificación, Alertas para
  monitoreo), no a un 403.
- «Exportar» es transversal: habilita las descargas CSV/XLSX y la API JSON
  (`/api/...`).
- La pantalla de aterrizaje de cada rol se define en `ROL_INICIO` y puede
  caer en un módulo personalizado si el administrador lo decidió así.
- El panel (`/`) solo consulta y dibuja las secciones cuyo módulo tiene el
  usuario: menos consultas y sin datos no autorizados.
- Al crear los usuarios de rol se siembra su catálogo completo de módulos;
  existen los usuarios `analista`, `planificacion` y `monitoreo`
  (contraseñas provisionales documentadas por el operador).
- La creación/edición/eliminación de usuarios queda registrada en
  `sys_auditoria`.

Usuarios funcionales siembreados por rol (idempotente al arrancar):

| Usuario | Contraseña inicial | Rol |
|---|---|---|
| `admin` | `admin123` | Administrador |
| `analista` | `analista123` | Analista sanitario |
| `planificacion` | `planifica123` | Funcionario de planificación |
| `monitoreo` | `monitorea123` | Responsable de monitoreo |

**Cámbialas en el primer acceso** (Mi perfil). La siembra es idempotente:
si el usuario ya existe no se toca.

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

Estrella con tres hechos y una dimensión, más las dos dimensiones
epidemiológicas nuevas:

- `dbo.dim_ipress` — catálogo de establecimientos (591 registros)
- `dbo.dim_fallecidos_covid` — fallecidos por COVID-19 2021-2023
  (124 000 registros): fecha de fallecimiento, edad, sexo, criterio de caso,
  banderas de hospitalización/UCI/vacuna, ubigeo de residencia y CDC
- `dbo.dim_vigilancia_iras` — vigilancia semanal de IRA 2021-2023
  (265 963 registros): IRA no-neumonía, neumonías, hospitalizaciones y
  defunciones (menores de 5 y 60+) por departamento
- `dbo.fact_afiliados_sis` — afiliación por corte (207 739 registros)
- `dbo.fact_atenciones` — atenciones por corte (299 038 registros)
- `dbo.fact_capacidad_diaria` — capacidad y ocupación diaria (510 859 registros)

Las dimensiones epidemiológicas no se unen a `dim_ipress_ext` porque traen
su propia geografía canónica (departamento/provincia/distrito): el filtro
`region` del sistema se aplica directamente sobre `departamento` y el
periodo sobre `fecha_semana` (IRA) o `fecha_fallecimiento` (COVID).

### Páginas y gráficos de las dimensiones nuevas

**Vigilancia IRA** (`/analisis/vigilancia`, módulo `vigilancia`): KPIs de
IRA no-neumonía, neumonías, hospitalizaciones y defunciones; línea con la
evolución mensual; comparativo interanual; barras por departamento; tabla
con letalidad de neumonía por territorio.

**Mortalidad COVID** (`/analisis/mortalidad`, módulo `mortalidad`): KPIs de
fallecidos, edad promedio, vacunados/hospitalizados/UCI; línea mensual de
fallecidos con corte por vacunación; barras por criterio de caso
(virologico, SINADEF, ...); barras de sexo por grupo de edad; detalle por
departamento y comparativo anual.

Además el **panel** muestra mini-panoramas de IRA y COVID para los usuarios
con esos módulos habilitados.

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
GET /api/vigilancia/ira          # exige el modulo vigilancia
GET /api/mortalidad/covid        # exige el modulo mortalidad
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
