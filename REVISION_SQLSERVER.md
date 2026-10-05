# Revisión de la conexión a SQL Server Express

El error que impide arrancar es el rechazo del inicio de sesión `sa` (18456).
El aviso `_queue.Empty` aparece porque el pool está vacío y el programa intenta
abrir su primera conexión; ese caso ya está controlado por `bd.py`.

## Lo que encontré en este ZIP

1. `config.py` apuntaba por defecto a `localhost`, sin el nombre de instancia.
   Tu instancia de Express es `.\SQLEXPRESS`. Se corrigió el valor por defecto.
   Una variable `SIBS_DB_SERVER` existente tiene prioridad sobre ese valor.
2. La cadena agregaba `Connection Timeout=30`. No es una palabra clave del
   driver ODBC 17 y es una causa identificada del aviso de atributo inválido.
   Se eliminó; `bd.py` ya pasa el tiempo mediante `pyodbc.connect(timeout=...)`.
   Este cambio no corrige por sí mismo una contraseña rechazada por SQL Server.
3. Este archivo usa Windows por defecto (`SIBS_DB_TRUSTED=yes`); no contiene una
   contraseña de `sa`. Usuario y contraseña se leen de `SIBS_DB_UID` y
   `SIBS_DB_PWD`. Si el programa intenta entrar como `sa`, puede haber variables
   de entorno activas, una modificación local o una copia distinta del archivo.
4. No hay `.env` ni un cargador de ese archivo. `python run.py` lee las variables
   del proceso. Cambiar un `.env` por sí solo no cambia esta configuración.
5. Las migraciones crean tablas de administración y objetos auxiliares, pero
   no crean `dim_ipress`, `fact_afiliados_sis`, `fact_atenciones` ni
   `fact_capacidad_diaria`. Además, no incluyen tus tres procedimientos de salud.
   Se espera que esos objetos existan en `SaludBrechasDB`.
6. Las migraciones necesitan más columnas que los tres procedimientos originales,
   entre ellas geografía en los hechos y `nombre_establecimiento`, `categoria`
   y `nivel` en `dim_ipress`. El script anterior de tablas mínimas cubría los
   procedimientos; la aplicación completa necesita el esquema original de salud.

## Archivos corregidos o agregados

- `config.py`: instancia local correcta, retiro del atributo no compatible,
  comprobación de credenciales cuando se elige autenticación SQL y escape de
  valores ODBC para contraseñas con separadores o llaves.
- `diagnostico_bd.py`: prueba independiente de Flask, sin migraciones ni
  escrituras. Muestra qué configuración está usando Python y comprueba los
  metadatos mínimos del esquema.
- `README.md`: configuración e instrucciones ajustadas a SQL Server Express.

## Pasos para tu equipo

En PowerShell, dentro de tu carpeta del proyecto, reemplaza `config.py` y agrega
`diagnostico_bd.py` desde este ZIP. Luego ejecuta:

```powershell
$env:SIBS_DB_SERVER = '.\SQLEXPRESS'
$env:SIBS_DB_NAME = 'SaludBrechasDB'
$env:SIBS_DB_TRUSTED = 'yes'
python diagnostico_bd.py
```

Esto usa la cuenta de Windows que ejecuta Python, como en tu conexión de SSMS.
Una contraseña de `sa` guardada en el entorno no se utiliza al elegir Windows.
Si SSMS se abre con otro usuario de Windows, Python debe tener acceso con su
propia cuenta a esa instancia y a `SaludBrechasDB`.

Si la prueba confirma la conexión y las columnas mínimas, ejecuta en la misma
terminal:

```powershell
python run.py
```

Si aparece `ESQUEMA INCOMPLETO`, verifica primero que estés apuntando a la base
correcta. Después usa el script original o respaldo de la base de salud.
Crear únicamente una base vacía o tablas con columnas mínimas deja pendientes
los campos que requieren las consultas y los datos de los indicadores.

## Si necesitas usar el usuario sa

Comprueba en SSMS que puedes conectar a `.\SQLEXPRESS` con **Autenticación de
SQL Server**, usuario `sa` y la misma contraseña. Si SSMS también rechaza el
inicio de sesión, revisa en esa instancia el modo mixto, el estado habilitado de
`sa`, la contraseña y el reinicio del servicio tras cambiar el modo.

Para poner la contraseña en el entorno sin escribirla como texto en el historial
de PowerShell:

```powershell
$env:SIBS_DB_SERVER = '.\SQLEXPRESS'
$env:SIBS_DB_NAME = 'SaludBrechasDB'
$env:SIBS_DB_TRUSTED = 'no'
$env:SIBS_DB_UID = 'sa'
$credencial = Get-Credential -UserName 'sa' -Message 'Credenciales de SQL Server'
$env:SIBS_DB_PWD = $credencial.GetNetworkCredential().Password
Remove-Variable credencial
python diagnostico_bd.py
```

Si persiste 18456, ejecuta esto en SSMS conectado mediante Windows a la misma
instancia. El último registro `Reason:` permite distinguir el motivo:

```sql
SELECT @@SERVERNAME AS Servidor,
       SERVERPROPERTY('IsIntegratedSecurityOnly') AS SoloWindows;
SELECT name, is_disabled FROM sys.sql_logins WHERE name = N'sa';
EXEC master.sys.sp_readerrorlog 0, 1, N'Login failed for user', N'sa';
```

`SoloWindows=0` indica modo mixto; `is_disabled=0` indica un login habilitado.
No compartas la contraseña ni una cadena de conexión completa.

## Alcance de la validación

Se revisaron la configuración, el pool, el arranque de Flask, las migraciones y
las dependencias del esquema. Se comprobaron la sintaxis Python y los casos de
construcción de conexión y diagnóstico con pruebas locales. No se pudo probar
una conexión real contra el SQL Server instalado en tu computadora. La prueba
de columnas es mínima: no valida los tipos, todos los indicadores ni los datos.

Referencias técnicas: [palabras clave ODBC de Microsoft](https://learn.microsoft.com/en-us/sql/connect/odbc/dsn-connection-string-attribute?view=sql-server-ver17),
[timeout de pyodbc](https://github.com/mkleehammer/pyodbc/wiki/The-pyodbc-Module#timeout)
y [error 18456](https://learn.microsoft.com/en-us/sql/relational-databases/errors-events/mssqlserver-18456-database-engine-error?view=sql-server-ver17).
