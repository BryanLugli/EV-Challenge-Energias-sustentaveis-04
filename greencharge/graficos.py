"""Gráficos dos resultados (PNG para o README e para o vídeo)."""

from collections import defaultdict

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from .config import DT_H, PASSOS_DIA  # noqa: E402

# Paleta (cores por PAPEL, fixas em todos os gráficos)
SOLAR = "#1baf7a"      # energia solar direta
BATERIA = "#2a78d6"    # energia solar guardada na bateria
REDE = "#eb6834"       # energia da rede
TEXTO = "#0b0b0b"
TEXTO2 = "#52514e"
GRADE = "#e4e3df"
PONTA = "#f3efe6"
CINZA_1, CINZA_2 = "#b9b8b2", "#8a8983"
DESTAQUE = SOLAR

plt.rcParams.update({
    "font.family": "DejaVu Sans", "font.size": 10, "axes.edgecolor": GRADE,
    "axes.labelcolor": TEXTO2, "xtick.color": TEXTO2, "ytick.color": TEXTO2,
    "axes.spines.top": False, "axes.spines.right": False, "axes.grid": True,
    "grid.color": GRADE, "grid.linewidth": 0.8, "axes.axisbelow": True,
    "axes.titleweight": "bold", "axes.titlecolor": TEXTO, "axes.titlesize": 11,
    "figure.facecolor": "white", "axes.facecolor": "white",
})


def escolher_dia_demo(res_gc: dict, climas: list) -> int:
    """Primeiro dia útil de sol com bastante recarga — bom para mostrar no vídeo."""
    regs = res_gc["registros"]
    melhor, maior = 0, -1
    for d, clima in enumerate(climas):
        dia = regs[d * PASSOS_DIA:(d + 1) * PASSOS_DIA]
        if clima != "sol" or not any(x["posto"] == "ponta" for x in dia):
            continue
        energia = sum(x["carga_ev_kw"] for x in dia)
        if energia > maior:
            melhor, maior = d, energia
    return melhor


def _faixa_ponta(ax, dia_regs):
    horas = [i * 0.25 for i in range(PASSOS_DIA)]
    inicio = None
    for i, x in enumerate(dia_regs + [{"posto": ""}]):
        if x["posto"] == "ponta" and inicio is None:
            inicio = horas[i]
        if x["posto"] != "ponta" and inicio is not None:
            ax.axvspan(inicio, horas[i], color=PONTA, zorder=0, lw=0)
            ax.text((inicio + horas[i]) / 2, 0.97, "ponta", transform=ax.get_xaxis_transform(),
                    ha="center", va="top", fontsize=8, color=TEXTO2)
            inicio = None


def grafico_dia(resultados: dict, dia: int, caminho: str):
    nomes = [("imediata", "Sprint 2 — carga imediata, sem bateria"),
             ("greencharge", "Sprint 4 — GreenCharge inteligente")]
    fig, axes = plt.subplots(1, 2, figsize=(13, 4.6), sharey=True)
    horas = [i * 0.25 for i in range(PASSOS_DIA)]
    ymax = 0
    for ax, (nome, titulo) in zip(axes, nomes):
        regs = resultados[nome]["registros"][dia * PASSOS_DIA:(dia + 1) * PASSOS_DIA]
        s = [x["pv_para_ev_kw"] for x in regs]
        b = [x["bateria_para_ev_kw"] for x in regs]
        r = [x["rede_para_ev_kw"] for x in regs]
        pv = [x["pv_kw"] for x in regs]
        ymax = max(ymax, max(a + c + d for a, c, d in zip(s, b, r)), max(pv))
        _faixa_ponta(ax, regs)
        ax.stackplot(horas, s, b, r, colors=[SOLAR, BATERIA, REDE], step="post",
                     labels=["Solar direto", "Bateria (solar guardado)", "Rede"],
                     edgecolor="white", linewidth=0.6)
        ax.plot(horas, pv, color=TEXTO, lw=1.6, ls="--", label="Geração solar disponível", drawstyle="steps-post")
        e = lambda v: sum(v) * DT_H
        tot = e(s) + e(b) + e(r)
        ax.set_title(f"{titulo}\n{100 * (e(s) + e(b)) / tot:.0f}% solar · {e(r):.0f} kWh da rede", loc="left")
        ax.set_xlim(0, 24)
        ax.set_xticks(range(0, 25, 3), [f"{h}h" for h in range(0, 25, 3)])
        ax.set_xlabel("Hora do dia")
    axes[0].set_ylabel("Potência (kW)")
    for ax in axes:
        ax.set_ylim(0, ymax * 1.12)
    h, l = axes[0].get_legend_handles_labels()
    fig.legend(h, l, loc="lower center", ncol=4, frameon=False, bbox_to_anchor=(0.5, -0.02))
    data = resultados["greencharge"]["registros"][dia * PASSOS_DIA]["data"]
    fig.suptitle(f"De onde vem a energia que carrega os carros — mesmo dia ({data}), mesmo sol, mesmos carros",
                 x=0.01, ha="left", fontsize=12, fontweight="bold", color=TEXTO)
    fig.tight_layout(rect=(0, 0.06, 1, 0.95))
    fig.savefig(caminho, dpi=160, bbox_inches="tight")
    plt.close(fig)


