"""Tests de ga4-report.

No se llama a la API: usamos la estructura exacta que devuelve runReport
(cabeceras separadas de valores, todo como string) para comprobar el
aplanado, la comparación de periodos y las alertas.
"""

import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ga4_report.client import aplanar_respuesta, Informe  # noqa: E402
from ga4_report.reports import (  # noqa: E402
    Periodo, ultimos_dias, mes_actual, variacion, comparar_por_clave,
    detectar_alertas, construir_resumen, peticion_landing_pages, METRICAS_BASE,
)
from ga4_report.output import a_markdown, a_csv, a_dict  # noqa: E402


# --- fixtures: respuesta cruda de la API -------------------------------------

def respuesta_api(filas: list[tuple[str, int, int, int, int, float]]) -> dict:
    """Imita runReport con landing page + métricas base."""
    return {
        "dimensionHeaders": [{"name": "landingPagePlusQueryString"}],
        "metricHeaders": [
            {"name": "sessions", "type": "TYPE_INTEGER"},
            {"name": "totalUsers", "type": "TYPE_INTEGER"},
            {"name": "engagedSessions", "type": "TYPE_INTEGER"},
            {"name": "conversions", "type": "TYPE_FLOAT"},
            {"name": "engagementRate", "type": "TYPE_FLOAT"},
        ],
        "rows": [
            {
                "dimensionValues": [{"value": pagina}],
                "metricValues": [{"value": str(s)}, {"value": str(u)}, {"value": str(e)}, {"value": str(c)}, {"value": str(er)}],
            }
            for pagina, s, u, e, c, er in filas
        ],
        "rowCount": len(filas),
    }


def informe(filas):
    return aplanar_respuesta(respuesta_api(filas))


def totales(sesiones, usuarios, conversiones):
    d = respuesta_api([("_", sesiones, usuarios, sesiones, conversiones, 0.6)])
    d["dimensionHeaders"] = []
    for fila in d["rows"]:
        fila["dimensionValues"] = []
    return aplanar_respuesta(d)


# --- aplanado ----------------------------------------------------------------

def test_aplanar_convierte_metricas_a_numero():
    inf = informe([("/curso", 120, 100, 80, 3, 0.66)])
    fila = inf.filas[0]
    assert fila["landingPagePlusQueryString"] == "/curso"
    assert fila["sessions"] == 120 and isinstance(fila["sessions"], int)
    assert fila["conversions"] == 3.0 and isinstance(fila["conversions"], float)
    assert fila["engagementRate"] == pytest.approx(0.66)


def test_aplanar_respuesta_vacia():
    inf = aplanar_respuesta({"dimensionHeaders": [], "metricHeaders": [], "rows": []})
    assert inf.filas == [] and inf.total_filas == 0


def test_aplanar_sin_rows_no_falla():
    inf = aplanar_respuesta({"dimensionHeaders": [{"name": "x"}], "metricHeaders": [{"name": "sessions"}]})
    assert inf.filas == []


def test_valor_no_numerico_se_convierte_en_cero():
    d = respuesta_api([("/a", 1, 1, 1, 0, 0.5)])
    d["rows"][0]["metricValues"][0]["value"] = "(not set)"
    assert aplanar_respuesta(d).filas[0]["sessions"] == 0


# --- periodos ----------------------------------------------------------------

def test_periodo_anterior_mismo_numero_de_dias():
    p = Periodo(date(2026, 8, 4), date(2026, 8, 31))
    ant = p.anterior()
    assert ant.dias == p.dias == 28
    assert ant.fin == date(2026, 8, 3)
    assert ant.inicio == date(2026, 7, 7)


def test_ultimos_dias_acaba_ayer():
    p = ultimos_dias(7, hasta=date(2026, 9, 1))
    assert p.fin == date(2026, 9, 1) and p.inicio == date(2026, 8, 26)


def test_mes_actual_empieza_el_dia_uno():
    p = mes_actual(hoy=date(2026, 9, 15))
    assert p.inicio == date(2026, 9, 1) and p.fin == date(2026, 9, 14)


def test_periodo_en_formato_api():
    assert Periodo(date(2026, 1, 1), date(2026, 1, 31)).api() == {"startDate": "2026-01-01", "endDate": "2026-01-31"}


# --- variación ---------------------------------------------------------------

def test_variacion_positiva_y_negativa():
    assert variacion(150, 100) == 50.0
    assert variacion(70, 100) == -30.0


def test_variacion_sin_base_devuelve_none():
    """De 0 a 50 no es '+inf%' ni '+100%': no había base de comparación."""
    assert variacion(50, 0) is None


# --- comparación -------------------------------------------------------------

def test_comparar_incluye_paginas_solo_en_un_periodo():
    act = informe([("/a", 100, 90, 60, 2, 0.6), ("/nueva", 40, 30, 20, 1, 0.5)])
    ant = informe([("/a", 80, 70, 50, 1, 0.6), ("/vieja", 60, 50, 30, 0, 0.5)])
    comps = {c.clave: c for c in comparar_por_clave(act, ant, "landingPagePlusQueryString")}
    assert set(comps) == {"/a", "/nueva", "/vieja"}
    assert comps["/a"].var_sesiones == 25.0
    assert comps["/nueva"].var_sesiones is None
    assert comps["/vieja"].actual["sessions"] == 0


