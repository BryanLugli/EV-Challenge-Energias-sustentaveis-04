"""
Assistente virtual do GreenCharge ("Pergunte ao GreenCharge").

Responde perguntas em português sobre o eletroposto usando os resultados da
simulação (relatorio.json). Funciona de dois jeitos:

  * offline (padrão): reconhece intenções por palavras-chave e responde com
    os números reais do relatório — não precisa de internet nem de chave;
  * com LLM (opcional): se a variável GROQ_API_KEY existir, manda a pergunta
    + o relatório para o modelo openai/gpt-oss-20b na Groq (o mesmo provedor
    que usamos no chatbot EV ChargeOps da disciplina de IA) e devolve a
    resposta em linguagem natural, ancorada nos dados.

Uso:
    python -m greencharge.assistente                      # modo conversa
    python -m greencharge.assistente "quanto co2 evitei?"  # pergunta única
"""

import json
import os
import sys
import unicodedata
from pathlib import Path

RELATORIO = Path(__file__).resolve().parent.parent / "resultados" / "relatorio.json"


def _norm(txt: str) -> str:
    txt = unicodedata.normalize("NFKD", txt.lower())
    return "".join(c for c in txt if not unicodedata.combining(c))


def _br(n: float, casas: int = 0) -> str:
    """Número no formato brasileiro: 1.234,5"""
    return f"{n:,.{casas}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _melhor_horario(rel: dict) -> str:
    prev = rel.get("previsao_amanha", [])
    if not prev:
        return "Ainda não tenho previsão para amanhã."
    picos = sorted(prev, key=lambda x: -x["pv_kw"])[:4]
    horas = sorted(p["hora"] for p in picos)
    return (f"Amanhã o sol deve render mais entre {horas[0]} e {horas[-1]} "
            f"(até {_br(picos[0]['pv_kw'], 1)} kW). Se puder, deixe o carro conectado nesse período: "
            f"a recarga sai praticamente 100% solar. Evite depender da rede entre 17h30 e 20h30 "
            f"(ponta da Tarifa Branca, R$ {_br(rel['tarifa']['ponta'], 2)}/kWh).")


