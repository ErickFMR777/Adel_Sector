"""
catalogos.py — Catálogos de opciones válidas para filtrar en ambos portales.

Es la **única fuente de verdad** de los valores seleccionables. Existe
porque los dos portales nombran distinto las mismas cosas, y una
diferencia de una letra hace que la consulta devuelva cero registros
sin ningún error visible. Casos reales verificados en producción:

    Concepto            SECOP I (formulario)          SECOP II (API)
    ─────────────────────────────────────────────────────────────────
    Bogotá              "Bogotá D.C."  (cód. 1100)    "Distrito Capital de Bogotá"
    Norte de Santander  "Norte De Santander"          "Norte de Santander"
    Mínima cuantía      "Contratación Mínima Cuantía" "Mínima cuantía"
    Subasta inversa     "Subasta"                     "Selección abreviada subasta inversa"

Con este catálogo la interfaz muestra una etiqueta legible y envía a
cada portal el valor exacto que ese portal espera, de modo que el
usuario no puede equivocarse escribiendo.

Los valores de ``valor_api`` salen de agrupar el dataset real
(``$group``); los de ``codigo_secop1``, de los JS del portal.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class Opcion:
    """Una opción seleccionable, con su equivalente en cada portal.

    Attributes:
        etiqueta:      Texto que ve la persona usuaria.
        codigo_secop1: Valor que espera el formulario de SECOP I.
                       ``None`` si el concepto no existe en ese portal.
        valor_api:     Valor exacto del campo en SECOP II.
                       ``None`` si no existe como valor literal.
        valores_api:   Varios valores de la API cuando el concepto no
                       tiene equivalente único. Es el caso de "Celebrado":
                       SECOP I marca así el proceso que ya derivó en
                       contrato, mientras que SECOP II reparte esos
                       contratos entre "Cerrado", "En ejecución",
                       "Modificado", etc. Se declara aparte de
                       ``valor_api`` para que quede claro que no es un
                       valor literal del dataset.
    """

    etiqueta: str
    codigo_secop1: Optional[str] = None
    valor_api: Optional[str] = None
    valores_api: tuple[str, ...] = ()

    @property
    def api_valores(self) -> tuple[str, ...]:
        """Todos los valores de la API que representa esta opción."""
        if self.valores_api:
            return self.valores_api
        return (self.valor_api,) if self.valor_api else ()

    @property
    def existe_en_api(self) -> bool:
        """La opción se puede filtrar en SECOP II."""
        return bool(self.api_valores)

    @property
    def solo_secop1(self) -> bool:
        """La opción únicamente filtra en SECOP I."""
        return self.codigo_secop1 is not None and not self.existe_en_api

    @property
    def solo_api(self) -> bool:
        """La opción únicamente filtra en SECOP II."""
        return self.existe_en_api and self.codigo_secop1 is None


# Etiqueta de la opción "sin filtro". Consultar sin departamento es la
# búsqueda a nivel nacional.
TODOS = "— Todos —"
NACIONAL = "🇨🇴 Todo el país (nacional)"


# ────────────────────────────────────────────────────────────
# DEPARTAMENTOS
# ────────────────────────────────────────────────────────────

DEPARTAMENTOS: list[Opcion] = [
    Opcion("Amazonas", "91000", "Amazonas"),
    Opcion("Antioquia", "5000", "Antioquia"),
    Opcion("Arauca", "81000", "Arauca"),
    Opcion("Atlántico", "8000", "Atlántico"),
    # OJO: la API no usa "Bogotá D.C." sino "Distrito Capital de Bogotá".
    Opcion("Bogotá D.C.", "1100", "Distrito Capital de Bogotá"),
    Opcion("Bolívar", "1300", "Bolívar"),
    Opcion("Boyacá", "15000", "Boyacá"),
    Opcion("Caldas", "17000", "Caldas"),
    Opcion("Caquetá", "1800", "Caquetá"),
    Opcion("Casanare", "85000", "Casanare"),
    Opcion("Cauca", "19000", "Cauca"),
    Opcion("Cesar", "20000", "Cesar"),
    Opcion("Chocó", "27000", "Chocó"),
    Opcion("Córdoba", "23000", "Córdoba"),
    Opcion("Cundinamarca", "25000", "Cundinamarca"),
    Opcion("Guainía", "94000", "Guainía"),
    Opcion("Guaviare", "95000", "Guaviare"),
    Opcion("Huila", "41000", "Huila"),
    Opcion("La Guajira", "44000", "La Guajira"),
    Opcion("Magdalena", "47000", "Magdalena"),
    Opcion("Meta", "50000", "Meta"),
    Opcion("Nariño", "52000", "Nariño"),
    # La API escribe "de" en minúscula; el portal, "De".
    Opcion("Norte de Santander", "54000", "Norte de Santander"),
    Opcion("Putumayo", "86000", "Putumayo"),
    Opcion("Quindío", "63000", "Quindío"),
    Opcion("Risaralda", "66000", "Risaralda"),
    Opcion(
        "San Andrés, Providencia y Santa Catalina",
        "88000",
        "San Andrés, Providencia y Santa Catalina",
    ),
    Opcion("Santander", "668000", "Santander"),
    Opcion("Sucre", "70000", "Sucre"),
    Opcion("Tolima", "73000", "Tolima"),
    Opcion("Valle del Cauca", "76000", "Valle del Cauca"),
    Opcion("Vaupés", "97000", "Vaupés"),
    Opcion("Vichada", "99000", "Vichada"),
    # Contratos cuya ubicación no quedó registrada (solo en la API).
    Opcion("Sin departamento definido", None, "No Definido"),
]


# ────────────────────────────────────────────────────────────
# MODALIDADES DE CONTRATACIÓN
# ────────────────────────────────────────────────────────────

MODALIDADES: list[Opcion] = [
    # --- Presentes en ambos portales ---
    Opcion("Mínima cuantía", "13", "Mínima cuantía"),
    Opcion("Contratación directa", "12", "Contratación directa"),
    Opcion("Contratación directa (con ofertas)", "2", "Contratación Directa (con ofertas)"),
    Opcion("Régimen especial", "4", "Contratación régimen especial"),
    Opcion("Licitación pública", "1", "Licitación pública"),
    Opcion("Licitación pública de obra", "21", "Licitación pública Obra Publica"),
    Opcion("Selección abreviada de menor cuantía", "11", "Selección Abreviada de Menor Cuantía"),
    Opcion("Selección abreviada subasta inversa", "9", "Selección abreviada subasta inversa"),
    Opcion("Concurso de méritos abierto", "15", "Concurso de méritos abierto"),
    # --- Solo en la API de SECOP II ---
    Opcion("Régimen especial (con ofertas)", None, "Contratación régimen especial (con ofertas)"),
    Opcion("Licitación pública — Acuerdo Marco de Precios", None,
           "Licitación Pública Acuerdo Marco de Precios"),
    Opcion("Selección abreviada menor cuantía sin manifestación de interés", None,
           "Seleccion Abreviada Menor Cuantia Sin Manifestacion Interes"),
    Opcion("Concurso de méritos con precalificación", None,
           "Concurso de méritos con precalificación"),
    Opcion("Enajenación de bienes con sobre cerrado", None,
           "Enajenación de bienes con sobre cerrado"),
    Opcion("Enajenación de bienes con subasta", None, "Enajenación de bienes con subasta"),
    Opcion("Modalidad no definida", None, "No Definido"),
    # --- Solo en el formulario de SECOP I ---
    Opcion("Concurso de méritos con lista corta", "10", None),
    Opcion("Concurso de méritos con lista multiusos", "14", None),
    Opcion("Lista multiusos", "16", None),
    Opcion("Selección abreviada servicios de salud", "17", None),
    Opcion("Otras formas de contratación directa", "3", None),
    Opcion("Invitación a cooperativas o asociaciones territoriales", "5", None),
    Opcion("Selección abreviada literal h (Ley 1150 de 2007)", "18", None),
    Opcion("Asociación público privada", "19", None),
    Opcion("Iniciativa privada sin recursos públicos", "20", None),
    Opcion("Contratos y convenios con más de dos partes", "22", None),
    Opcion("Concurso de diseño arquitectónico", "23", None),
]


# ────────────────────────────────────────────────────────────
# TIPO DE CONTRATO
#   Solo existe en SECOP II: la tabla de resultados de SECOP I no
#   trae esta columna (aparece únicamente en la ficha de detalle).
# ────────────────────────────────────────────────────────────

TIPOS_CONTRATO: list[Opcion] = [
    Opcion(nombre, None, nombre)
    for nombre in (
        "Prestación de servicios",
        "Suministros",
        "Compraventa",
        "Obra",
        "Arrendamiento de inmuebles",
        "Comodato",
        "Interventoría",
        "Consultoría",
        "Seguros",
        "Arrendamiento de muebles",
        "Acuerdo Marco de Precios",
        "Servicios financieros",
        "Operaciones de Crédito Público",
        "Asociación Público Privada",
        "Venta muebles",
        "Venta inmuebles",
        "Negocio fiduciario",
        "Comisión",
        "Concesión",
        "Acuerdo de cooperación",
        "Decreto 092 de 2017",
        "Otro",
        "No Especificado",
        "No Definido",
    )
]


# ────────────────────────────────────────────────────────────
# ESTADOS
#   Los dos portales modelan cosas distintas: SECOP I sigue el
#   estado del *proceso*, la API el del *contrato*. "Celebrado" en
#   SECOP I abarca varios estados de la API (ver
#   api_scraper.ESTADO_CELEBRADO_EQUIVALENTES).
# ────────────────────────────────────────────────────────────

ESTADOS: list[Opcion] = [
    # "Celebrado" no es un valor del dataset: es el estado del *proceso*
    # en SECOP I. En SECOP II esos contratos aparecen repartidos entre
    # varios estados, así que se declara como grupo.
    Opcion(
        "Celebrado / formalizado",
        "4",
        valores_api=(
            "Cerrado", "terminado", "En ejecución",
            "Modificado", "Prorrogado", "cedido",
        ),
    ),
    Opcion("En ejecución", None, "En ejecución"),
    Opcion("Cerrado", None, "Cerrado"),
    Opcion("Terminado", None, "terminado"),
    Opcion("Modificado", None, "Modificado"),
    Opcion("Prorrogado", None, "Prorrogado"),
    Opcion("Cedido", None, "cedido"),
    Opcion("Suspendido", None, "Suspendido"),
    Opcion("Cancelado", None, "Cancelado"),
    Opcion("Aprobado", None, "Aprobado"),
    Opcion("En aprobación", None, "En aprobación"),
    Opcion("Enviado al proveedor", None, "enviado Proveedor"),
    Opcion("Borrador", "1", "Borrador"),
    Opcion("Convocado", "2", None),
    Opcion("Adjudicado", "3", None),
    Opcion("Liquidado", "5", None),
    Opcion("Descartado", "6", None),
    Opcion("Terminado anormalmente", "7", None),
    Opcion("Terminado sin liquidar", "8", None),
]


# ────────────────────────────────────────────────────────────
# UTILIDADES DE BÚSQUEDA
# ────────────────────────────────────────────────────────────


def _normalizar(texto: str) -> str:
    """Minúsculas, sin tildes y sin espacios redundantes."""
    tabla = str.maketrans("áéíóúüñÁÉÍÓÚÜÑ", "aeiouunAEIOUUN")
    return " ".join(str(texto).translate(tabla).lower().split())


def buscar_opcion(catalogo: list[Opcion], valor: Optional[str]) -> Optional[Opcion]:
    """Localiza una opción por etiqueta, código de SECOP I o valor de la API.

    Es tolerante con tildes y mayúsculas para que siga funcionando
    cuando el valor llega escrito a mano (por ejemplo, desde la CLI).

    Args:
        catalogo: Uno de ``DEPARTAMENTOS`` / ``MODALIDADES`` / ...
        valor:    Texto a resolver.

    Returns:
        La ``Opcion`` correspondiente, o ``None`` si no se reconoce.
    """
    if valor is None:
        return None

    texto = str(valor).strip()
    if not texto or texto in (TODOS, NACIONAL):
        return None

    # 1. Código exacto de SECOP I.
    for opcion in catalogo:
        if opcion.codigo_secop1 == texto:
            return opcion

    # 2. Valor exacto de la API.
    for opcion in catalogo:
        if opcion.valor_api == texto:
            return opcion

    # 3. Etiqueta o valor, tolerando tildes y mayúsculas.
    objetivo = _normalizar(texto)
    for opcion in catalogo:
        candidatos = (
            opcion.etiqueta, opcion.valor_api, opcion.codigo_secop1,
            *opcion.valores_api,
        )
        if any(c and _normalizar(c) == objetivo for c in candidatos):
            return opcion

    # 4. Coincidencia parcial, como último recurso.
    for opcion in catalogo:
        if objetivo and objetivo in _normalizar(opcion.etiqueta):
            return opcion

    return None


def etiquetas(catalogo: list[Opcion], incluir_todos: bool = True) -> list[str]:
    """Devuelve las etiquetas del catálogo para poblar un desplegable."""
    valores = [opcion.etiqueta for opcion in catalogo]
    return [TODOS, *valores] if incluir_todos else valores


def etiqueta_anotada(opcion: Opcion) -> str:
    """Etiqueta con una nota si la opción solo sirve en un portal.

    Evita la confusión de elegir un filtro y recibir cero resultados de
    una fuente porque ese concepto sencillamente no existe allí.
    """
    if opcion.solo_api:
        return f"{opcion.etiqueta}  · solo SECOP II"
    if opcion.solo_secop1:
        return f"{opcion.etiqueta}  · solo SECOP I"
    return opcion.etiqueta


def opciones_desplegable(
    catalogo: list[Opcion],
    etiqueta_vacia: str = TODOS,
    anotar: bool = True,
) -> dict[str, Optional[Opcion]]:
    """Construye el mapa ``etiqueta mostrada → Opcion`` de un desplegable.

    Devolver el diccionario (en vez de solo las etiquetas) permite que la
    interfaz muestre un texto legible y anotado mientras conserva la
    opción completa, con el valor exacto que espera cada portal.

    Args:
        catalogo:       Lista de opciones.
        etiqueta_vacia: Texto de la opción "sin filtro".
        anotar:         Añadir la nota "· solo SECOP X". Conviene
                        desactivarlo cuando **todas** las opciones del
                        catálogo son del mismo portal (como los tipos de
                        contrato): repetir el mismo sufijo en cada
                        entrada solo añade ruido, y esa advertencia se
                        da una vez en la ayuda del campo.
    """
    mapa: dict[str, Optional[Opcion]] = {etiqueta_vacia: None}
    for opcion in catalogo:
        clave = etiqueta_anotada(opcion) if anotar else opcion.etiqueta
        mapa[clave] = opcion
    return mapa