def test_comparar_ordena_por_sesiones_actuales_desc():
    act = informe([("/b", 10, 1, 1, 0, 0.1), ("/a", 100, 1, 1, 0, 0.1)])
    ant = informe([])
    assert [c.clave for c in comparar_por_clave(act, ant, "landingPagePlusQueryString")] == ["/a", "/b"]


# --- alertas -----------------------------------------------------------------

def _comps(act, ant):
    return comparar_por_clave(informe(act), informe(ant), "landingPagePlusQueryString")


def test_alerta_caida_fuerte_es_critica():
    alertas = detectar_alertas(_comps([("/a", 30, 1, 1, 0, 0.1)], [("/a", 100, 1, 1, 0, 0.1)]))
    assert alertas[0].nivel == "critica" and alertas[0].variacion == -70.0


def test_alerta_caida_moderada_es_aviso():
    alertas = detectar_alertas(_comps([("/a", 65, 1, 1, 0, 0.1)], [("/a", 100, 1, 1, 0, 0.1)]))
    assert alertas[0].nivel == "aviso"


def test_pagina_desaparecida_es_critica():
    alertas = detectar_alertas(_comps([], [("/a", 100, 1, 1, 0, 0.1)]))
    assert alertas[0].nivel == "critica" and "dejado" in alertas[0].mensaje


def test_ruido_de_paginas_pequenas_se_ignora():
    """De 3 a 1 es -67% pero no significa nada."""
    assert detectar_alertas(_comps([("/a", 1, 1, 1, 0, 0.1)], [("/a", 3, 1, 1, 0, 0.1)])) == []


def test_landing_nueva_con_trafico_es_positiva():
    alertas = detectar_alertas(_comps([("/nueva", 50, 1, 1, 0, 0.1)], []))
    assert alertas[0].nivel == "positiva" and "nueva" in alertas[0].mensaje.lower()


def test_subida_fuerte_es_positiva():
    alertas = detectar_alertas(_comps([("/a", 160, 1, 1, 0, 0.1)], [("/a", 100, 1, 1, 0, 0.1)]))
    assert alertas[0].nivel == "positiva"


def test_alertas_criticas_primero():
    comps = _comps([("/sube", 200, 1, 1, 0, 0.1), ("/cae", 10, 1, 1, 0, 0.1)],
                   [("/sube", 100, 1, 1, 0, 0.1), ("/cae", 100, 1, 1, 0, 0.1)])
    alertas = detectar_alertas(comps)
    assert alertas[0].pagina == "/cae" and alertas[-1].pagina == "/sube"


# --- peticiones --------------------------------------------------------------

def test_peticion_landing_filtra_organico_por_defecto():
    cuerpo = peticion_landing_pages(Periodo(date(2026, 1, 1), date(2026, 1, 31)))
    assert cuerpo["dimensionFilter"]["filter"]["stringFilter"]["value"] == "Organic Search"
    assert [m["name"] for m in cuerpo["metrics"]] == METRICAS_BASE


def test_peticion_landing_sin_filtro():
    assert "dimensionFilter" not in peticion_landing_pages(Periodo(date(2026, 1, 1), date(2026, 1, 31)), solo_organico=False)


# --- resumen y salida --------------------------------------------------------

@pytest.fixture
def resumen():
    periodo = Periodo(date(2026, 8, 4), date(2026, 8, 31))
    return construir_resumen(
        periodo,
        totales(28000, 21000, 410),
        totales(24500, 19000, 380),
        informe([("/curso-perito", 5200, 4000, 3500, 80, 0.67), ("/blog/guia", 1200, 1000, 700, 10, 0.55)]),
        informe([("/curso-perito", 4800, 3700, 3200, 75, 0.66), ("/blog/guia", 2400, 2000, 1500, 20, 0.6)]),
        top=10,
    )


def test_resumen_calcula_variaciones_globales(resumen):
    assert resumen.variaciones["sessions"] == pytest.approx(14.3, abs=0.1)
    assert resumen.periodo_anterior.fin == date(2026, 8, 3)


def test_resumen_genera_alerta_por_caida_del_blog(resumen):
    paginas = {a.pagina for a in resumen.alertas}
    assert "/blog/guia" in paginas


def test_markdown_contiene_secciones_y_cifras(resumen):
    md = a_markdown(resumen)
    assert "## Totales" in md and "## Alertas" in md and "## Landing pages principales" in md
    assert "28.000" in md and "+14.3%" in md
    assert "/blog/guia" in md and "-50.0%" in md


def test_csv_tiene_cabecera_y_filas(resumen):
    lineas = a_csv(resumen).strip().splitlines()
    assert lineas[0].startswith("landing_page,sesiones")
    assert len(lineas) == 3


def test_dict_es_serializable(resumen):
    import json
    d = a_dict(resumen)
    json.dumps(d)  # no debe lanzar
    assert d["periodo"]["inicio"] == "2026-08-04"
    assert d["alertas"][0]["pagina"] == "/blog/guia"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
