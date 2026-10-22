"""
GreenCharge — Sprint 4 — Solução Final Integrada
EV Challenge 2026 · FIAP · Energias Renováveis e Sustentabilidade

Equipe:
  Bryan Lugli      - RM571350
  Beckman Lugli    - RM573442
  Guilherme Xavier - RM573053

Roda a solução completa:
  1. simula 30 dias de geração solar, bateria e recarga de veículos;
  2. compara três estratégias no mesmo cenário;
  3. projeta um ano inteiro;
  4. gera relatório (JSON/CSV), gráficos (PNG) e o painel web (dashboard/index.html).

Uso:
    python main.py                # padrão: 30 dias a partir de 01/10/2026
    python main.py --dias 7       # outro período
    python main.py --sem-anual    # pula a projeção de 365 dias (mais rápido)
"""

import argparse
import csv
import json
from dataclasses import asdict
from pathlib import Path

from greencharge import dashboard, graficos
from greencharge.config import PASSOS_DIA, Config
from greencharge.estrategias import ESTRATEGIAS, PRINCIPAIS
from greencharge.metricas import calcular
from greencharge.simulador import preparar_cenario, simular

RAIZ = Path(__file__).resolve().parent
RES, IMG = RAIZ / "resultados", RAIZ / "docs" / "img"


def rodar(cfg: Config, nomes=PRINCIPAIS):
    cenario = preparar_cenario(cfg)
    resultados = {n: simular(cfg, cenario, n) for n in nomes}
    kpis = {n: calcular(r, cfg, cfg.cenario.dias) for n, r in resultados.items()}
    return cenario, resultados, kpis


def tabela(kpis: dict):
    linhas = [
        ("Recarga vinda do sol (%)", "fracao_solar_pct"),
        ("Autoconsumo da geração FV (%)", "autoconsumo_pv_pct"),
        ("Energia entregue aos carros (kWh)", "energia_ev_kwh"),
        ("Energia da rede (kWh)", "ev_da_rede_kwh"),
        ("Rede no horário de ponta (kWh)", "rede_na_ponta_kwh"),
        ("Pico de demanda da rede (kW)", "pico_rede_kw"),
        ("Intervalos acima do limite", "passos_acima_limite"),
        ("Energia comprada da rede (R$)", "custo_rede_rs"),
        ("Rede por kWh entregue (R$)", "custo_rede_por_kwh_rs"),
        ("Custo líquido por kWh (R$)", "custo_medio_rs_kwh"),
        ("Recargas concluídas (%)", "sessoes_atendidas_pct"),
        ("CO2 emitido pela recarga (kg)", "co2_rede_kg"),
    ]
    nomes = list(kpis)
    w = max(14, max(len(n) for n in nomes) + 2)
    print(f"\n  {'Indicador':<36}" + "".join(f"{n:>{w}}" for n in nomes))
    print("  " + "─" * (36 + w * len(nomes)))
    for rot, k in linhas:
        print(f"  {rot:<36}" + "".join(f"{kpis[n][k]:>{w}}" for n in nomes))


