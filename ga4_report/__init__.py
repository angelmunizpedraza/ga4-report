"""ga4-report: informes automáticos de tráfico orgánico desde la GA4 Data API."""

__version__ = "1.0.0"

from .client import ClienteGA4, GA4Error, Informe, aplanar_respuesta
from .reports import Periodo, ultimos_dias, mes_actual, construir_resumen, detectar_alertas, comparar_por_clave, variacion
from .output import a_markdown, a_csv, a_dict, enviar_webhook

__all__ = [
    "ClienteGA4", "GA4Error", "Informe", "aplanar_respuesta",
    "Periodo", "ultimos_dias", "mes_actual", "construir_resumen", "detectar_alertas", "comparar_por_clave", "variacion",
    "a_markdown", "a_csv", "a_dict", "enviar_webhook",
]
