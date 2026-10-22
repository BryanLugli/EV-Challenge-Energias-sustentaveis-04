"""
Testes de consistência física e de regras do GreenCharge.
Rodar:  python -m pytest -q      (ou  python tests/test_greencharge.py)
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from greencharge.config import Config  # noqa: E402
from greencharge.estrategias import PRINCIPAIS  # noqa: E402
from greencharge.simulador import preparar_cenario, simular  # noqa: E402
from greencharge.tarifa import PONTA, posto_tarifario  # noqa: E402
from datetime import date  # noqa: E402

CFG = Config()
CFG.cenario.dias = 10
CEN = preparar_cenario(CFG)
RES = {n: simular(CFG, CEN, n) for n in PRINCIPAIS}


def test_balanco_de_energia_fecha():
    """Toda a energia solar vai para carro, bateria ou rede; carga = solar + bateria + rede."""
    for res in RES.values():
        for r in res["registros"]:
            assert abs(r["pv_kw"] - (r["pv_para_ev_kw"] + r["carga_bateria_kw"] + r["injecao_kw"])) < 0.01
            assert abs(r["carga_ev_kw"] - (r["pv_para_ev_kw"] + r["bateria_para_ev_kw"] + r["rede_para_ev_kw"])) < 0.01
            assert min(r["pv_para_ev_kw"], r["bateria_para_ev_kw"], r["rede_para_ev_kw"], r["injecao_kw"]) >= -1e-9


def test_bateria_respeita_limites():
    s = CFG.sistema
    for nome in ("autoconsumo", "greencharge"):
        for r in RES[nome]["registros"]:
            assert 100 * s.bat_soc_min - 0.1 <= r["soc_pct"] <= 100 * s.bat_soc_max + 0.1
            assert r["bateria_para_ev_kw"] <= s.bat_potencia_kw + 1e-6
            assert r["carga_bateria_kw"] <= s.bat_potencia_kw + 1e-6


def test_bateria_so_carrega_com_sol():
    for r in RES["greencharge"]["registros"]:
        if r["carga_bateria_kw"] > 0:
            assert r["pv_kw"] >= r["carga_bateria_kw"] - 1e-6


def test_greencharge_nao_estoura_limite_da_rede():
    for r in RES["greencharge"]["registros"]:
        assert r["rede_para_ev_kw"] <= CFG.sistema.limite_rede_kw + 1e-6


def test_carros_conectados_saem_carregados():
    """
    Toda sessão que conseguiu vaga sai com a carga pedida — exceto o que era
    fisicamente impossível (carro que esperou na fila e ficou pouco tempo conectado).
    """
    fim = CFG.cenario.dias * 96
    pmax = CFG.sistema.carregador_pmax_kw
    for s in RES["greencharge"]["sessoes"]:
        if s.atendida_em >= 0 and s.saida < fim:
            impossivel = max(0.0, s.energia_pedida - pmax * (s.saida - s.atendida_em) * 0.25)
            assert s.restante <= impossivel + 0.05, (s.id, s.perfil, s.restante, impossivel)


def test_potencia_nunca_passa_do_carregador():
    for r in RES["greencharge"]["registros"]:
        assert r["carga_ev_kw"] <= CFG.sistema.n_carregadores * CFG.sistema.carregador_pmax_kw + 1e-6


def test_tarifa_branca():
    quarta, sabado = date(2026, 10, 21), date(2026, 10, 24)
    assert posto_tarifario(quarta, 18 * 4) == PONTA          # 18:00
    assert posto_tarifario(quarta, 17 * 4) == "intermediario"  # 17:00
    assert posto_tarifario(quarta, 12 * 4) == "fora_ponta"
    assert posto_tarifario(sabado, 18 * 4) == "fora_ponta"     # fim de semana


def test_greencharge_melhor_que_sprint2():
    def frac(nome):
        r = RES[nome]["registros"]
        solar = sum(x["pv_para_ev_kw"] + x["bateria_para_ev_kw"] for x in r)
        return solar / sum(x["carga_ev_kw"] for x in r)
    assert frac("greencharge") > frac("imediata")


if __name__ == "__main__":
    falhas = 0
    for nome, f in list(globals().items()):
        if nome.startswith("test_"):
            try:
                f()
                print("ok  ", nome)
            except AssertionError as e:
                falhas += 1
                print("FALHOU", nome, e)
    sys.exit(1 if falhas else 0)
