"""Motor de ranking por reglas configurables de prioridad.

Este modulo implementa el requerimiento indispensable del sistema: "Generar
ranking de establecimientos y territorios segun reglas configurables de
prioridad".

El algoritmo es el siguiente:

1. Se obtiene la tabla base de indicadores por establecimiento (o agregado por
   territorio) desde IndicadoresModel.
2. Para cada regla activa del perfil se toma el valor del indicador con el
   mismo `codigo`.
3. El valor se recorta a la ventana de normalizacion [umbral_minimo,
   umbral_maximo] y se normaliza a [0, 1] (min-max sobre el conjunto de la
   consulta). Si la direccion es MENOR se invierte: 1 = peor.
4. Se multiplica por el peso de la regla y se suma: ese es el puntaje.
5. El puntaje se relativiza al maximo alcanzado y se clasifica en CRITICA,
   ALTA, MEDIA o BAJA segun los umbrales del perfil.

Las reglas `obligatorio` con indicador nulo se consideran no evaluables: si el
perfil tiene alguna obligatoria y el registro no las cumple, queda excluido
del ranking (y se informa la razon).
"""

from .admin_model import PrioridadModel
from .indicadores_model import IndicadoresModel
from .base_model import BaseModel, normalizar_filas

CATEGORIAS_PRIORIDAD = {
    "CRITICA": {"etiqueta": "Critica", "color": "#b91c1c", "orden": 4},
    "ALTA": {"etiqueta": "Alta", "color": "#ea580c", "orden": 3},
    "MEDIA": {"etiqueta": "Media", "color": "#ca8a04", "orden": 2},
    "BAJA": {"etiqueta": "Baja", "color": "#16a34a", "orden": 1},
    "NO_EVALUABLE": {"etiqueta": "No evaluable", "color": "#64748b", "orden": 0},
}

# Indicadores disponibles para construir reglas nuevas desde la interfaz.
CATALOGO_INDICADORES = {
    "ratio_afiliados_cama": "Afiliados por cama operativa",
    "tasa_ocupacion": "Tasa de ocupacion (%)",
    "pico_ocupacion": "Pico de ocupacion (%)",
    "dias_sobre_umbral": "Dias sobre umbral de ocupacion",
    "tasa_inoperatividad": "Tasa de inoperatividad de recursos (%)",
    "presion_atencion": "Atenciones por 1000 afiliados",
    "presion_emergencia": "Atenciones de urgencia por cama de emergencia",
    "porc_rural": "Poblacion rural (%)",
    "porc_vulnerable": "Poblacion vulnerable (%)",
    "cobertura_uci": "Cobertura de UCI (1/0)",
    "dias_sin_reporte": "Dias sin reporte de capacidad",
    "tasa_uso_ventiladores": "Uso de ventiladores (%)",
    "recursos_operativos": "Recursos operativos (promedio)",
    "recursos_disponibles": "Recursos disponibles (promedio)",
    "total_atenciones": "Atenciones del periodo",
    "afiliados": "Afiliados (foto de corte)",
    "dias_alerta_roja": "Dias en alerta roja",
    "dias_alerta_amarilla": "Dias en alerta amarilla",
}

# Los perfiles sembrados usan nombres del dominio ("presion de afiliados",
# "poblacion rural") que no coinciden con los alias que exponen las consultas.
# Sin esta tabla de equivalencias esas reglas se descartarian en silencio y sus
# pesos no sumarian: por eso se resuelven aqui en lugar de forzar un unico
# nombre en la base de datos.
ALIAS_INDICADORES = {
    "presion_afiliados": "ratio_afiliados_cama",
    "afiliados_por_cama": "ratio_afiliados_cama",
    "poblacion_rural": "porc_rural",
    "poblacion_vulnerable": "porc_vulnerable",
    "ocupacion": "tasa_ocupacion",
    "inoperatividad": "tasa_inoperatividad",
}


def resolver_indicador(codigo):
    """Devuelve el alias canonico del indicador o None si la regla no tiene soporte.

    Se expone publicamente porque el administrador tambien necesita resolverlo:
    al validar una regla nueva debe considerar validos tanto los codigos del
    catalogo como los nombres del dominio con los que estan sembrados los
    perfiles, que de otro modo se rechazarian como inexistentes.
    """
    codigo = (codigo or "").strip().lower()
    if codigo in CATALOGO_INDICADORES:
        return codigo
    return ALIAS_INDICADORES.get(codigo)


