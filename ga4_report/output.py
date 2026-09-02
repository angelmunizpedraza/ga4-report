"""Formatos de salida del informe y envío a webhook (n8n, Make, Slack...)."""

from __future__ import annotations

import csv
import io
import json
from dataclasses import asdict
from datetime import date

import requests

from .reports import Resumen

ETIQUETAS = {
    "sessions": "Sesiones",
    "totalUsers": "Usuarios",
    "engagedSessions": "Sesiones con interacción",
    "conversions": "Conversiones",
    "engagementRate": "Tasa de interacción",
}


def _fmt(metrica: str, valor) -> str:
    if metrica == "engagementRate":
        return f"{float(valor) * 100:.1f}%"
    if isinstance(valor, float):
        return f"{valor:,.0f}".replace(",", ".")
    return f"{int(valor):,}".replace(",", ".")


def _var(v: float | None) -> str:
    if v is None:
        return "—"
    signo = "+" if v > 0 else ""
    return f"{signo}{v:.1f}%"


def a_markdown(r: Resumen, titulo: str = "Informe de tráfico orgánico") -> str:
    out = [f"# {titulo}", "", f"**Periodo:** {r.periodo}  ", f"**Comparado con:** {r.periodo_anterior}", ""]

    out += ["## Totales", "", "| Métrica | Actual | Anterior | Variación |", "|---|---:|---:|---:|"]
    for m, etiqueta in ETIQUETAS.items():
        out.append(f"| {etiqueta} | {_fmt(m, r.totales.get(m, 0))} | {_fmt(m, r.totales_anterior.get(m, 0))} | {_var(r.variaciones.get(m))} |")

    if r.alertas:
        out += ["", "## Alertas", ""]
        iconos = {"critica": "🔴", "aviso": "🟠", "positiva": "🟢"}
        for a in r.alertas:
            out.append(f"- {iconos[a.nivel]} `{a.pagina}` — {a.mensaje} ({a.sesiones_anterior} → {a.sesiones_actual})")

    if r.top_landings:
        out += ["", "## Landing pages principales", "", "| Página | Sesiones | Anterior | Var. | Conversiones |", "|---|---:|---:|---:|---:|"]
        for c in r.top_landings:
            out.append(
                f"| `{c.clave}` | {_fmt('sessions', c.actual.get('sessions', 0))} | "
                f"{_fmt('sessions', c.anterior.get('sessions', 0))} | {_var(c.var_sesiones)} | "
                f"{_fmt('conversions', c.actual.get('conversions', 0))} |"
            )

    if r.canales:
        out += ["", "## Sesiones por canal", "", "| Canal | Sesiones | Conversiones |", "|---|---:|---:|"]
        for fila in r.canales:
            out.append(f"| {fila.get('sessionDefaultChannelGroup', '?')} | {_fmt('sessions', fila.get('sessions', 0))} | {_fmt('conversions', fila.get('conversions', 0))} |")

    out += ["", f"_Generado el {date.today():%d/%m/%Y}_", ""]
    return "\n".join(out)


def a_csv(r: Resumen) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["landing_page", "sesiones", "sesiones_anterior", "var_sesiones_pct", "conversiones", "conversiones_anterior", "var_conversiones_pct"])
    for c in r.top_landings:
        w.writerow([
            c.clave,
            c.actual.get("sessions", 0), c.anterior.get("sessions", 0), c.var_sesiones if c.var_sesiones is not None else "",
            c.actual.get("conversions", 0), c.anterior.get("conversions", 0), c.var_conversiones if c.var_conversiones is not None else "",
        ])
    return buf.getvalue()


def a_dict(r: Resumen) -> dict:
    return {
        "periodo": {"inicio": r.periodo.inicio.isoformat(), "fin": r.periodo.fin.isoformat()},
        "periodo_anterior": {"inicio": r.periodo_anterior.inicio.isoformat(), "fin": r.periodo_anterior.fin.isoformat()},
        "totales": r.totales,
        "totales_anterior": r.totales_anterior,
        "variaciones": r.variaciones,
        "alertas": [asdict(a) for a in r.alertas],
        "top_landings": [
            {"pagina": c.clave, "actual": c.actual, "anterior": c.anterior,
             "var_sesiones": c.var_sesiones, "var_conversiones": c.var_conversiones}
            for c in r.top_landings
        ],
        "canales": r.canales,
    }


def enviar_webhook(url: str, r: Resumen, incluir_markdown: bool = True, timeout: int = 30) -> int:
    """Envía el resumen como JSON a un webhook.

    Pensado para n8n: recibe el JSON, y `markdown` ya viene listo para pegarlo
    en un mensaje de Slack, Telegram o WhatsApp sin volver a formatear nada.
    """
    carga = a_dict(r)
    if incluir_markdown:
        carga["markdown"] = a_markdown(r)
    resp = requests.post(url, json=carga, timeout=timeout)
    resp.raise_for_status()
    return resp.status_code