def responder_offline(pergunta: str, rel: dict) -> str:
    q = _norm(pergunta)
    gc = rel["kpis"]["greencharge"]
    base = rel["kpis"]["imediata"]
    if any(k in q for k in ["co2", "carbono", "emiss", "ambient", "clima"]):
        return (f"No período simulado o GreenCharge rodou {_br(gc['km_eletricos'])} km elétricos, evitando cerca de "
                f"{_br(gc['co2_evitado_vs_combustao_kg'])} kg de CO₂ em relação a carros a gasolina "
                f"({_br(gc['litros_gasolina_evitados'])} litros que não foram queimados). "
                f"Da energia usada, {_br(gc['fracao_solar_pct'], 0)}% veio do sol.")
    if any(k in q for k in ["economi", "custo", "conta", "dinheiro", "r$", "reais", "gasto"]):
        return (f"A energia comprada da rede para recarregar caiu de R$ {_br(base['custo_rede_rs'], 2)} "
                f"(lógica da Sprint 2) para R$ {_br(gc['custo_rede_rs'], 2)} com o GreenCharge — "
                f"{_br(100 * (1 - gc['custo_rede_rs'] / base['custo_rede_rs']), 0)}% a menos. "
                f"Quase nada é comprado na ponta: {_br(gc['rede_na_ponta_kwh'], 1)} kWh no mês todo.")
    if any(k in q for k in ["horario", "hora", "quando", "melhor", "agora"]):
        return _melhor_horario(rel)
    if any(k in q for k in ["bateria", "soc", "armazen"]):
        return (f"A bateria GoodWe Lynx Home F ({_br(rel['sistema']['bat_capacidade_kwh'], 2)} kWh) entregou "
                f"{_br(gc['ev_da_bateria_kwh'], 0)} kWh de energia solar guardada para os carros, "
                f"fazendo {_br(gc['ciclos_bateria'], 0)} ciclos no período. Ela fica com uma reserva de "
                f"energia até 16h30 para cobrir o horário de ponta.")
    if any(k in q for k in ["solar", "sol", "renovavel", "painel", "geracao"]):
        return (f"Os {_br(rel['sistema']['pv_kwp'], 0)} kWp geraram {_br(gc['energia_pv_kwh'])} kWh. "
                f"{_br(gc['fracao_solar_pct'], 0)}% da recarga veio do sol (Sprint 2: {_br(base['fracao_solar_pct'], 0)}%) "
                f"e {_br(gc['autoconsumo_pv_pct'], 0)}% da geração foi usada no próprio local.")
    if any(k in q for k in ["pico", "demanda", "limite", "sobrecarga"]):
        return (f"O pico de demanda da rede foi {_br(gc['pico_rede_kw'], 1)} kW, contra {_br(base['pico_rede_kw'], 1)} kW "
                f"na lógica da Sprint 2, que passou do limite contratado de "
                f"{_br(rel['sistema']['limite_rede_kw'], 0)} kW em {base['passos_acima_limite']} intervalos de 15 min.")
    if any(k in q for k in ["fila", "vaga", "esper", "atendid"]):
        return (f"{_br(gc['sessoes_atendidas_pct'], 0)}% das recargas terminaram com a carga pedida "
                f"(Sprint 2: {_br(base['sessoes_atendidas_pct'], 0)}%). O app avisa quando o carro está cheio "
                f"e a vaga é liberada para o próximo da fila.")
    return ("Posso falar sobre: CO₂ evitado, economia na conta, melhor horário para carregar, bateria, "
            "energia solar, pico de demanda e fila de vagas. Pergunte, por exemplo: "
            "\"qual o melhor horário para carregar amanhã?\"")


def responder_llm(pergunta: str, rel: dict) -> str | None:
    chave = os.environ.get("GROQ_API_KEY")
    if not chave:
        return None
    try:
        import requests
    except ImportError:
        return None
    contexto = {k: rel[k] for k in ("kpis", "sistema", "tarifa", "previsao_amanha") if k in rel}
    try:
        resp = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {chave}"},
            json={
                "model": "openai/gpt-oss-20b",
                "temperature": 0.2,
                "messages": [
                    {"role": "system", "content":
                        "Você é o assistente do GreenCharge, um eletroposto com energia solar, bateria GoodWe e "
                        "carregadores GoodWe HCA. Responda em português, em até 4 frases, usando SOMENTE os "
                        "números do JSON abaixo. Se a informação não estiver no JSON, diga que não sabe.\n"
                        + json.dumps(contexto, ensure_ascii=False)},
                    {"role": "user", "content": pergunta},
                ],
            },
            timeout=20,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"].strip()
    except Exception:
        return None   # sem internet ou erro de API: cai no modo offline


def responder(pergunta: str, rel: dict | None = None) -> str:
    rel = rel or json.loads(RELATORIO.read_text(encoding="utf-8"))
    return responder_llm(pergunta, rel) or responder_offline(pergunta, rel)


def main():
    if not RELATORIO.exists():
        print("Rode primeiro: python main.py")
        return
    rel = json.loads(RELATORIO.read_text(encoding="utf-8"))
    modo = "LLM (Groq)" if os.environ.get("GROQ_API_KEY") else "offline"
    if len(sys.argv) > 1:
        print(responder(" ".join(sys.argv[1:]), rel))
        return
    print(f"Pergunte ao GreenCharge ({modo}). Digite 'sair' para encerrar.\n")
    while True:
        try:
            q = input("Você: ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if q.lower() in {"sair", "exit", "quit"}:
            break
        if q:
            print("GreenCharge:", responder(q, rel), "\n")


if __name__ == "__main__":
    main()
