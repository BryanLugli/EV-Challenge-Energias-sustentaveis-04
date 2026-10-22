"""Indicadores de desempenho (KPIs) de cada estratégia."""

from .config import DT_H, PASSOS_DIA
from .tarifa import PONTA


def calcular(res: dict, cfg, dias: int) -> dict:
    r = res["registros"]
    tar, amb = cfg.tarifa, cfg.ambiental
    fim = dias * PASSOS_DIA

    e = lambda chave: sum(x[chave] for x in r) * DT_H
    pv = e("pv_kw")
    ev = e("carga_ev_kw")
    pv_ev, bat_ev, rede = e("pv_para_ev_kw"), e("bateria_para_ev_kw"), e("rede_para_ev_kw")
    carga_bat, injecao = e("carga_bateria_kw"), e("injecao_kw")
    rede_ponta = sum(x["rede_para_ev_kw"] for x in r if x["posto"] == PONTA) * DT_H

    custo_rede = sum(x["rede_para_ev_kw"] * x["preco_kwh"] for x in r) * DT_H
    credito_injecao = injecao * tar.fora_ponta * tar.fracao_valor_injecao
    # energia que sobrou guardada na bateria no fim do período tem valor (não é perda)
    delta_bat = res["soc_final_kwh"] - res["soc_inicial_kwh"]
    credito_bateria = delta_bat * tar.fora_ponta * tar.fracao_valor_injecao
    custo_liquido = custo_rede - credito_injecao - credito_bateria

    picos = [x["rede_para_ev_kw"] for x in r]
    limite = cfg.sistema.limite_rede_kw

    # Qualidade de serviço: só sessões que terminaram dentro do período
    completas = [s for s in res["sessoes"] if s.saida < fim]
    atendidas = [s for s in completas if s.restante <= 0.05]
    nunca_conectou = [s for s in completas if s.atendida_em < 0]
    pedida = sum(s.energia_pedida for s in completas)
    nao_entregue = sum(s.restante for s in completas)

    co2_rede = rede * amb.fator_emissao_rede_kg_kwh
    co2_se_tudo_rede = ev * amb.fator_emissao_rede_kg_kwh
    km = ev / amb.consumo_ve_kwh_km
    co2_combustao = km / amb.consumo_combustao_km_l * amb.emissao_gasolina_kg_l

    ciclos = (bat_ev + carga_bat) / 2 / cfg.sistema.bat_capacidade_kwh if res["estrategia"] != "imediata" else 0

    return {
        "estrategia": res["estrategia"],
        "rotulo": res["rotulo"],
        "energia_pv_kwh": round(pv, 1),
        "energia_ev_kwh": round(ev, 1),
        "ev_do_pv_kwh": round(pv_ev, 1),
        "ev_da_bateria_kwh": round(bat_ev, 1),
        "ev_da_rede_kwh": round(rede, 1),
        "rede_na_ponta_kwh": round(rede_ponta, 1),
        "injecao_kwh": round(injecao, 1),
        "fracao_solar_pct": round(100 * (pv_ev + bat_ev) / ev, 1) if ev else 0,
        "autoconsumo_pv_pct": round(100 * (pv - injecao) / pv, 1) if pv else 0,
        "pico_rede_kw": round(max(picos), 1),
        "passos_acima_limite": sum(1 for p in picos if p > limite + 1e-6),
        "custo_rede_rs": round(custo_rede, 2),
        "credito_injecao_rs": round(credito_injecao + credito_bateria, 2),
        "custo_liquido_rs": round(custo_liquido, 2),
        "custo_rede_por_kwh_rs": round(custo_rede / ev, 3) if ev else 0,
        "custo_medio_rs_kwh": round(custo_liquido / ev, 3) if ev else 0,
        "co2_rede_kg": round(co2_rede, 1),
        "co2_evitado_vs_rede_kg": round(co2_se_tudo_rede - co2_rede, 1),
        "co2_evitado_vs_combustao_kg": round(co2_combustao - co2_rede, 1),
        "km_eletricos": round(km),
        "litros_gasolina_evitados": round(km / amb.consumo_combustao_km_l),
        "ciclos_bateria": round(ciclos, 1),
        "sessoes_total": len(completas),
        "sessoes_100pct": len(atendidas),
        "sessoes_atendidas_pct": round(100 * len(atendidas) / len(completas), 1) if completas else 0,
        "sessoes_sem_vaga": len(nunca_conectou),
        "energia_pedida_kwh": round(pedida, 1),
        "energia_nao_entregue_kwh": round(nao_entregue, 1),
    }
