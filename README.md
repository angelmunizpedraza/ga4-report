# ga4-report

[![CI](https://github.com/angelmunizpedraza/ga4-report/actions/workflows/ci.yml/badge.svg)](https://github.com/angelmunizpedraza/ga4-report/actions)
![Python](https://img.shields.io/badge/python-3.10%2B-blue)
![License](https://img.shields.io/badge/license-MIT-green)

Informe de tráfico orgánico desde la API de Google Analytics 4, con comparación
automática contra el periodo anterior y alertas de landing pages que caen o suben.

Pensado para lanzarse solo cada lunes y llegar por Slack o WhatsApp vía n8n, para
que la revisión semanal empiece con "estas tres páginas necesitan atención" en
lugar de con veinte minutos de clics en la interfaz de GA4.

## Instalación

```bash
pip install "ga4-report @ git+https://github.com/angelmunizpedraza/ga4-report"
```

Deja disponible el comando `ga4-report`. Para trabajar sobre el código:

```bash
git clone https://github.com/angelmunizpedraza/ga4-report
cd ga4-report
pip install -e ".[dev]"
```

(`python -m ga4_report` sigue funcionando igual.)

## Configuración (una sola vez)

1. En [Google Cloud Console](https://console.cloud.google.com) crea un proyecto y
   activa **Google Analytics Data API**.
2. Crea una **cuenta de servicio** (IAM > Cuentas de servicio) y descarga su clave
   JSON.
3. En GA4, ve a **Administrar > Gestión de accesos a la propiedad** y añade el
   email de la cuenta de servicio (`algo@proyecto.iam.gserviceaccount.com`) con rol
   **Lector**.
4. Apunta el ID numérico de la propiedad (Administrar > Configuración de la
   propiedad).

```bash
export GOOGLE_APPLICATION_CREDENTIALS=/ruta/credenciales.json
```

Nunca subas ese JSON a un repositorio; el `.gitignore` ya lo excluye.

## Uso

```bash
python -m ga4_report --property 123456789
```

Últimos 28 días completos (hasta ayer) frente a los 28 anteriores, solo tráfico
orgánico. Otras opciones:

```bash
# Mes en curso, guardando Markdown y CSV
python -m ga4_report --property 123456789 --mes-actual --markdown informe.md --csv landings.csv

# Todos los canales, no solo orgánico
python -m ga4_report --property 123456789 --todos-los-canales

# Enviar a n8n y no imprimir por pantalla
python -m ga4_report --property 123456789 --webhook https://n8n.midominio.com/webhook/ga4 -q
```

| Opción | Descripción |
|---|---|
| `--property` | ID numérico de la propiedad GA4 (obligatorio) |
| `--credenciales` | Ruta al JSON de la cuenta de servicio |
| `--dias N` | Últimos N días completos (por defecto 28) |
| `--mes-actual` | Del día 1 hasta ayer |
| `--todos-los-canales` | No filtrar por `Organic Search` |
| `--top N` | Landing pages en la tabla (por defecto 15) |
| `--markdown`, `--csv`, `--json` | Guardar en cada formato |
| `--webhook URL` | POST con el JSON del resumen, incluyendo el Markdown ya formateado |

## Qué produce

```markdown
# Informe de tráfico orgánico

**Periodo:** 04/08/2026 – 31/08/2026
**Comparado con:** 07/07/2026 – 03/08/2026

## Totales

| Métrica | Actual | Anterior | Variación |
|---|---:|---:|---:|
| Sesiones | 28.000 | 24.500 | +14.3% |
| Conversiones | 410 | 380 | +7.9% |

## Alertas

- 🔴 `/pagina-antigua` — Ha dejado de recibir tráfico orgánico (180 → 0)
- 🟠 `/blog/guia-perito` — Caída del 50% en sesiones (2400 → 1200)
- 🟢 `/landing-nueva` — Landing nueva con tráfico (0 → 340)
```

Y debajo la tabla de landing pages con variación y conversiones, y el reparto por
canal.

## Alertas: cómo decide

| Situación | Nivel |
|---|---|
| Tenía ≥ 20 sesiones y ahora 0 | 🔴 crítica |
| Cae ≥ 60 % | 🔴 crítica |
| Cae entre 30 % y 60 % | 🟠 aviso |
| Sube ≥ 50 % o es nueva con ≥ 20 sesiones | 🟢 positiva |

Las páginas con menos de 20 sesiones en ambos periodos se ignoran. Una URL que
pasa de 3 a 1 sesión ha caído un 67 % y no significa absolutamente nada; sin este
filtro el informe se llena de ruido y deja de leerse.

## Automatizar con n8n

1. Nodo **Schedule** (lunes 8:00) → nodo **Execute Command**:
   `python -m ga4_report --property 123456789 --webhook {{$json.webhook}} -q`
2. O bien: nodo **Webhook** que recibe el POST. El cuerpo trae `markdown` listo para
   pegar en Slack/Telegram/WhatsApp, y `alertas` como lista para filtrar: por
   ejemplo, avisar solo si hay alguna `critica`.

## Uso como librería

```python
from ga4_report import ClienteGA4, ultimos_dias, construir_resumen, a_markdown
from ga4_report.reports import peticion_totales, peticion_landing_pages

cliente = ClienteGA4("123456789", "credenciales.json")
periodo = ultimos_dias(7)

resumen = construir_resumen(
    periodo,
    cliente.run_report(peticion_totales(periodo)),
    cliente.run_report(peticion_totales(periodo.anterior())),
    cliente.run_report(peticion_landing_pages(periodo)),
    cliente.run_report(peticion_landing_pages(periodo.anterior())),
)
print(a_markdown(resumen))
```

## Decisiones de diseño

**REST directo en lugar de `google-analytics-data`.** La librería oficial arrastra
gRPC, protobuf y unos 40 MB de dependencias para hacer dos POST. Llamar al endpoint
a mano deja la estructura de `runReport` a la vista — `dateRanges`, `dimensions`,
`metrics`, `dimensionFilter`, `orderBys` — que es lo que hay que conocer para
trabajar con GA4 de verdad.

**El periodo acaba ayer, no hoy.** GA4 procesa los datos con horas de retraso.
Comparar el día de hoy a medias contra un día cerrado del periodo anterior siempre
sale peor de lo real y genera alertas falsas.

**Variación `None` cuando la base es cero.** Una página que pasa de 0 a 50
sesiones no ha subido "+∞ %" ni "+100 %": no había base de comparación. Se
etiqueta como landing nueva, que es lo que es.

**La API devuelve todo como string, incluidos los números.** `aplanar_respuesta`
empareja cabeceras con valores y convierte según el tipo declarado
(`TYPE_INTEGER`, `TYPE_FLOAT`). Un `(not set)` en una métrica se convierte en 0 en
lugar de romper el informe.

**Lógica separada de la red.** `reports.py` y `output.py` trabajan sobre datos ya
descargados y se prueban sin credenciales. Solo `client.py` toca la API.

## Tests

```bash
pytest tests/ -v
```

26 tests con la estructura exacta de respuesta de la API, cubriendo aplanado de
tipos, cálculo de periodos, umbrales de alerta y los tres formatos de salida.

## Licencia

MIT

## Related tools

Part of a set of nine open-source tools I use on client work — all Python, MIT, deterministic, no API keys:

[geo-check](https://github.com/angelmunizpedraza/geo-check) · [render-gap](https://github.com/angelmunizpedraza/render-gap) · [llms-txt-generator](https://github.com/angelmunizpedraza/llms-txt-generator) · [citeable](https://github.com/angelmunizpedraza/citeable) · [serp-to-ai-diff](https://github.com/angelmunizpedraza/serp-to-ai-diff) · [ai-visibility-tracker](https://github.com/angelmunizpedraza/ai-visibility-tracker) · [linkjuice](https://github.com/angelmunizpedraza/linkjuice) · [seo-audit](https://github.com/angelmunizpedraza/seo-audit)

`geo-check` asks whether the AI crawlers are allowed in. `render-gap` asks whether anything was there when they arrived. `citeable` asks whether it was worth quoting.
