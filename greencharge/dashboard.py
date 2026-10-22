"""Gera o painel web (dashboard/index.html) com os dados da simulação embutidos."""

import json
from pathlib import Path

from .config import PASSOS_DIA

TEMPLATE = Path(__file__).with_name("dashboard_template.html")


def gerar(resultados: dict, kpis: dict, cenario: dict, relatorio: dict, dia_demo: int, destino: Path):
    r0 = resultados["greencharge"]["registros"]
    dados = {
        "dias": len(r0) // PASSOS_DIA,
        "passos_dia": PASSOS_DIA,
        "datas": sorted({x["data"] for x in r0}),
        "climas": [{"sol": "sol", "parcial": "parcialmente nublado", "nublado": "nublado"}[c]
                   for c in cenario["climas"]],
        "postos": [x["posto"] for x in r0],
        "pv": [round(x["pv_kw"], 2) for x in r0],
        "dia_demo": dia_demo,
        "rotulos": {"imediata": "Sprint 2 (imediata)", "autoconsumo": "Bateria em autoconsumo",
                    "greencharge": "GreenCharge (Sprint 4)"},
        "series": {
            nome: {
                "s": [round(x["pv_para_ev_kw"], 2) for x in res["registros"]],
                "b": [round(x["bateria_para_ev_kw"], 2) for x in res["registros"]],
                "r": [round(x["rede_para_ev_kw"], 2) for x in res["registros"]],
                "soc": [x["soc_pct"] for x in res["registros"]],
            }
            for nome, res in resultados.items()
        },
        "kpis": kpis,
        "tarifa": relatorio["tarifa"],
        "previsao_amanha": relatorio["previsao_amanha"],
    }
    html = TEMPLATE.read_text(encoding="utf-8").replace("__DADOS__", json.dumps(dados, ensure_ascii=False))
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(html, encoding="utf-8")
