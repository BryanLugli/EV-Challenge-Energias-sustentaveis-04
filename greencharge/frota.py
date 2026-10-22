"""
Demanda de recarga: sessões de veículos elétricos.

Na Sprint 2 a demanda era "N carros conectados por hora, cada um puxando 7,4 kW".
Isso não permite otimizar nada, porque não diz QUANTO cada carro precisa nem
ATÉ QUANDO ele fica. Agora cada veículo é uma sessão com:
  chegada, saída prevista e energia pedida (kWh) — exatamente o que o usuário
  informa no app (ou o que o carregador recebe via OCPP/ISO 15118).
Com isso o controlador sabe quem tem folga para esperar o sol e quem tem pressa.
"""

import math
import random
from dataclasses import dataclass, field
from datetime import date, timedelta

from .config import PASSO_MIN, PASSOS_DIA


@dataclass
class Sessao:
    id: int
    perfil: str              # "trabalho", "morador" ou "rapida"
    chegada: int             # índice do passo (15 min) desde o início da simulação
    saida: int               # passo em que o carro vai embora
    energia_pedida: float    # kWh
    entregue: float = 0.0
    entregue_solar: float = 0.0
    vaga: int = -1
    atendida_em: int = -1    # passo em que conectou (pode esperar vaga)
    completou_em: int = -1   # passo em que a bateria do carro ficou cheia
    liberou_vaga: bool = False
    historico: list = field(default_factory=list)

    @property
    def restante(self) -> float:
        return max(0.0, self.energia_pedida - self.entregue)


def _poisson(lam: float, rng: random.Random) -> int:
    l, k, p = math.exp(-lam), 0, 1.0
    while True:
        p *= rng.random()
        if p <= l:
            return k
        k += 1


def _passo(h: float) -> int:
    return int(round(h * 60 / PASSO_MIN))


def gerar_sessoes(data_inicio: str, dias: int, cen, consumo_kwh_km: float, rng: random.Random) -> list[Sessao]:
    d0 = date.fromisoformat(data_inicio)
    sessoes = []
    sid = 0
    for d in range(dias):
        util = (d0 + timedelta(days=d)).weekday() < 5
        base = d * PASSOS_DIA

        # Quem trabalha no prédio: chega de manhã, fica o dia todo
        n = _poisson(cen.sessoes_trabalho_dia * (1.0 if util else 0.3), rng)
        for _ in range(n):
            chega = rng.gauss(8.3, 0.8)
            fica = rng.uniform(7.0, 10.0)
            km = rng.uniform(25, 70)
            sessoes.append(Sessao(sid, "trabalho", base + _passo(chega), base + _passo(chega + fica),
                                  round(min(40.0, km * consumo_kwh_km), 2)))
            sid += 1

        # Moradores: chegam à noite e saem de manhã
        n = _poisson(cen.sessoes_moradores_dia, rng)
        for _ in range(n):
            chega = rng.gauss(19.0, 1.2)
            sai = 24 + rng.gauss(7.3, 0.7)
            km = rng.uniform(30, 90)
            sessoes.append(Sessao(sid, "morador", base + _passo(chega), base + _passo(sai),
                                  round(min(40.0, km * consumo_kwh_km), 2)))
            sid += 1

        # Visitas rápidas durante o dia
        n = _poisson(cen.sessoes_rapidas_dia, rng)
        for _ in range(n):
            chega = rng.uniform(9.0, 17.0)
            fica = rng.uniform(1.0, 2.5)
            # o app só aceita pedir o que cabe no tempo de permanência (7 kW × horas)
            pedido = min(rng.uniform(4, 10), 0.9 * 7.0 * fica)
            sessoes.append(Sessao(sid, "rapida", base + _passo(chega), base + _passo(chega + fica),
                                  round(pedido, 2)))
            sid += 1

    fim = dias * PASSOS_DIA
    sessoes = [s for s in sessoes if s.chegada < fim]
    for s in sessoes:
        s.saida = min(s.saida, fim)
    sessoes.sort(key=lambda s: s.chegada)
    return sessoes