def grafico_kpis(kpis: dict, caminho: str):
    ordem = ["imediata", "autoconsumo", "greencharge"]
    rotulos = ["Sprint 2\n(imediata)", "Bateria em\nautoconsumo", "GreenCharge\n(Sprint 4)"]
    cores = [CINZA_1, CINZA_2, DESTAQUE]
    paineis = [
        ("fracao_solar_pct", "Recarga vinda do sol (%)", "{:.0f}%", "maior é melhor"),
        ("rede_na_ponta_kwh", "Rede no horário de ponta (kWh)", "{:.0f}", "menor é melhor"),
        ("pico_rede_kw", "Pico de demanda da rede (kW)", "{:.1f}", "menor é melhor"),
        ("custo_rede_rs", "Energia comprada da rede (R$)", "R$ {:.0f}", "menor é melhor"),
    ]
    fig, axes = plt.subplots(1, 4, figsize=(14, 3.6))
    for ax, (chave, titulo, fmt, nota) in zip(axes, paineis):
        vals = [kpis[n][chave] for n in ordem]
        bars = ax.bar(range(3), vals, color=cores, width=0.62)
        for bar, v in zip(bars, vals):
            ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height(), fmt.format(v),
                    ha="center", va="bottom", fontsize=9, color=TEXTO, fontweight="bold")
        ax.set_xticks(range(3), rotulos, fontsize=8.5)
        ax.set_title(titulo, loc="left", fontsize=10, pad=20)
        ax.text(0, 1.02, nota, transform=ax.transAxes, fontsize=8.5, color=TEXTO2, va="bottom")
        ax.set_ylim(0, max(vals) * 1.22 if max(vals) > 0 else 1)
        ax.grid(axis="x", visible=False)
    fig.suptitle("Mesmo cenário de 30 dias, três formas de operar o eletroposto",
                 x=0.01, ha="left", fontsize=12, fontweight="bold", color=TEXTO)
    fig.tight_layout(rect=(0, 0, 1, 0.92))
    fig.savefig(caminho, dpi=160, bbox_inches="tight")
    plt.close(fig)


def grafico_semana(res_gc: dict, dia_inicio: int, caminho: str):
    regs = res_gc["registros"][dia_inicio * PASSOS_DIA:(dia_inicio + 7) * PASSOS_DIA]
    x = [i * 0.25 for i in range(len(regs))]
    fig, (a1, a2) = plt.subplots(2, 1, figsize=(13, 5.2), sharex=True, gridspec_kw={"height_ratios": [1.4, 1]})
    a1.fill_between(x, [r["pv_kw"] for r in regs], step="post", color=SOLAR, alpha=0.35, lw=0, label="Geração solar")
    a1.plot(x, [r["carga_ev_kw"] for r in regs], color=TEXTO, lw=1.2, drawstyle="steps-post", label="Recarga dos carros")
    a1.set_ylabel("kW")
    a1.set_title("Uma semana do GreenCharge: o sol enche a bateria de dia e ela alimenta os carros à noite",
                 loc="left")
    a1.legend(loc="upper right", frameon=False, ncol=2)
    a2.plot(x, [r["soc_pct"] for r in regs], color=BATERIA, lw=2, drawstyle="steps-post")
    a2.set_ylabel("Bateria (%)")
    a2.set_ylim(0, 100)
    dias = sorted({r["data"] for r in regs})
    a2.set_xticks([i * 24 for i in range(len(dias))], [d[5:].replace("-", "/") for d in dias])
    a2.set_xlim(0, len(regs) * 0.25)
    fig.tight_layout()
    fig.savefig(caminho, dpi=160, bbox_inches="tight")
    plt.close(fig)


def grafico_diario(resultados: dict, caminho: str):
    fig, ax = plt.subplots(figsize=(13, 3.8))
    estilos = {"imediata": (CINZA_1, "Sprint 2 (imediata)"),
               "autoconsumo": (CINZA_2, "Bateria em autoconsumo"),
               "greencharge": (DESTAQUE, "GreenCharge (Sprint 4)")}
    for nome, (cor, rot) in estilos.items():
        por_dia = defaultdict(lambda: [0.0, 0.0])
        for r in resultados[nome]["registros"]:
            por_dia[r["data"]][0] += r["pv_para_ev_kw"] + r["bateria_para_ev_kw"]
            por_dia[r["data"]][1] += r["carga_ev_kw"]
        dias = sorted(por_dia)
        vals = [100 * por_dia[d][0] / por_dia[d][1] if por_dia[d][1] else 0 for d in dias]
        ax.plot(range(len(dias)), vals, color=cor, lw=2.2 if nome == "greencharge" else 1.6,
                marker="o", ms=4, label=rot)
    ax.set_xticks(range(0, len(dias), 3), [dias[i][8:] + "/" + dias[i][5:7] for i in range(0, len(dias), 3)])
    ax.set_ylabel("Recarga vinda do sol (%)")
    ax.set_ylim(0, 100)
    ax.set_title("Fração solar da recarga, dia a dia", loc="left")
    ax.legend(frameon=False, ncol=3, loc="upper left", bbox_to_anchor=(0, -0.12))
    fig.tight_layout()
    fig.savefig(caminho, dpi=160, bbox_inches="tight")
    plt.close(fig)
