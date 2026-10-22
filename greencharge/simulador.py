"""
Motor de simulação integrado: sol → inversor/bateria → carregadores → rede.

O simulador é a "física" do eletroposto. A estratégia só DECIDE; quem garante
que a energia fecha (nada surge do nada, bateria respeita limites, perdas de
eficiência) é este módulo. Assim as três estratégias são comparadas de forma
justa, com exatamente o mesmo sol e os mesmos carros.
"""

import copy
import math
import random

from .config import DT_H, PASSOS_DIA, Config
from .estrategias import ESTRATEGIAS, Estado
from .frota import gerar_sessoes
from .solar import simular_pv
from .tarifa import calendario, preco, FORA_PONTA


def preparar_cenario(cfg: Config):
    """Gera sol (real e previsto), clima e sessões — compartilhados por todas as estratégias."""
    c = cfg.cenario
    rng = random.Random(c.semente)
    pv_real, pv_prev, climas = simular_pv(c.data_inicio, c.dias, cfg.sistema.pv_kwp,
                                          cfg.sistema.pv_performance_ratio, c.erro_previsao, rng)
    sessoes = gerar_sessoes(c.data_inicio, c.dias, c, cfg.ambiental.consumo_ve_kwh_km, rng)
    return {
        "pv": [x for dia in pv_real for x in dia],
        "previsao": [x for dia in pv_prev for x in dia],
        "climas": climas,
        "sessoes": sessoes,
        "calendario": calendario(c.data_inicio, c.dias),
    }


def simular(cfg: Config, cenario: dict, nome_estrategia: str) -> dict:
    s_cfg, tar = cfg.sistema, cfg.tarifa
    _, decidir, libera_vaga = ESTRATEGIAS[nome_estrategia]
    PASSOS_AVISO = 2   # motorista libera a vaga até 30 min depois do aviso de carga completa
    sessoes = copy.deepcopy(cenario["sessoes"])
    pv, prev, cal = cenario["pv"], cenario["previsao"], cenario["calendario"]
    postos = [x[2] for x in cal]

    tem_bateria = nome_estrategia != "imediata"
    cap = s_cfg.bat_capacidade_kwh if tem_bateria else 0.0
    soc = cap * s_cfg.bat_soc_inicial
    soc_min, soc_max = cap * s_cfg.bat_soc_min, cap * s_cfg.bat_soc_max
    ef = math.sqrt(s_cfg.bat_eficiencia_ida_volta)   # metade da perda na carga, metade na descarga

    vagas = [None] * s_cfg.n_carregadores
    fila, pendentes = [], list(sessoes)
    registros = []

    for t in range(len(pv)):
        data, passo_dia, posto = cal[t]

        # ── chegadas e saídas ──────────────────────────────────────────────
        while pendentes and pendentes[0].chegada <= t:
            fila.append(pendentes.pop(0))
        for i, s in enumerate(vagas):
            if s is None:
                continue
            if s.saida <= t:
                vagas[i] = None
            elif libera_vaga and s.restante <= 1e-6:
                if s.completou_em < 0:
                    s.completou_em = t
                elif t - s.completou_em >= PASSOS_AVISO:
                    s.liberou_vaga = True
                    vagas[i] = None
        fila = [s for s in fila if s.saida > t]       # quem desistiu de esperar vai embora
        for i in range(len(vagas)):
            if vagas[i] is None and fila:
                s = fila.pop(0)
                s.vaga, s.atendida_em = i, t
                vagas[i] = s
        conectados = [s for s in vagas if s is not None]
        ativos = [s for s in conectados if s.restante > 1e-6]

        # ── decisão da estratégia ──────────────────────────────────────────
        estado = Estado(t, passo_dia, posto, data.weekday() >= 5, pv[t], prev, postos,
                        ativos, soc, cfg)
        dec = decidir(estado)

        # ── física: aplica limites e fecha o balanço de energia ────────────
        ev_kw = {}
        for s in ativos:
            p = max(0.0, min(dec.ev_kw.get(s.id, 0.0), s_cfg.carregador_pmax_kw, s.restante / DT_H))
            ev_kw[s.id] = p
        carga = sum(ev_kw.values())

        pv_para_ev = min(pv[t], carga)
        deficit = carga - pv_para_ev
        bat_para_ev = 0.0
        if tem_bateria and deficit > 0:
            disp = max(0.0, (soc - soc_min) * ef / DT_H)
            bat_para_ev = min(deficit, dec.descarga_max_kw, s_cfg.bat_potencia_kw, disp)
            soc -= bat_para_ev * DT_H / ef
        rede = deficit - bat_para_ev

        excedente = pv[t] - pv_para_ev
        carga_bat = 0.0
        if tem_bateria and dec.carregar_bateria and excedente > 0:
            espaco = max(0.0, (soc_max - soc) / (ef * DT_H))
            carga_bat = min(excedente, s_cfg.bat_potencia_kw, espaco)
            soc += carga_bat * ef * DT_H
        injecao = excedente - carga_bat

        # energia entregue a cada carro, com rastreio da parcela solar
        frac_solar = (pv_para_ev + bat_para_ev) / carga if carga > 0 else 0.0
        for s in ativos:
            e = ev_kw[s.id] * DT_H
            s.entregue += e
            s.entregue_solar += e * frac_solar

        registros.append({
            "t": t,
            "data": data.isoformat(),
            "hora": f"{passo_dia * 15 // 60:02d}:{passo_dia * 15 % 60:02d}",
            "posto": posto,
            "pv_kw": round(pv[t], 3),
            "pv_previsto_kw": round(prev[t], 3),
            "carga_ev_kw": round(carga, 3),
            "pv_para_ev_kw": round(pv_para_ev, 3),
            "bateria_para_ev_kw": round(bat_para_ev, 3),
            "rede_para_ev_kw": round(rede, 3),
            "carga_bateria_kw": round(carga_bat, 3),
            "injecao_kw": round(injecao, 3),
            "soc_pct": round(100 * soc / cap, 1) if cap else 0.0,
            "veiculos_conectados": len(conectados),
            "veiculos_carregando": sum(1 for p in ev_kw.values() if p > 0),
            "veiculos_na_fila": len(fila),
            "preco_kwh": preco(tar, posto),
        })

    return {"estrategia": nome_estrategia,
            "rotulo": ESTRATEGIAS[nome_estrategia][0],
            "registros": registros,
            "sessoes": sessoes,
            "soc_final_kwh": soc,
            "soc_inicial_kwh": cap * s_cfg.bat_soc_inicial}
