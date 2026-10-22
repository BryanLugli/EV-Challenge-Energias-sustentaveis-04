"""
Estratégias de controle do eletroposto.

Cada estratégia recebe o estado do sistema a cada 15 min e devolve:
  * a potência de cada carregador (kW)  → em produção vira um perfil OCPP
    (SetChargingProfile) mandado para o GoodWe HCA;
  * quanto a bateria pode descarregar    → em produção vira o modo de trabalho
    do inversor GoodWe ET (autoconsumo / economia / reserva).

Três estratégias são comparadas no MESMO cenário (mesmo sol, mesmos carros):

  1. imediata     — a lógica da Sprint 2: cada carro puxa 7 kW assim que
                    conecta; o sol é usado se estiver lá na hora. Sem bateria.
  2. autoconsumo  — o mesmo, mas com a bateria GoodWe no modo de fábrica
                    "autoconsumo" (guarda o excedente, descarrega sempre que
                    falta). É o que o hardware faz sozinho, sem o GreenCharge.
  3. greencharge  — o algoritmo inteligente desta sprint (abaixo).
"""

from dataclasses import dataclass

from .config import DT_H, PASSOS_DIA
from .tarifa import FORA_PONTA, INTERMEDIARIO, PONTA


@dataclass
class Estado:
    t: int                     # passo global
    passo_dia: int
    posto: str                 # posto tarifário atual
    fim_de_semana: bool
    pv_kw: float               # geração medida agora
    previsao: list             # previsão de geração (kW) para todos os passos
    postos: list               # posto tarifário de todos os passos
    conectados: list           # sessões conectadas
    soc_kwh: float             # energia na bateria
    cfg: object


@dataclass
class Decisao:
    ev_kw: dict                # id da sessão → kW
    descarga_max_kw: float     # quanto a bateria PODE descarregar para os carros
    carregar_bateria: bool = True


def _limite_sessao(s, cfg) -> float:
    """Não adianta mandar mais potência do que falta para encher o carro."""
    return min(cfg.sistema.carregador_pmax_kw, s.restante / DT_H)


# ─────────────────────────────────────────────────────────────────────────────
# 1) Sprint 2 — carga imediata, sem bateria
# ─────────────────────────────────────────────────────────────────────────────
def imediata(e: Estado) -> Decisao:
    return Decisao({s.id: _limite_sessao(s, e.cfg) for s in e.conectados}, 0.0, carregar_bateria=False)


# ─────────────────────────────────────────────────────────────────────────────
# 2) Bateria no modo autoconsumo de fábrica
# ─────────────────────────────────────────────────────────────────────────────
def autoconsumo(e: Estado) -> Decisao:
    return Decisao({s.id: _limite_sessao(s, e.cfg) for s in e.conectados},
                   e.cfg.sistema.bat_potencia_kw, carregar_bateria=True)


# ─────────────────────────────────────────────────────────────────────────────
# 3) GreenCharge — algoritmo inteligente
# ─────────────────────────────────────────────────────────────────────────────
MARGEM_SEGURANCA = 0.85     # só confia em 85% da capacidade futura do carregador
CONFIANCA_PREVISAO = 0.75   # só conta com 75% do sol previsto
RESERVA_PONTA_KWH = 8.0     # energia guardada na bateria para o horário de ponta
HORIZONTE = PASSOS_DIA      # olha no máximo 24 h à frente


