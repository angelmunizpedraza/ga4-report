"""Informes de tráfico orgánico: peticiones a la API, comparación de periodos y alertas.

Todo lo que hay aquí es lógica pura sobre datos ya descargados, así que se
puede probar sin tocar la API.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

from .client import Informe

METRICAS_BASE = ["sessions", "totalUsers", "engagedSessions", "conversions", "engagementRate"]


# --- rangos de fechas --------------------------------------------------------

@dataclass(frozen=True)
class Periodo:
    inicio: date
    fin: date

    @property
    def dias(self) -> int:
        return (self.fin - self.inicio).days + 1

    def anterior(self) -> "Periodo":
        """El mismo número de días justo antes de este periodo."""
        fin = self.inicio - timedelta(days=1)
        return Periodo(fin - timedelta(days=self.dias - 1), fin)

    def api(self) -> dict:
        return {"startDate": self.inicio.isoformat(), "endDate": self.fin.isoformat()}

    def __str__(self) -> str:
        return f"{self.inicio:%d/%m/%Y} – {self.fin:%d/%m/%Y}"


def ultimos_dias(n: int, hasta: date | None = None) -> Periodo:
    """Últimos n días completos. Por defecto acaba ayer: los datos de hoy en GA4
    llegan con horas de retraso y compararlos con un día cerrado engaña."""
    fin = hasta or (date.today() - timedelta(days=1))
    return Periodo(fin - timedelta(days=n - 1), fin)


def mes_actual(hoy: date | None = None) -> Periodo:
    hoy = hoy or date.today()
    return Periodo(hoy.replace(day=1), hoy - timedelta(days=1) if hoy.day > 1 else hoy)


# --- peticiones --------------------------------------------------------------

def filtro_organico() -> dict:
    return {
        "filter": {
            "fieldName": "sessionDefaultChannelGroup",
            "stringFilter": {"matchType": "EXACT", "value": "Organic Search"},
        }
    }


def peticion_landing_pages(periodo: Periodo, limite: int = 100, solo_organico: bool = True) -> dict:
    cuerpo = {
        "dateRanges": [periodo.api()],
        "dimensions": [{"name": "landingPagePlusQueryString"}],
        "metrics": [{"name": m} for m in METRICAS_BASE],
        "orderBys": [{"metric": {"metricName": "sessions"}, "desc": True}],
        "limit": limite,
    }
    if solo_organico:
        cuerpo["dimensionFilter"] = filtro_organico()
    return cuerpo


def peticion_totales(periodo: Periodo, solo_organico: bool = True) -> dict:
    cuerpo = {
        "dateRanges": [periodo.api()],
        "metrics": [{"name": m} for m in METRICAS_BASE],
    }
    if solo_organico:
        cuerpo["dimensionFilter"] = filtro_organico()
    return cuerpo


def peticion_por_canal(periodo: Periodo) -> dict:
    return {
        "dateRanges": [periodo.api()],
        "dimensions": [{"name": "sessionDefaultChannelGroup"}],
        "metrics": [{"name": "sessions"}, {"name": "conversions"}],
        "orderBys": [{"metric": {"metricName": "sessions"}, "desc": True}],
    }


# --- comparación -------------------------------------------------------------

def variacion(actual: float, anterior: float) -> float | None:
    """Porcentaje de cambio. None cuando no había base (evita dividir por cero
    y evita el falso '+100%' de una página que pasa de 0 a 1 sesión)."""
    if anterior == 0:
        return None
    return round((actual - anterior) / anterior * 100, 1)


@dataclass
class Comparacion:
    clave: str
    actual: dict
    anterior: dict
    var_sesiones: float | None
    var_conversiones: float | None


def comparar_por_clave(actual: Informe, anterior: Informe, clave: str) -> list[Comparacion]:
    """Cruza dos informes por una dimensión (p. ej. landing page).

    Las páginas que solo existen en un periodo entran igual con ceros en el
    otro: una landing nueva que ya trae tráfico es tan noticia como una que
    ha desaparecido.
    """
    ant = {f[clave]: f for f in anterior.filas}
    act = {f[clave]: f for f in actual.filas}
    vacio = {m: 0 for m in METRICAS_BASE}

    salida = []
    for k in sorted(set(ant) | set(act), key=lambda x: -act.get(x, vacio).get("sessions", 0)):
        a, b = act.get(k, vacio), ant.get(k, vacio)
        salida.append(Comparacion(
            clave=k,
            actual=a,
            anterior=b,
            var_sesiones=variacion(a.get("sessions", 0), b.get("sessions", 0)),
            var_conversiones=variacion(a.get("conversions", 0), b.get("conversions", 0)),
        ))
    return salida


# --- alertas -----------------------------------------------------------------

@dataclass
class Alerta:
    nivel: str      # critica | aviso | positiva
    pagina: str
    mensaje: str
    sesiones_actual: int
    sesiones_anterior: int
    variacion: float | None


def detectar_alertas(
    comparaciones: list[Comparacion],
    umbral_caida: float = -30.0,
    umbral_subida: float = 50.0,
    minimo_sesiones: int = 20,
) -> list[Alerta]:
    """Marca páginas con cambios que merecen que alguien las mire.

    `minimo_sesiones` evita ruido: una página que pasa de 3 a 1 sesión ha
    caído un 67% y no significa nada. Solo alertamos si en alguno de los dos
    periodos tuvo tráfico real.
    """
    alertas = []
    for c in comparaciones:
        s_act = int(c.actual.get("sessions", 0))
        s_ant = int(c.anterior.get("sessions", 0))
        if max(s_act, s_ant) < minimo_sesiones:
            continue

        if s_ant >= minimo_sesiones and s_act == 0:
            alertas.append(Alerta("critica", c.clave, "Ha dejado de recibir tráfico orgánico", s_act, s_ant, -100.0))
        elif c.var_sesiones is not None and c.var_sesiones <= umbral_caida:
            nivel = "critica" if c.var_sesiones <= umbral_caida * 2 else "aviso"
            alertas.append(Alerta(nivel, c.clave, f"Caída del {abs(c.var_sesiones):.0f}% en sesiones", s_act, s_ant, c.var_sesiones))
        elif c.var_sesiones is None and s_act >= minimo_sesiones:
            alertas.append(Alerta("positiva", c.clave, "Landing nueva con tráfico", s_act, s_ant, None))
        elif c.var_sesiones is not None and c.var_sesiones >= umbral_subida:
            alertas.append(Alerta("positiva", c.clave, f"Subida del {c.var_sesiones:.0f}% en sesiones", s_act, s_ant, c.var_sesiones))

    orden = {"critica": 0, "aviso": 1, "positiva": 2}
    return sorted(alertas, key=lambda a: (orden[a.nivel], -abs(a.sesiones_anterior - a.sesiones_actual)))


# --- resumen -----------------------------------------------------------------

@dataclass
class Resumen:
    periodo: Periodo
    periodo_anterior: Periodo
    totales: dict
    totales_anterior: dict
    variaciones: dict = field(default_factory=dict)
    top_landings: list[Comparacion] = field(default_factory=list)
    alertas: list[Alerta] = field(default_factory=list)
    canales: list[dict] = field(default_factory=list)


def construir_resumen(
    periodo: Periodo,
    totales: Informe,
    totales_ant: Informe,
    landings: Informe,
    landings_ant: Informe,
    canales: Informe | None = None,
    top: int = 10,
) -> Resumen:
    t = totales.filas[0] if totales.filas else {m: 0 for m in METRICAS_BASE}
    ta = totales_ant.filas[0] if totales_ant.filas else {m: 0 for m in METRICAS_BASE}
    comps = comparar_por_clave(landings, landings_ant, "landingPagePlusQueryString")
    return Resumen(
        periodo=periodo,
        periodo_anterior=periodo.anterior(),
        totales=t,
        totales_anterior=ta,
        variaciones={m: variacion(t.get(m, 0), ta.get(m, 0)) for m in METRICAS_BASE},
        top_landings=comps[:top],
        alertas=detectar_alertas(comps),
        canales=canales.filas if canales else [],
    )
