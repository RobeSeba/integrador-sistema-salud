"""Modelos de administracion: usuarios, roles, cargas y reglas de prioridad."""

import hashlib
from datetime import datetime

from werkzeug.security import check_password_hash, generate_password_hash

from .base_model import BaseModel, normalizar_filas


class UsuarioInvalido(ValueError):
    """Credenciales o datos de usuario invalidos."""


class PerfilNoEncontrado(ValueError):
    """El perfil de prioridad solicitado no existe."""


class AdminModel(BaseModel):
    # ==================================================================
    # Usuarios
    # ==================================================================
    @staticmethod
    def hash_password(password):
        return generate_password_hash(password)

    @classmethod
    def autenticar(cls, usuario, password):
        """Verifica credenciales. Devuelve la fila del usuario o None."""
        if not usuario or not password:
            return None
        fila = cls.consultar_uno(
            "SELECT * FROM dbo.sys_usuarios WHERE usuario = ? AND activo = 1",
            [str(usuario).strip()],
        )
        if not fila:
            return None
        if not check_password_hash(fila["password_hash"], password):
            return None
        return fila

    @classmethod
    def registrar_acceso(cls, id_usuario):
        cls.ejecutar(
            "UPDATE dbo.sys_usuarios SET ultimo_acceso = ? WHERE id_usuario = ?",
            [datetime.now(), id_usuario],
        )

    @classmethod
    def listar_usuarios(cls, solo_activos=False):
        sql = """
            SELECT id_usuario, usuario, nombre_completo, rol, email, cargo,
                   activo, fecha_creacion, ultimo_acceso
            FROM dbo.sys_usuarios
        """
        if solo_activos:
            sql += " WHERE activo = 1"
        sql += " ORDER BY activo DESC, nombre_completo"
        return normalizar_filas(cls.consultar(sql))

    @classmethod
    def obtener_usuario(cls, id_usuario):
        return cls.consultar_uno(
            "SELECT id_usuario, usuario, nombre_completo, rol, email, cargo, activo "
            "FROM dbo.sys_usuarios WHERE id_usuario = ?",
            [id_usuario],
        )

    @classmethod
    def crear_usuario(cls, usuario, password, nombre_completo, rol,
                      email=None, cargo=None, activo=True):
        usuario = str(usuario or "").strip()
        nombre_completo = str(nombre_completo or "").strip()
        if not usuario:
            raise UsuarioInvalido("El nombre de usuario es obligatorio.")
        if not nombre_completo:
            raise UsuarioInvalido("El nombre completo es obligatorio.")
        if len(password or "") < 6:
            raise UsuarioInvalido("La contrasena debe tener al menos 6 caracteres.")
        if cls.consultar_uno("SELECT 1 AS x FROM dbo.sys_usuarios WHERE usuario = ?", [usuario]):
            raise UsuarioInvalido(f"El usuario '{usuario}' ya existe.")
        sql = """
            INSERT INTO dbo.sys_usuarios
                (usuario, password_hash, nombre_completo, rol, email, cargo, activo)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """
        cls.ejecutar(sql, [
            usuario, cls.hash_password(password), nombre_completo, rol,
            email or None, cargo or None, 1 if activo else 0,
        ])
        return cls.consultar_uno(
            "SELECT id_usuario, usuario, nombre_completo, rol, email, cargo, activo "
            "FROM dbo.sys_usuarios WHERE usuario = ?", [usuario]
        )

    @classmethod
    def _verificar_admin_restante(cls, id_usuario, rol_nuevo, activo_nuevo):
        """Impide que una edicion deje el sistema sin ningun administrador.

        La cuenta se pierde como administrador si se desactiva o si se le
        cambia el rol, por eso la comprobacion no puede mirar solo `activo`:
        degradar de ADMINISTRADOR a MONITOREO sin desactivar la cuenta tambien
        dejaria el sistema sin administracion.
        """
        actual = cls.obtener_usuario(id_usuario)
        if not actual:
            return
        sigue_admin = (
            str(actual["rol"]).upper() == "ADMINISTRADOR"
            and int(actual["activo"] or 0) == 1
        )
        sera_admin = (
            str(rol_nuevo).upper() == "ADMINISTRADOR" and bool(activo_nuevo)
        )
        if not sigue_admin or sera_admin:
            return
        otros = cls.consultar_valor(
            "SELECT COUNT(*) FROM dbo.sys_usuarios "
            "WHERE rol = 'ADMINISTRADOR' AND activo = 1 AND id_usuario <> ?",
            [id_usuario], default=0,
        )
        if int(otros or 0) == 0:
            raise UsuarioInvalido(
                "Debe existir al menos un administrador activo. "
                "Active o cree otro administrador antes de quitar este rol."
            )

    @classmethod
    def actualizar_usuario(cls, id_usuario, nombre_completo, rol,
                           email=None, cargo=None, activo=True):
        cls._verificar_admin_restante(id_usuario, rol, activo)
        cls.ejecutar(
            """
            UPDATE dbo.sys_usuarios
               SET nombre_completo = ?, rol = ?, email = ?, cargo = ?, activo = ?
             WHERE id_usuario = ?
            """,
            [nombre_completo, rol, email or None, cargo or None,
             1 if activo else 0, id_usuario],
        )
        return cls.obtener_usuario(id_usuario)

    @classmethod
    def actualizar_datos_propios(cls, id_usuario, nombre_completo,
                                 email=None, cargo=None):
        """Edicion de los datos propios: no toca rol ni estado de la cuenta."""
        cls.ejecutar(
            "UPDATE dbo.sys_usuarios SET nombre_completo = ?, email = ?, cargo = ? "
            "WHERE id_usuario = ?",
            [nombre_completo, email or None, cargo or None, id_usuario],
        )
        return cls.obtener_usuario(id_usuario)

    @classmethod
    def verificar_password(cls, id_usuario, password):
        """Comprueba la contrasena actual del usuario indicado."""
        fila = cls.consultar_uno(
            "SELECT password_hash FROM dbo.sys_usuarios WHERE id_usuario = ?",
            [id_usuario],
        )
        if not fila or not password:
            return False
        return bool(check_password_hash(fila["password_hash"], password))

    @classmethod
    def cambiar_password(cls, id_usuario, password_nuevo):
        if len(password_nuevo or "") < 6:
            raise UsuarioInvalido("La contrasena debe tener al menos 6 caracteres.")
        cls.ejecutar(
            "UPDATE dbo.sys_usuarios SET password_hash = ? WHERE id_usuario = ?",
            [cls.hash_password(password_nuevo), id_usuario],
        )

    @classmethod
    def eliminar_usuario(cls, id_usuario, id_usuario_actual):
        if int(id_usuario) == int(id_usuario_actual):
            raise UsuarioInvalido("No puede desactivar su propia cuenta.")
        actual = cls.obtener_usuario(id_usuario)
        if actual and str(actual["rol"]).upper() == "ADMINISTRADOR":
            otros = cls.consultar_valor(
                "SELECT COUNT(*) FROM dbo.sys_usuarios "
                "WHERE rol = 'ADMINISTRADOR' AND activo = 1 AND id_usuario <> ?",
                [id_usuario], default=0,
            )
            if int(otros or 0) == 0:
                raise UsuarioInvalido(
                    "Debe existir al menos un administrador activo. "
                    "Active otro administrador antes de desactivar este."
                )
        cls.ejecutar("UPDATE dbo.sys_usuarios SET activo = 0 WHERE id_usuario = ?", [id_usuario])

    @classmethod
    def total_administradores_activos(cls):
        return cls.consultar_valor(
            "SELECT COUNT(*) FROM dbo.sys_usuarios "
            "WHERE rol = 'ADMINISTRADOR' AND activo = 1",
            default=0,
        )