def nombre_indicador(codigo):
    """Etiqueta legible de un indicador, tolerando los codigos con alias."""
    canonico = resolver_indicador(codigo)
    if canonico and canonico in CATALOGO_INDICADORES:
        return CATALOGO_INDICADORES[canonico]
    return (codigo or "").replace("_", " ")


def codigos_equivalentes(codigo):
    """Todos los nombres que apuntan al mismo indicador que `codigo`.

    Sirve para detectar duplicados reales: si el perfil ya tiene la regla
    "presion_afiliados" y el administrador elige "ratio_afiliados_cama" en el
    formulario, ambas se resuelven al mismo indicador y sumarian su peso dos
    veces al calcular el ranking.
    """
    canonico = resolver_indicador(codigo)
    if not canonico:
        return []
    equivalentes = {codigo, canonico}
    for alias, destino in ALIAS_INDICADORES.items():
        if destino == canonico:
            equivalentes.add(alias)
    return sorted(equivalentes)


class RankingError(ValueError):
    """Reglas de priorizacion invalidas."""


class RankingModel:
    # ------------------------------------------------------------------
    # Perfiles
    # ------------------------------------------------------------------
    @staticmethod
    def listar_perfiles(solo_activos=True):
        return PrioridadModel.listar_perfiles(solo_activos=solo_activos)

    @staticmethod
    def reglas_de(id_perfil):
        return [r for r in PrioridadModel.listar_reglas(id_perfil) if r["activo"]]

    # ------------------------------------------------------------------
    # Normalizacion y calculo
    # ------------------------------------------------------------------
    @staticmethod
    def _normalizar(valor, rango):
        """Min-max dentro del rango configurado. None si no es evaluable."""
        if valor is None or rango is None:
            return None
        try:
            valor = float(valor)
        except (TypeError, ValueError):
            return None
        minimo, maximo = rango
        if maximo < minimo:
            minimo, maximo = maximo, minimo
        valor = min(max(valor, minimo), maximo)
        if maximo == minimo:
            return 0.0
        return (valor - minimo) / (maximo - minimo)

    @staticmethod
    def calcular(registros, reglas, perfil):
        """Aplica las reglas y devuelve los registros enriquecidos y ordenados."""
        if not registros:
            return []

        # 1. Rango real de cada indicador sobre el conjunto consultado.
        rangos = {}
        for regla in reglas:
            indicador = resolver_indicador(regla["codigo"])
            if indicador is None:
                rangos[regla["codigo"]] = None
                continue
            valores = [r.get(indicador) for r in registros]
            valores = [float(v) for v in valores if v is not None]
            if not valores:
                rangos[regla["codigo"]] = None
                continue
            # Los umbrales de la regla acotan la normalizacion; si no hay
            # umbral superior se usa el maximo observado en la consulta.
            lo = regla["umbral_minimo"]
            hi = regla["umbral_maximo"]
            rangos[regla["codigo"]] = (
                float(lo) if lo is not None else min(valores),
                float(hi) if hi is not None else max(valores),
            )

        peso_total = sum(float(r["peso"]) for r in reglas) or 1.0
        critico = float(perfil["umbral_critico_pct"]) / 100.0
        alto = float(perfil["umbral_alto_pct"]) / 100.0
        medio = float(perfil["umbral_medio_pct"]) / 100.0

        resultado = []
        for registro in registros:
            puntaje = 0.0
            detalle = {}
            faltantes = []
            obligatorio_fallido = None

            for regla in reglas:
                codigo = regla["codigo"]
                indicador = resolver_indicador(codigo)
                rango = rangos.get(codigo)
                bruto = registro.get(indicador) if indicador else None
                normalizado = None

                if rango is not None:
                    normalizado = RankingModel._normalizar(bruto, rango)
                    if regla["direccion"] == "MENOR" and normalizado is not None:
                        normalizado = 1.0 - normalizado

                aporte = (normalizado or 0.0) * float(regla["peso"])
                puntaje += aporte

                detalle[codigo] = {
                    "valor": bruto,
                    "normalizado": round(normalizado * 100, 2) if normalizado is not None else None,
                    "peso": float(regla["peso"]),
                    "aporte": round(aporte, 4),
                    "direccion": regla["direccion"],
                    "obligatorio": bool(regla["obligatorio"]),
                }

                if normalizado is None:
                    faltantes.append(codigo)
                    if regla["obligatorio"] and obligatorio_fallido is None:
                        obligatorio_fallido = codigo

            evaluable = obligatorio_fallido is None
            puntaje = puntaje / peso_total if peso_total else 0.0

            item = dict(registro)
            item["puntaje_bruto"] = round(puntaje, 6)
            item["indicadores_detalle"] = detalle
            item["indicadores_faltantes"] = faltantes
            item["evaluable"] = evaluable
            item["motivo_no_evaluable"] = (
                None if evaluable else
                f"Indicador obligatorio sin dato: {obligatorio_fallido}"
            )
            item["categoria_prioridad"] = "NO_EVALUABLE" if not evaluable else None
            resultado.append(item)

        # 2. Relativizacion sobre el maximo y clasificacion.
        maximo = max((r["puntaje_bruto"] for r in resultado if r["evaluable"]), default=0.0)
        for item in resultado:
            if not item["evaluable"]:
                item["puntaje_relativo"] = 0.0
                continue
            relativo = (item["puntaje_bruto"] / maximo) if maximo > 0 else 0.0
            item["puntaje_relativo"] = round(relativo * 100, 2)
            if relativo >= critico:
                item["categoria_prioridad"] = "CRITICA"
            elif relativo >= alto:
                item["categoria_prioridad"] = "ALTA"
            elif relativo >= medio:
                item["categoria_prioridad"] = "MEDIA"
            else:
                item["categoria_prioridad"] = "BAJA"
            item["categoria_color"] = CATEGORIAS_PRIORIDAD[item["categoria_prioridad"]]["color"]
            item["categoria_etiqueta"] = CATEGORIAS_PRIORIDAD[item["categoria_prioridad"]]["etiqueta"]

        # 3. Orden: primero no evaluables, luego por puntaje descendente.
        resultado.sort(
            key=lambda r: (
                1 if not r["evaluable"] else 0,
                -r["puntaje_relativo"],
                -(r.get("puntaje_bruto") or 0),
            )
        )
        posicion = 0
        for item in resultado:
            if item["evaluable"]:
                posicion += 1
                item["posicion"] = posicion
            else:
                item["posicion"] = None
        return resultado

    # ------------------------------------------------------------------
    # Rankings completos
    # ------------------------------------------------------------------
    @classmethod
    def ranking_establecimientos(cls, filtros, id_perfil, limite=None,
                                incluir_no_evaluables=True, solo_con_capacidad=True):
        """Ranking de establecimientos segun el perfil de prioridad elegido.

        `id_perfil` admite el id numerico o el codigo del perfil.
        """
        perfil = PrioridadModel.obtener_perfil(id_perfil)
        reglas = cls.reglas_de(perfil["id_perfil"])
        if not reglas:
            raise RankingError(
                f"El perfil '{perfil['nombre']}' no tiene reglas activas. "
                "Configure al menos una regla en Administracion > Reglas de prioridad."
            )

        registros = IndicadoresModel.indicadores_establecimiento(
            filtros, codigo_ipress=filtros.codigo_ipress
        )
        if solo_con_capacidad:
            registros = [
                r for r in registros
                if r.get("dias_reportados") and (r.get("dias_reportados") or 0) > 0
            ]

        ranking = cls.calcular(registros, reglas, perfil)
        if not incluir_no_evaluables:
            ranking = [r for r in ranking if r["evaluable"]]
        if limite:
            ranking = ranking[:limite]

        return {
            "perfil": perfil,
            "reglas": reglas,
            "filas": ranking,
            "total_evaluados": sum(1 for r in ranking if r["evaluable"]),
            "total_no_evaluables": sum(1 for r in ranking if not r["evaluable"]),
            "resumen_categorias": cls.resumen_categorias(ranking),
        }

    @classmethod
    def ranking_territorios(cls, filtros, id_perfil, nivel="region", limite=None):
        """Ranking de territorios segun el perfil de prioridad elegido."""
        perfil = PrioridadModel.obtener_perfil(id_perfil)
        reglas = cls.reglas_de(perfil["id_perfil"])
        if not reglas:
            raise RankingError(
                f"El perfil '{perfil['nombre']}' no tiene reglas activas."
            )

        registros = IndicadoresModel.indicadores_territorio(
            filtros, nivel=nivel, solo_con_capacidad=True
        )
        # Los agregados territoriales no traen todos los indicadores por
        # establecimiento: se recalculan los que faltan con los equivalentes.
        for registro in registros:
            registro.setdefault("dias_sin_reporte", 0)
            registro.setdefault("cobertura_uci",
                                1.0 if (registro.get("uci_operativas") or 0) > 0 else 0.0)
            registro.setdefault("pico_ocupacion", registro.get("pico_ocupacion") or 0.0)
            registro.setdefault("presion_emergencia",
                                registro.get("presion_emergencia") or 0.0)
            registro.setdefault("tasa_inoperatividad",
                                registro.get("tasa_inoperatividad") or 0.0)

        ranking = cls.calcular(registros, reglas, perfil)
        if limite:
            ranking = ranking[:limite]
        return {
            "perfil": perfil,
            "reglas": reglas,
            "nivel": nivel,
            "filas": ranking,
            "total_evaluados": sum(1 for r in ranking if r["evaluable"]),
            "total_no_evaluables": sum(1 for r in ranking if not r["evaluable"]),
            "resumen_categorias": cls.resumen_categorias(ranking),
        }

    @staticmethod
    def resumen_categorias(filas):
        resumen = {clave: 0 for clave in CATEGORIAS_PRIORIDAD}
        for fila in filas:
            categoria = fila.get("categoria_prioridad") or "NO_EVALUABLE"
            resumen[categoria] = resumen.get(categoria, 0) + 1
        return [
            {
                "clave": clave,
                "etiqueta": CATEGORIAS_PRIORIDAD[clave]["etiqueta"],
                "color": CATEGORIAS_PRIORIDAD[clave]["color"],
                "cantidad": cantidad,
            }
            for clave, cantidad in resumen.items()
        ]

    # ------------------------------------------------------------------
    # Ranking territorial a partir de la vista de brechas del modelo
    # ------------------------------------------------------------------
    @classmethod
    def brechas_por_departamento(cls, filtros, limite=25):
        """Brecha demanda/capacidad agregada por región.

        Se calcula sobre `dim_ipress_ext` y no sobre la vista
        `v_brecha_demanda_capacidad`: esa vista ya viene agregada por
        departamento y por mes, por lo que no admite los filtros de
        provincia, distrito ni código IPRESS (sus columnas son
        `departamento`, `anio` y `mes`).
        """
        cond_fecha, params_fecha = filtros.where_tiempo("a")
        cond_geo, params_geo = filtros.where_geo("i")
        condiciones = cond_fecha + cond_geo
        where = ("WHERE " + " AND ".join(condiciones)) if condiciones else ""
        plan = filtros.columna_afiliados

        sql = f"""
            SELECT TOP (?) i.region AS departamento,
                   COUNT(DISTINCT a.codigo_ipress) AS establecimientos,
                   SUM(ISNULL(a.{plan}, 0)) AS total_asegurados,
                   ROUND(CAST(SUM(ISNULL(a.{plan}, 0)) AS FLOAT)
                       / NULLIF(SUM(CAST(ISNULL(c.total_camas_operativas, 0) AS FLOAT)), 0), 2)
                       AS ratio_asegurados_por_cama
            FROM dbo.fact_afiliados_sis a
            INNER JOIN dbo.dim_ipress_ext i ON i.codigo_ipress = a.codigo_ipress
            LEFT JOIN dbo.fact_capacidad_diaria c
                   ON c.codigo_ipress = a.codigo_ipress
                  AND c.fecha_corte = a.fecha_corte
            {where}
            GROUP BY i.region
            ORDER BY ratio_asegurados_por_cama DESC
        """
        return normalizar_filas(
            BaseModel.consultar(sql, [limite] + params_fecha + params_geo)
        )