def greencharge(e: Estado) -> Decisao:
    """
    Passo a passo da decisão (a cada 15 min):

    1. GARANTIA: calcula a potência mínima que cada carro precisa AGORA para
       sair com a carga pedida, mesmo se o sol não vier (prazo de saída).
    2. PREVISÃO: estima quanto do que falta pode vir do sol até o carro sair,
       rateando a geração prevista entre os carros conectados.
    3. TARIFA: o que não dá para tirar do sol é puxado da rede só no posto
       fora de ponta, espalhado por todas as horas baratas disponíveis
       ("valley filling") para não criar pico.
    4. SOL AGORA: o excedente solar do momento vai primeiro para quem tem
       menos folga (menor laxity), depois para a bateria, e só então é injetado.
    5. BATERIA: guarda energia solar para a ponta (17h30–20h30) e para a noite;
       só libera a reserva de ponta quando a ponta chega.
    6. PEAK SHAVING: se a importação da rede passar do limite contratado,
       usa a bateria e reduz quem tem folga, nunca quem está no prazo.
    """
    cfg = e.cfg
    s_cfg = cfg.sistema
    pmax, pmin = s_cfg.carregador_pmax_kw, s_cfg.carregador_pmin_kw
    con = e.conectados
    potencias = {s.id: 0.0 for s in con}
    if not con:
        return Decisao(potencias, 0.0, True)

    # ── 1. garantia de prazo ────────────────────────────────────────────────
    obrigatorio = {}
    for s in con:
        passos = max(1, s.saida - e.t)
        capacidade_futura = pmax * DT_H * (passos - 1) * MARGEM_SEGURANCA
        obrigatorio[s.id] = min(_limite_sessao(s, cfg), max(0.0, (s.restante - capacidade_futura) / DT_H))

    # ── 2. previsão solar rateada ───────────────────────────────────────────
    total_restante = sum(s.restante for s in con) or 1.0
    precisa_rede = {}
    for s in con:
        fim = min(s.saida, e.t + HORIZONTE, len(e.previsao))
        sol_janela = sum(e.previsao[k] for k in range(e.t, fim)) * DT_H
        parte = sol_janela * CONFIANCA_PREVISAO * s.restante / total_restante
        precisa_rede[s.id] = max(0.0, s.restante - parte)

    # ── 3. rede só no fora de ponta, espalhada nas horas baratas ───────────
    for s in con:
        p = obrigatorio[s.id]
        if e.posto == FORA_PONTA and precisa_rede[s.id] > 0:
            fim = min(s.saida, e.t + HORIZONTE, len(e.postos))
            passos_baratos = sum(1 for k in range(e.t, fim) if e.postos[k] == FORA_PONTA) or 1
            ritmo = precisa_rede[s.id] / (passos_baratos * DT_H)
            if ritmo > 0:
                ritmo = max(pmin, ritmo)
            p = max(p, min(ritmo, _limite_sessao(s, cfg)))
        potencias[s.id] = p

    # ── 4. excedente solar para quem tem menos folga ───────────────────────
    sobra = e.pv_kw - sum(potencias.values())

    def folga(s):
        return (s.saida - e.t) * DT_H - s.restante / pmax

    for s in sorted(con, key=folga):
        if sobra <= 0:
            break
        teto = _limite_sessao(s, cfg)
        extra = min(teto - potencias[s.id], sobra)
        if extra <= 0:
            continue
        novo = potencias[s.id] + extra
        if 0 < novo < pmin:
            # abaixo da corrente mínima o carro não carrega; só arredonda
            # para cima se a diferença for pequena e estivermos fora de ponta
            if e.posto == FORA_PONTA and pmin - novo < 0.5:
                novo = min(pmin, teto)
            else:
                continue
        sobra -= novo - potencias[s.id]
        potencias[s.id] = novo

    # ── 5. bateria: reserva para a ponta ────────────────────────────────────
    minimo = s_cfg.bat_capacidade_kwh * s_cfg.bat_soc_min
    antes_da_ponta = (not e.fim_de_semana) and e.passo_dia < 66  # antes das 16h30
    if e.posto in (PONTA, INTERMEDIARIO) or e.fim_de_semana:
        descarga = s_cfg.bat_potencia_kw
    elif antes_da_ponta and e.passo_dia >= 24:   # entre 6h e 16h30: guarda a reserva
        livre = e.soc_kwh - (minimo + RESERVA_PONTA_KWH)
        descarga = max(0.0, min(s_cfg.bat_potencia_kw, livre / DT_H))
    else:                                        # madrugada: usa o que sobrou do dia
        descarga = s_cfg.bat_potencia_kw

    # ── 6. peak shaving ─────────────────────────────────────────────────────
    carga = sum(potencias.values())
    disponivel_bat = max(0.0, min(descarga, (e.soc_kwh - minimo) / DT_H))
    rede_estimada = carga - e.pv_kw - disponivel_bat
    if rede_estimada > s_cfg.limite_rede_kw:
        excesso = rede_estimada - s_cfg.limite_rede_kw
        for s in sorted(con, key=folga, reverse=True):     # corta de quem tem mais folga
            corte = min(excesso, potencias[s.id] - obrigatorio[s.id])
            if corte > 0:
                potencias[s.id] -= corte
                excesso -= corte
            if excesso <= 0:
                break

    return Decisao(potencias, descarga, True)


# nome → (rótulo, função, libera_vaga)
# libera_vaga: o app do GreenCharge avisa o motorista quando a carga termina e
# a vaga é liberada em até 30 min para o próximo da fila (gestão de fila).
ESTRATEGIAS = {
    "imediata": ("Sprint 2: carga imediata, sem bateria", imediata, False),
    "autoconsumo": ("Bateria GoodWe em modo autoconsumo", autoconsumo, False),
    "greencharge": ("GreenCharge inteligente (Sprint 4)", greencharge, True),
    # variante usada só na análise de contribuição (ablação): mesmo algoritmo, sem gestão de fila
    "greencharge_sem_fila": ("GreenCharge sem gestão de fila", greencharge, False),
}
PRINCIPAIS = ["imediata", "autoconsumo", "greencharge"]