class AuditoriaModel(BaseModel):
    """Registro de eventos relevantes del sistema."""

    @classmethod
    def registrar(cls, modulo, accion, detalle="", id_usuario=None, usuario=None):
        try:
            cls.ejecutar(
                "INSERT INTO dbo.sys_auditoria "
                "(id_usuario, usuario, modulo, accion, detalle) VALUES (?, ?, ?, ?, ?)",
                [id_usuario, usuario, modulo, accion, (detalle or "")[:1000]],
            )
        except Exception:
            # La auditoria nunca debe romper la operacion principal.
            pass

    @classmethod
    def listar(cls, limite=100, modulo=None):
        sql = """
            SELECT TOP (?) a.id_auditoria, a.fecha_evento, a.usuario,
                   a.id_usuario, ISNULL(u.nombre_completo, a.usuario) AS usuario_nombre,
                   a.modulo, a.accion, a.detalle
            FROM dbo.sys_auditoria a
            LEFT JOIN dbo.sys_usuarios u ON u.id_usuario = a.id_usuario
        """
        params = [limite]
        if modulo:
            sql += " WHERE a.modulo = ?"
            params.append(modulo)
        sql += " ORDER BY a.fecha_evento DESC, a.id_auditoria DESC"
        return normalizar_filas(cls.consultar(sql, params))


