"""
Importa a telemetria do protótipo ESP32 (Wokwi) para o Python.

Como usar:
  1. Rode o projeto no Wokwi, deixe passar pelo menos um "dia" (≈ 2,5 min).
  2. Copie todo o texto do Monitor Serial e salve como firmware/log_wokwi.txt
  3. python -m greencharge.importar_wokwi firmware/log_wokwi.txt

Saída: resumo no terminal + gráfico em docs/img/wokwi_telemetria.png.
É a prova de que o controlador embarcado e o motor Python falam a mesma
"língua" (mesmas colunas: pv_para_ev_kw, bateria_para_ev_kw, rede_para_ev_kw...).
"""

import json
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent


def ler_log(caminho: str) -> tuple[list, list, list]:
    passos, eventos, resumos = [], [], []
    for linha in Path(caminho).read_text(encoding="utf-8", errors="ignore").splitlines():
        linha = linha.strip()
        if not linha.startswith("{"):
            continue
        try:
            d = json.loads(linha)
        except json.JSONDecodeError:
            continue
        if "hora" in d:
            passos.append(d)
        elif d.get("resumo"):
            resumos.append(d)
        else:
            eventos.append(d)
    return passos, eventos, resumos


def resumir(passos: list) -> dict:
    dt = 0.25
    solar = sum(p["pv_para_ev_kw"] for p in passos) * dt
    bat = sum(p["bateria_para_ev_kw"] for p in passos) * dt
    rede = sum(p["rede_para_ev_kw"] for p in passos) * dt
    total = solar + bat + rede
    return {
        "passos": len(passos),
        "energia_carros_kwh": round(total, 2),
        "solar_direto_kwh": round(solar, 2),
        "bateria_kwh": round(bat, 2),
        "rede_kwh": round(rede, 2),
        "fracao_solar_pct": round(100 * (solar + bat) / total, 1) if total else 0,
        "rede_na_ponta_kwh": round(sum(p["rede_para_ev_kw"] for p in passos if p["posto"] == "P") * dt, 2),
    }


def plotar(passos: list, destino: Path):
    from . import graficos as g  # usa o mesmo estilo e as mesmas cores
    plt = g.plt
    x = range(len(passos))
    fig, ax = plt.subplots(figsize=(12, 3.8))
    ax.stackplot(x, [p["pv_para_ev_kw"] for p in passos], [p["bateria_para_ev_kw"] for p in passos],
                 [p["rede_para_ev_kw"] for p in passos], colors=[g.SOLAR, g.BATERIA, g.REDE],
                 labels=["Solar direto", "Bateria", "Rede"], step="post", edgecolor="white", linewidth=0.5)
    ax.plot(x, [p["pv_kw"] for p in passos], color=g.TEXTO, ls="--", lw=1.4, label="Geração FV (LDR)",
            drawstyle="steps-post")
    passo_tick = max(1, len(passos) // 12)
    ax.set_xticks(list(x)[::passo_tick], [p["hora"] for p in passos][::passo_tick])
    ax.set_ylabel("kW")
    ax.set_title("Telemetria do controlador ESP32 (Wokwi) importada no Python", loc="left")
    ax.legend(frameon=False, ncol=4, loc="upper right")
    fig.tight_layout()
    destino.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(destino, dpi=160, bbox_inches="tight")
    plt.close(fig)


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return
    passos, eventos, resumos = ler_log(sys.argv[1])
    if not passos:
        print("Nenhuma linha de telemetria encontrada no arquivo.")
        return
    r = resumir(passos)
    print("Telemetria do ESP32 importada:")
    for k, v in r.items():
        print(f"  {k:<22} {v}")
    print(f"  eventos de conexão      {len(eventos)}")
    destino = RAIZ / "docs" / "img" / "wokwi_telemetria.png"
    plotar(passos, destino)
    print(f"Gráfico salvo em {destino.relative_to(RAIZ)}")


if __name__ == "__main__":
    main()
