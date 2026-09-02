"""CLI: python -m ga4_report --property 123456789 --dias 28 --markdown informe.md"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date

from .client import ClienteGA4, GA4Error
from .reports import (ultimos_dias, mes_actual, construir_resumen,
                      peticion_totales, peticion_landing_pages, peticion_por_canal)
from .output import a_markdown, a_csv, a_dict, enviar_webhook


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="ga4-report",
                                description="Informe de tráfico orgánico desde GA4 con comparación de periodos y alertas.")
    p.add_argument("--property", required=True, help="ID numérico de la propiedad GA4 (p. ej. 123456789)")
    p.add_argument("--credenciales", help="ruta al JSON de la cuenta de servicio (o GOOGLE_APPLICATION_CREDENTIALS)")
    rango = p.add_mutually_exclusive_group()
    rango.add_argument("--dias", type=int, default=28, help="últimos N días completos (por defecto 28)")
    rango.add_argument("--mes-actual", action="store_true", help="del día 1 del mes hasta ayer")
    p.add_argument("--todos-los-canales", action="store_true", help="no filtrar por Organic Search")
    p.add_argument("--top", type=int, default=15, help="landing pages a mostrar (por defecto 15)")
    p.add_argument("--markdown", metavar="RUTA", help="guardar informe en Markdown")
    p.add_argument("--csv", metavar="RUTA", help="guardar landing pages en CSV")
    p.add_argument("--json", metavar="RUTA", help="guardar todo en JSON")
    p.add_argument("--webhook", metavar="URL", help="enviar el resumen a un webhook (n8n, Slack...)")
    p.add_argument("-q", "--quiet", action="store_true", help="no imprimir el informe por pantalla")
    args = p.parse_args(argv)

    periodo = mes_actual() if args.mes_actual else ultimos_dias(args.dias)
    anterior = periodo.anterior()
    organico = not args.todos_los_canales

    try:
        cliente = ClienteGA4(args.property, args.credenciales)
        print(f"Consultando propiedad {cliente.property_id}: {periodo} vs {anterior}...", file=sys.stderr)
        totales = cliente.run_report(peticion_totales(periodo, organico))
        totales_ant = cliente.run_report(peticion_totales(anterior, organico))
        landings = cliente.run_report(peticion_landing_pages(periodo, 200, organico))
        landings_ant = cliente.run_report(peticion_landing_pages(anterior, 200, organico))
        canales = cliente.run_report(peticion_por_canal(periodo))
    except GA4Error as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    resumen = construir_resumen(periodo, totales, totales_ant, landings, landings_ant, canales, top=args.top)
    titulo = "Informe de tráfico orgánico" if organico else "Informe de tráfico"
    md = a_markdown(resumen, titulo)

    if not args.quiet:
        print(md)
    if args.markdown:
        open(args.markdown, "w", encoding="utf-8").write(md)
        print(f"Markdown guardado en {args.markdown}", file=sys.stderr)
    if args.csv:
        open(args.csv, "w", encoding="utf-8", newline="").write(a_csv(resumen))
        print(f"CSV guardado en {args.csv}", file=sys.stderr)
    if args.json:
        json.dump(a_dict(resumen), open(args.json, "w", encoding="utf-8"), ensure_ascii=False, indent=2, default=str)
        print(f"JSON guardado en {args.json}", file=sys.stderr)
    if args.webhook:
        codigo = enviar_webhook(args.webhook, resumen)
        print(f"Webhook respondió {codigo}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
