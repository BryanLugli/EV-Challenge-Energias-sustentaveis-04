"""Postos tarifários da Tarifa Branca (Enel SP) e preço de cada passo de 15 min."""

from datetime import date, timedelta

from .config import PASSO_MIN, PASSOS_DIA

PONTA, INTERMEDIARIO, FORA_PONTA = "ponta", "intermediario", "fora_ponta"


def posto_tarifario(data: date, passo_do_dia: int) -> str:
    if data.weekday() >= 5:            # sábado e domingo: tudo fora de ponta
        return FORA_PONTA
    minuto = passo_do_dia * PASSO_MIN
    if 17 * 60 + 30 <= minuto < 20 * 60 + 30:
        return PONTA
    if 16 * 60 + 30 <= minuto < 17 * 60 + 30 or 20 * 60 + 30 <= minuto < 21 * 60 + 30:
        return INTERMEDIARIO
    return FORA_PONTA


def preco(tarifa, posto: str) -> float:
    return {PONTA: tarifa.ponta, INTERMEDIARIO: tarifa.intermediario, FORA_PONTA: tarifa.fora_ponta}[posto]


def calendario(data_inicio: str, dias: int) -> list[tuple[date, int, str]]:
    """Lista (data, passo_do_dia, posto) para todos os passos da simulação."""
    d0 = date.fromisoformat(data_inicio)
    out = []
    for d in range(dias):
        dia = d0 + timedelta(days=d)
        for p in range(PASSOS_DIA):
            out.append((dia, p, posto_tarifario(dia, p)))
    return out