class CargaModel(BaseModel):
    """Registro historico de cargas de archivos (historia del administrador)."""

    # Se usan las claves en mayusculas porque son los nombres reales de las
    # tablas; la comparacion se normaliza para no depender de como lo escriba
    # el operador (la plantilla y las cargas antigas pueden venir en minusculas).
    TABLAS_PERMITIDAS = {
        "FACT_AFILIADOS_SIS": "Afiliados SIS",
        "FACT_ATENCIONES": "Atenciones",
        "FACT_CAPACIDAD_DIARIA": "Capacidad diaria",
    }

    @classmethod
    def normalizar_tabla_destino(cls, tabla_destino):
        """Devuelve la clave canonica o None si no es una tabla permitida."""
        clave = str(tabla_destino or "").strip().upper()
        return clave if clave in cls.TABLAS_PERMITIDAS else None

    @staticmethod
    def hash_archivo(ruta):
        h = hashlib.sha256()
        with open(ruta, "rb") as fh:
            for bloque in iter(lambda: fh.read(65536), b""):
                h.update(bloque)
        return h.hexdigest()

    @classmethod
    def listar(cls, limite=100, estado=None, tabla=None):
        sql = """
            SELECT TOP (?) c.id_carga, c.nombre_archivo, c.fuente, c.tabla_destino,
                   c.fecha_dato, c.fecha_inicio_periodo, c.fecha_fin_periodo,
                   c.fecha_carga, c.filas_insertadas, c.filas_rechazadas,
                   c.modo_carga, c.estado, c.mensaje, c.id_usuario,
                   ISNULL(u.nombre_completo, u.usuario) AS usuario_nombre
            FROM dbo.sys_cargas c
            LEFT JOIN dbo.sys_usuarios u ON u.id_usuario = c.id_usuario
        """
        params = [limite]
        condiciones = []
        if estado:
            condiciones.append("c.estado = ?")
            params.append(estado)
        if tabla:
            condiciones.append("c.tabla_destino = ?")
            params.append(tabla)
        if condiciones:
            sql += " WHERE " + " AND ".join(condiciones)
        sql += " ORDER BY c.fecha_carga DESC, c.id_carga DESC"
        return normalizar_filas(cls.consultar(sql, params))

    @classmethod
    def obtener(cls, id_carga):
        return cls.consultar_uno(
            "SELECT * FROM dbo.sys_cargas WHERE id_carga = ?", [id_carga]
        )

    @classmethod
    def registrar(cls, nombre_archivo, fuente, tabla_destino, fecha_dato,
                  ruta_archivo=None, id_usuario=None, estado="PENDIENTE",
                  modo_carga="INCREMENTAL", filas_insertadas=0, filas_rechazadas=0,
                  mensaje="", hash_archivo=None,
                  fecha_inicio_periodo=None, fecha_fin_periodo=None):
        tabla_destino_original = tabla_destino
        # Se normaliza antes de validar: asi "fact_afiliados_sis" se acepta
        # igual que "FACT_AFILIADOS_SIS", tal como se documenta.
        tabla_destino = cls.normalizar_tabla_destino(tabla_destino)
        if tabla_destino is None:
            raise ValueError(
                f"Tabla destino no permitida: {tabla_destino_original}. "
                f"Valores admitidos: {', '.join(sorted(cls.TABLAS_PERMITIDAS))}."
            )
        sql = """
            INSERT INTO dbo.sys_cargas
                (nombre_archivo, ruta_archivo, fuente, tabla_destino, fecha_dato,
                 fecha_inicio_periodo, fecha_fin_periodo, filas_insertadas,
                 filas_rechazadas, modo_carga, estado, mensaje, id_usuario, hash_archivo)
            OUTPUT INSERTED.id_carga
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        return cls.consultar_valor(sql, [
            nombre_archivo, ruta_archivo, fuente, tabla_destino, fecha_dato,
            fecha_inicio_periodo, fecha_fin_periodo, filas_insertadas,
            filas_rechazadas, modo_carga, estado, (mensaje or "")[:1000],
            id_usuario, hash_archivo,
        ], commit=True)

    @classmethod
    def actualizar_resultado(cls, id_carga, estado, filas_insertadas=None,
                             filas_rechazadas=None, mensaje=None):
        sql = "UPDATE dbo.sys_cargas SET estado = ?"
        params = [estado]
        if filas_insertadas is not None:
            sql += ", filas_insertadas = ?"
            params.append(filas_insertadas)
        if filas_rechazadas is not None:
            sql += ", filas_rechazadas = ?"
            params.append(filas_rechazadas)
        if mensaje is not None:
            sql += ", mensaje = ?"
            params.append(mensaje[:1000])
        sql += " WHERE id_carga = ?"
        params.append(id_carga)
        cls.ejecutar(sql, params)

    @classmethod
    def eliminar(cls, id_carga):
        cls.ejecutar("DELETE FROM dbo.sys_cargas WHERE id_carga = ?", [id_carga])

    @classmethod
    def resumen(cls):
        """Indicadores del historial de cargas para el panel de administracion."""
        sql = """
            SELECT COUNT(*) AS total_cargas,
                   -- ISNULL: sobre una tabla vacia SUM devuelve NULL y el panel
                   -- mostraria celdas vacias en lugar de cero.
                   ISNULL(SUM(CASE WHEN estado = 'APLICADO' THEN 1 ELSE 0 END), 0) AS aplicadas,
                   ISNULL(SUM(CASE WHEN estado = 'ERROR' THEN 1 ELSE 0 END), 0) AS con_error,
                   ISNULL(SUM(CASE WHEN estado = 'VALIDADO' THEN 1 ELSE 0 END), 0) AS validadas,
                   ISNULL(SUM(filas_insertadas), 0) AS filas_totales,
                   MAX(fecha_carga) AS ultima_carga
            FROM dbo.sys_cargas
        """
        return cls.consultar_uno(sql) or {}

    @classmethod
    def por_tabla(cls):
        sql = """
            SELECT tabla_destino, COUNT(*) AS cargas,
                   ISNULL(SUM(filas_insertadas), 0) AS filas,
                   MAX(fecha_carga) AS ultima_carga
            FROM dbo.sys_cargas
            WHERE estado = 'APLICADO'
            GROUP BY tabla_destino
            ORDER BY tabla_destino
        """
        return normalizar_filas(cls.consultar(sql))


class PrioridadModel(BaseModel):
    """Perfiles de priorizacion y sus reglas (ponderadores configurables)."""

    # ------------------------------------------------------------------
    # Perfiles
    # ------------------------------------------------------------------
    @classmethod
    def listar_perfiles(cls, solo_activos=False):
        sql = """
            SELECT p.id_perfil, p.codigo, p.nombre, p.descripcion, p.activo, p.es_base,
                   p.umbral_critico_pct, p.umbral_alto_pct, p.umbral_medio_pct,
                   p.fecha_creacion, p.fecha_actualizacion,
                   (SELECT COUNT(*) FROM dbo.sys_reglas_prioridad r
                     WHERE r.id_perfil = p.id_perfil AND r.activo = 1) AS reglas_activas,
                   (SELECT ISNULL(SUM(r.peso), 0) FROM dbo.sys_reglas_prioridad r
                     WHERE r.id_perfil = p.id_perfil AND r.activo = 1) AS peso_total
            FROM dbo.sys_perfiles_prioridad p
        """
        if solo_activos:
            sql += " WHERE p.activo = 1"
        sql += " ORDER BY p.es_base DESC, p.nombre"
        return normalizar_filas(cls.consultar(sql))

    @classmethod
    def obtener_perfil(cls, id_perfil):
        """Acepta el id numerico o el codigo del perfil ('BRECHA_CAPACIDAD')."""
        perfil = None
        try:
            perfil = cls.consultar_uno(
                "SELECT * FROM dbo.sys_perfiles_prioridad WHERE id_perfil = ?",
                [int(id_perfil)],
            )
        except (TypeError, ValueError):
            perfil = None
        if perfil is None and id_perfil:
            perfil = cls.obtener_perfil_por_codigo(str(id_perfil).strip().upper())
        if perfil is None:
            raise PerfilNoEncontrado(
                f"No existe el perfil de prioridad '{id_perfil}'."
            )
        return perfil

    @classmethod
    def obtener_perfil_por_codigo(cls, codigo):
        return cls.consultar_uno(
            "SELECT * FROM dbo.sys_perfiles_prioridad WHERE codigo = ?", [codigo]
        )

    @classmethod
    def crear_perfil(cls, codigo, nombre, descripcion=None,
                     umbral_critico=75.0, umbral_alto=50.0, umbral_medio=25.0):
        cls.ejecutar(
            """
            INSERT INTO dbo.sys_perfiles_prioridad
                (codigo, nombre, descripcion, umbral_critico_pct, umbral_alto_pct, umbral_medio_pct)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            [str(codigo).strip().upper(), nombre, descripcion,
             umbral_critico, umbral_alto, umbral_medio],
        )
        return cls.obtener_perfil_por_codigo(codigo)

    @classmethod
    def actualizar_perfil(cls, id_perfil, nombre, descripcion, activo,
                          umbral_critico, umbral_alto, umbral_medio):
        cls.ejecutar(
            """
            UPDATE dbo.sys_perfiles_prioridad
               SET nombre = ?, descripcion = ?, activo = ?,
                   umbral_critico_pct = ?, umbral_alto_pct = ?, umbral_medio_pct = ?,
                   fecha_actualizacion = ?
             WHERE id_perfil = ?
            """,
            [nombre, descripcion, 1 if activo else 0,
             umbral_critico, umbral_alto, umbral_medio,
             datetime.now(), id_perfil],
        )
        return cls.obtener_perfil(id_perfil)

    @classmethod
    def eliminar_perfil(cls, id_perfil):
        perfil = cls.obtener_perfil(id_perfil)
        if perfil and perfil["es_base"]:
            raise ValueError("Los perfiles base del sistema no se pueden eliminar.")
        cls.ejecutar("DELETE FROM dbo.sys_perfiles_prioridad WHERE id_perfil = ?", [id_perfil])

    # ------------------------------------------------------------------
    # Reglas
    # ------------------------------------------------------------------
    @classmethod
    def listar_reglas(cls, id_perfil):
        sql = """
            SELECT id_regla, id_perfil, codigo, nombre, descripcion, peso,
                   umbral_minimo, umbral_maximo, direccion, obligatorio, activo, orden
            FROM dbo.sys_reglas_prioridad
            WHERE id_perfil = ?
            ORDER BY activo DESC, orden, id_regla
        """
        return normalizar_filas(cls.consultar(sql, [id_perfil]))

    @classmethod
    def regla_existe(cls, id_perfil, codigo):
        """True si el perfil ya tiene una regla para ese indicador."""
        return cls.consultar_uno(
            "SELECT 1 AS x FROM dbo.sys_reglas_prioridad "
            "WHERE id_perfil = ? AND codigo = ?",
            [id_perfil, str(codigo or "").strip().lower()],
        ) is not None

    @classmethod
    def actualizar_regla(cls, id_regla, peso, umbral_minimo, umbral_maximo,
                         direccion, obligatorio, activo):
        cls.ejecutar(
            """
            UPDATE dbo.sys_reglas_prioridad
               SET peso = ?, umbral_minimo = ?, umbral_maximo = ?,
                   direccion = ?, obligatorio = ?, activo = ?
             WHERE id_regla = ?
            """,
            [peso, umbral_minimo, umbral_maximo, direccion,
             1 if obligatorio else 0, 1 if activo else 0, id_regla],
        )

    @classmethod
    def crear_regla(cls, id_perfil, codigo, nombre, descripcion, peso,
                    umbral_minimo=None, umbral_maximo=None,
                    direccion="MAYOR", obligatorio=False, activo=True):
        cls.ejecutar(
            """
            INSERT INTO dbo.sys_reglas_prioridad
                (id_perfil, codigo, nombre, descripcion, peso, umbral_minimo,
                 umbral_maximo, direccion, obligatorio, activo, orden)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    (SELECT ISNULL(MAX(orden), 0) + 1 FROM dbo.sys_reglas_prioridad
                      WHERE id_perfil = ?))
            """,
            [id_perfil, codigo, nombre, descripcion, peso,
             umbral_minimo, umbral_maximo, direccion,
             1 if obligatorio else 0, 1 if activo else 0, id_perfil],
        )

    @classmethod
    def eliminar_regla(cls, id_regla):
        cls.ejecutar("DELETE FROM dbo.sys_reglas_prioridad WHERE id_regla = ?", [id_regla])

    @classmethod
    def duplicar_perfil(cls, id_perfil_origen, codigo, nombre):
        """Crea una copia de un perfil con todas sus reglas."""
        origen = cls.obtener_perfil(id_perfil_origen)
        if not origen:
            raise ValueError("Perfil de origen no encontrado.")
        nuevo = cls.crear_perfil(
            codigo, nombre,
            f"Duplicado de '{origen['nombre']}'",
            origen["umbral_critico_pct"], origen["umbral_alto_pct"],
            origen["umbral_medio_pct"],
        )
        for regla in cls.listar_reglas(id_perfil_origen):
            cls.crear_regla(
                nuevo["id_perfil"], regla["codigo"], regla["nombre"],
                regla["descripcion"], regla["peso"], regla["umbral_minimo"],
                regla["umbral_maximo"], regla["direccion"],
                regla["obligatorio"], regla["activo"],
            )
        return nuevo