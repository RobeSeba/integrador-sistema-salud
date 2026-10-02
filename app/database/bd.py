"""Capa de conexion a la base de datos (pyodbc + SQL Server).

Este modulo reemplaza al archivo `bd.py` de la raiz: conserva la cadena de
conexion probada y agrega un pool de conexiones seguro para uso concurrente
bajo el servidor de desarrollo de Flask.
"""

import queue
import threading
from contextlib import contextmanager

import pyodbc


class ErrorBaseDatos(RuntimeError):
    """Error envuelto de la capa de datos."""


class ConnectionPool:
    """Pool simple de conexiones pyodbc respaldado por una cola."""

    def __init__(self, connection_string, size=8, timeout=30):
        self._connection_string = connection_string
        self._size = max(1, int(size))
        self._timeout = timeout
        self._pool = queue.Queue(maxsize=self._size)
        self._lock = threading.Lock()
        self._creadas = 0
        self._cerradas = 0

    # -- ciclo de vida -----------------------------------------------------
    def _conectar(self):
        return pyodbc.connect(
            self._connection_string,
            timeout=self._timeout,
            autocommit=False,
        )

    def _adquirir(self):
        try:
            conn = self._pool.get_nowait()
        except queue.Empty:
            with self._lock:
                if self._creadas < self._size:
                    self._creadas += 1
                    try:
                        return self._conectar()
                    except Exception:
                        self._creadas -= 1
                        raise
            conn = self._pool.get(timeout=self._timeout)
        return self._recuperar(conn)

    def _recuperar(self, conn):
        """Devuelve al pool una conexion sana; descarta las rotas."""
        try:
            if conn is None or getattr(conn, "closed", False):
                raise ErrorBaseDatos("Conexion cerrada unexpectedly.")
            cursor = conn.cursor()
            if cursor is not None:
                cursor.close()
            conn.rollback()
            return conn
        except Exception:
            self._descartar(conn)
            raise ErrorBaseDatos("Conexion perdida, se descarto del pool.")

    def _descartar(self, conn):
        try:
            if conn is not None:
                conn.close()
        except Exception:
            pass
        with self._lock:
            self._creadas = max(0, self._creadas - 1)

    def _liberar(self, conn):
        try:
            self._pool.put_nowait(conn)
        except queue.Full:
            self._descartar(conn)

    @contextmanager
    def conexion(self):
        """Context manager: entrega una conexion y la devuelve al pool."""
        conn = self._adquirir()
        try:
            yield conn
        except Exception:
            self._descartar(conn)
            raise
        else:
            self._liberar(conn)

    def cerrar(self):
        while True:
            try:
                conn = self._pool.get_nowait()
            except queue.Empty:
                break
            self._descartar(conn)

    @property
    def estadisticas(self):
        return {
            "conexiones_vivas": self._creadas,
            "conexiones_libres": self._pool.qsize(),
            "tamano_pool": self._size,
        }


# Pool global compartido por la aplicacion
_pool = None
_pool_lock = threading.Lock()
_ultima_conexion_string = None


def init_pool(config):
    """Crea (o recrea) el pool global a partir de la configuracion."""
    global _pool, _ultima_conexion_string
    with _pool_lock:
        connection_string = config.connection_string()
        if _pool is not None and connection_string == _ultima_conexion_string:
            return _pool
        if _pool is not None:
            _pool.cerrar()
        _pool = ConnectionPool(
            connection_string,
            size=config.DB_POOL_SIZE,
            timeout=config.DB_TIMEOUT,
        )
        _ultima_conexion_string = connection_string
        return _pool


def get_pool() -> ConnectionPool:
    if _pool is None:
        raise ErrorBaseDatos(
            "El pool de conexiones no esta inicializado. "
            "Llame a init_pool(config) al crear la aplicacion."
        )
    return _pool


@contextmanager
def conexion():
    """Context manager principal para obtener una conexion del pool."""
    with get_pool().conexion() as conn:
        yield conn


def probar_conexion(config=None) -> dict:
    """Verifica la conectividad. Util para la pantalla de diagnostico."""
    if config is not None:
        init_pool(config)
    with conexion() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT DB_NAME() AS bd, @@VERSION AS version")
        fila = cursor.fetchone()
        cursor.close()
        version = fila[1] if fila[1] else ""
        linea = version.splitlines()[0] if version else ""
        return {"bd": fila[0], "servidor": linea, "ok": True}


def ruta_sql(nombre_archivo=None):
    """Resuelve la ruta de la carpeta de migraciones o de un script .sql."""
    from pathlib import Path

    carpeta = Path(__file__).resolve().parent / "migrations"
    if not nombre_archivo:
        return carpeta
    return carpeta / nombre_archivo