def main():
    ap = argparse.ArgumentParser(description="GreenCharge — Sprint 4")
    ap.add_argument("--dias", type=int, default=30)
    ap.add_argument("--inicio", default="2026-10-01")
    ap.add_argument("--sem-anual", action="store_true")
    args = ap.parse_args()

    cfg = Config()
    cfg.cenario.dias, cfg.cenario.data_inicio = args.dias, args.inicio
    RES.mkdir(exist_ok=True)
    IMG.mkdir(parents=True, exist_ok=True)

    print("=" * 78)
    print("  GreenCharge — Sprint 4 — solução integrada (sol + bateria + recarga inteligente)")
    print("=" * 78)
    print(f"  Período: {args.dias} dias a partir de {args.inicio} · passo de 15 min")

    cenario, resultados, kpis = rodar(cfg, list(ESTRATEGIAS))
    ablacao = {n: kpis[n] for n in ESTRATEGIAS}
    resultados = {n: resultados[n] for n in PRINCIPAIS}
    kpis = {n: kpis[n] for n in PRINCIPAIS}
    print(f"  Cenário: {len(cenario['sessoes'])} sessões de recarga · "
          f"clima: {cenario['climas'].count('sol')} dias de sol, {cenario['climas'].count('parcial')} parciais, "
          f"{cenario['climas'].count('nublado')} nublados")
    tabela(kpis)
    print("\n  Análise de contribuição (mesmo cenário):")
    tabela(ablacao)

    # ── projeção anual ─────────────────────────────────────────────────────
    anual = None
    if not args.sem_anual:
        print("\n  Projetando 365 dias (jan–dez/2026)...")
        cfg_a = Config()
        cfg_a.cenario.dias, cfg_a.cenario.data_inicio = 365, "2026-01-01"
        _, _, kpis_a = rodar(cfg_a)
        anual = {n: {k: kpis_a[n][k] for k in ("fracao_solar_pct", "energia_ev_kwh", "ev_da_rede_kwh",
                                               "rede_na_ponta_kwh", "custo_rede_rs", "custo_rede_por_kwh_rs", "custo_liquido_rs",
                                               "co2_evitado_vs_combustao_kg", "co2_evitado_vs_rede_kg",
                                               "km_eletricos", "litros_gasolina_evitados", "pico_rede_kw",
                                               "ciclos_bateria", "sessoes_atendidas_pct")}
                 for n in kpis_a}
        gc, s2 = anual["greencharge"], anual["imediata"]
        print(f"  Ano: {gc['fracao_solar_pct']}% solar (Sprint 2: {s2['fracao_solar_pct']}%) · "
              f"rede R$ {gc['custo_rede_rs']:.0f} (Sprint 2: R$ {s2['custo_rede_rs']:.0f}) · "
              f"{gc['co2_evitado_vs_combustao_kg'] / 1000:.1f} t CO2 evitadas vs gasolina")

    # ── previsão de amanhã (último dia simulado → usado pelo assistente) ──
    ult = cfg.cenario.dias - 1
    prev = cenario["previsao"][ult * PASSOS_DIA:(ult + 1) * PASSOS_DIA]
    previsao_amanha = [{"hora": f"{p * 15 // 60:02d}:{p * 15 % 60:02d}", "pv_kw": round(v, 2)}
                       for p, v in enumerate(prev) if v > 0]

    relatorio = {
        "projeto": "GreenCharge — Sprint 4",
        "periodo": {"inicio": args.inicio, "dias": args.dias},
        "sistema": asdict(cfg.sistema),
        "tarifa": asdict(cfg.tarifa),
        "ambiental": asdict(cfg.ambiental),
        "kpis": kpis,
        "ablacao": ablacao,
        "projecao_anual": anual,
        "previsao_amanha": previsao_amanha,
    }
    (RES / "relatorio.json").write_text(json.dumps(relatorio, ensure_ascii=False, indent=2), encoding="utf-8")

    for nome, res in resultados.items():
        with open(RES / f"historico_{nome}.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(res["registros"][0]))
            w.writeheader()
            w.writerows(res["registros"])
    with open(RES / "sessoes_greencharge.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["id", "perfil", "chegada", "saida", "pedido_kwh", "entregue_kwh", "solar_kwh", "vaga",
                    "liberou_vaga"])
        for s in resultados["greencharge"]["sessoes"]:
            w.writerow([s.id, s.perfil, s.chegada, s.saida, s.energia_pedida, round(s.entregue, 2),
                        round(s.entregue_solar, 2), s.vaga, s.liberou_vaga])

    # ── gráficos e painel ──────────────────────────────────────────────────
    dia = graficos.escolher_dia_demo(resultados["greencharge"], cenario["climas"])
    graficos.grafico_dia(resultados, dia, IMG / "dia_tipico_comparacao.png")
    graficos.grafico_kpis(kpis, IMG / "kpis_comparacao.png")
    graficos.grafico_semana(resultados["greencharge"], max(0, min(dia - 2, cfg.cenario.dias - 7)),
                            IMG / "semana_bateria.png")
    graficos.grafico_diario(resultados, IMG / "fracao_solar_diaria.png")
    dashboard.gerar(resultados, kpis, cenario, relatorio, dia, RAIZ / "dashboard" / "index.html")

    print("\n  Arquivos gerados:")
    print("    resultados/relatorio.json, resultados/historico_*.csv, resultados/sessoes_greencharge.csv")
    print("    docs/img/*.png")
    print("    dashboard/index.html   ← abra no navegador")
    print("    python -m greencharge.assistente   ← converse com o assistente")
    print("=" * 78)


if __name__ == "__main__":
    main()
