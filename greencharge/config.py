"""
GreenCharge — Sprint 4
Parâmetros do sistema integrado (geração + armazenamento + recarga de VEs).

Todos os valores ficam centralizados aqui para que a banca (e a equipe) possa
alterar um número e rodar de novo. Cada parâmetro indica de onde veio.
"""

from dataclasses import dataclass, field


# ─────────────────────────────────────────────────────────────────────────────
# LOCAL
# ─────────────────────────────────────────────────────────────────────────────
LATITUDE = -23.55          # São Paulo
LONGITUDE = -46.63
MERIDIANO_FUSO = -45.0     # UTC-3 → meridiano de referência -45°

# ─────────────────────────────────────────────────────────────────────────────
# PASSO DE SIMULAÇÃO
# ─────────────────────────────────────────────────────────────────────────────
PASSO_MIN = 15                     # resolução de 15 min (mesma do medidor da distribuidora)
DT_H = PASSO_MIN / 60              # passo em horas
PASSOS_DIA = 24 * 60 // PASSO_MIN  # 96 passos por dia


@dataclass
class Sistema:
    """Hardware do eletroposto — tudo compatível com o ecossistema GoodWe."""

    # Fotovoltaico + inversor híbrido GoodWe ET (ex.: GW15K-ET, trifásico)
    pv_kwp: float = 15.0               # potência pico instalada
    pv_performance_ratio: float = 0.80  # perdas de temperatura, sujeira, cabos, inversor

    # Bateria GoodWe Lynx Home F (LFP) — 5 módulos × 3,27 kWh = 16,38 kWh
    bat_capacidade_kwh: float = 16.38
    bat_soc_min: float = 0.10          # reserva para preservar a vida útil (escolha de projeto)
    bat_soc_max: float = 0.95
    bat_potencia_kw: float = 7.5       # limite de carga/descarga configurado no inversor
    bat_eficiencia_ida_volta: float = 0.92  # premissa típica para LFP + inversor
    bat_soc_inicial: float = 0.50

    # Carregadores GoodWe HCA 7 kW (monofásico) — 4 pontos
    n_carregadores: int = 4
    carregador_pmax_kw: float = 7.0
    carregador_pmin_kw: float = 1.4    # ~6 A em 230 V: mínima corrente da IEC 61851

    # Limite contratado de importação da rede (peak shaving)
    limite_rede_kw: float = 22.0


@dataclass
class Tarifa:
    """
    Tarifa Branca B1 — Enel SP, vigente desde 04/07/2026 (REH ANEEL nº 3.596/2026).
    Valores TUSD + TE, sem impostos. Fins de semana são cobrados como fora de ponta.
    """
    ponta: float = 1.48030          # 17:30–20:30 (dias úteis)
    intermediario: float = 0.98450  # 16:30–17:30 e 20:30–21:30 (dias úteis)
    fora_ponta: float = 0.66924     # demais horários
    convencional: float = 0.78938   # B1 convencional, só para referência
    # Valor líquido de 1 kWh injetado na rede (créditos da GD menos Fio B, Lei 14.300).
    # Premissa simplificada: 70% da tarifa fora de ponta.
    fracao_valor_injecao: float = 0.70


@dataclass
class Ambiental:
    # Fator médio de emissão do SIN — média jan–abr/2025 publicada pelo MCTI
    # (0,0237; 0,0248; 0,0215; 0,0289 tCO2/MWh).
    fator_emissao_rede_kg_kwh: float = 0.0247
    # Comparação com carro a combustão (premissas editáveis):
    consumo_ve_kwh_km: float = 0.17         # VE compacto típico
    consumo_combustao_km_l: float = 11.0    # carro flex com gasolina C
    emissao_gasolina_kg_l: float = 2.2      # kg CO2 por litro (ordem de grandeza)


@dataclass
class Cenario:
    data_inicio: str = "2026-10-01"
    dias: int = 30
    semente: int = 42
    # Frota que usa o estacionamento (condomínio misto: quem trabalha de dia + moradores à noite)
    sessoes_trabalho_dia: float = 3.0      # média de VEs que chegam de manhã (dias úteis)
    sessoes_moradores_dia: float = 3.0     # média de VEs que chegam à noite
    sessoes_rapidas_dia: float = 2.0       # visitas curtas durante o dia
    # Previsão solar: erro médio da previsão do dia (0 = previsão perfeita)
    erro_previsao: float = 0.15


@dataclass
class Config:
    sistema: Sistema = field(default_factory=Sistema)
    tarifa: Tarifa = field(default_factory=Tarifa)
    ambiental: Ambiental = field(default_factory=Ambiental)
    cenario: Cenario = field(default_factory=Cenario)
