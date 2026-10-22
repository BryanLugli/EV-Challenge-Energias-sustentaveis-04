"""
Geração fotovoltaica simulada.

Evolução em relação à Sprint 2:
  * Sprint 2: curva por hora, ruído aleatório independente a cada hora.
  * Sprint 4: passo de 15 min, céu claro pelo modelo de Haurwitz (GHI em W/m²),
    hora solar verdadeira (equação do tempo + longitude) e clima diário por
    cadeia de Markov (dias de sol / parcialmente nublados / nublados tendem a
    se repetir, como na vida real). Também gera uma PREVISÃO do dia seguinte
    com erro, que é o que o algoritmo inteligente enxerga.

Em produção, a classe FonteSolarGoodWe (fontes_goodwe.py) substitui este
módulo lendo a potência real do inversor.
"""

import math
import random
from datetime import date, timedelta

from .config import LATITUDE, LONGITUDE, MERIDIANO_FUSO, PASSOS_DIA, PASSO_MIN

# Estados de clima: (nome, faixa do índice de claridade diário)
CLIMAS = {
    "sol": (0.85, 1.00),
    "parcial": (0.50, 0.80),
    "nublado": (0.12, 0.35),
}
# Matriz de transição (probabilidade do clima de amanhã dado o de hoje).
# Primavera em SP: maioria dos dias com sol ou parcialmente nublados.
TRANSICAO = {
    "sol": {"sol": 0.60, "parcial": 0.30, "nublado": 0.10},
    "parcial": {"sol": 0.35, "parcial": 0.40, "nublado": 0.25},
    "nublado": {"sol": 0.20, "parcial": 0.40, "nublado": 0.40},
}


def _equacao_do_tempo_min(dia_ano: int) -> float:
    b = math.radians(360 / 365 * (dia_ano - 81))
    return 9.87 * math.sin(2 * b) - 7.53 * math.cos(b) - 1.5 * math.sin(b)


def _declinacao_rad(dia_ano: int) -> float:
    return math.radians(23.45 * math.sin(math.radians(360 / 365 * (284 + dia_ano))))


def cos_zenite(dia_ano: int, hora_relogio: float) -> float:
    """Cosseno do ângulo zenital do sol para a hora do relógio (UTC-3)."""
    correcao_h = (4 * (LONGITUDE - MERIDIANO_FUSO) + _equacao_do_tempo_min(dia_ano)) / 60
    hora_solar = hora_relogio + correcao_h
    angulo_horario = math.radians(15 * (hora_solar - 12))
    lat = math.radians(LATITUDE)
    dec = _declinacao_rad(dia_ano)
    return math.sin(lat) * math.sin(dec) + math.cos(lat) * math.cos(dec) * math.cos(angulo_horario)


def ghi_ceu_claro(dia_ano: int, hora_relogio: float) -> float:
    """Irradiância global horizontal de céu claro (W/m²) — modelo de Haurwitz (1945)."""
    cz = cos_zenite(dia_ano, hora_relogio)
    if cz <= 0.01:
        return 0.0
    return 1098.0 * cz * math.exp(-0.057 / cz)


def gerar_clima(dias: int, rng: random.Random) -> list[str]:
    estado = "sol"
    seq = []
    for _ in range(dias):
        seq.append(estado)
        r, acum = rng.random(), 0.0
        for prox, p in TRANSICAO[estado].items():
            acum += p
            if r <= acum:
                estado = prox
                break
    return seq


def perfil_pv_dia(dia_ano: int, kwp: float, pr: float, clima: str, rng: random.Random) -> list[float]:
    """Potência FV (kW) em cada passo de 15 min de um dia."""
    lo, hi = CLIMAS[clima]
    kt_dia = rng.uniform(lo, hi)
    perfil = []
    nuvem = 1.0
    for p in range(PASSOS_DIA):
        hora = (p + 0.5) * PASSO_MIN / 60
        ghi = ghi_ceu_claro(dia_ano, hora)
        # Nuvens passageiras: ruído correlacionado (AR(1)), mais forte em dias parciais
        amp = {"sol": 0.03, "parcial": 0.18, "nublado": 0.08}[clima]
        nuvem = 0.7 * nuvem + 0.3 * (1 + rng.gauss(0, amp * 2))
        k = max(0.05, min(1.05, kt_dia * nuvem))
        perfil.append(round(max(0.0, kwp * ghi / 1000 * pr * k), 3))
    return perfil


def simular_pv(data_inicio: str, dias: int, kwp: float, pr: float, erro_prev: float, rng: random.Random):
    """
    Retorna (pv_real, pv_previsto, climas):
      pv_real[d][p]      — o que realmente aconteceu
      pv_previsto[d][p]  — previsão disponível no início do dia d (com erro)
    """
    d0 = date.fromisoformat(data_inicio)
    climas = gerar_clima(dias, rng)
    real, prev = [], []
    for d in range(dias):
        dia_ano = (d0 + timedelta(days=d)).timetuple().tm_yday
        perfil = perfil_pv_dia(dia_ano, kwp, pr, climas[d], rng)
        real.append(perfil)
        # Previsão: mesmo formato, energia do dia errada em ±erro (viés diário)
        fator = max(0.2, 1 + rng.gauss(0, erro_prev))
        prev.append([round(x * fator, 3) for x in perfil])
    return real, prev, climas
