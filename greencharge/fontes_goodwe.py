"""
Integração com equipamentos GoodWe.

O GreenCharge foi escrito para que a fonte de dados seja trocável:

  * FonteSimulada  → usada nesta POC (modelo de céu claro + clima).
  * FonteGoodWe    → lê o inversor híbrido GoodWe (ET/EH/BT/BH...) pela rede
                     local, usando a biblioteca open-source `goodwe`
                     (pip install goodwe), a mesma usada pela integração
                     oficial do Home Assistant. Protocolo: UDP 8899 ou
                     Modbus/TCP 502 (dongle LAN+WiFi V2.0).

A lógica de decisão (estrategias.greencharge) não muda nada entre as duas:
ela só recebe "pv_kw" e "soc_kwh". É isso que permite sair da simulação para
o equipamento real trocando uma linha.

Observação honesta: a FonteGoodWe não foi testada contra um inversor físico
(a equipe não tem acesso a um). Os nomes de sensores abaixo seguem a
biblioteca `goodwe` para a família ET; outros modelos podem usar IDs diferentes.
"""

import asyncio


class FonteSimulada:
    """Entrega a geração e o estado da bateria a partir da simulação."""

    def __init__(self, pv_kw: list[float]):
        self._pv = pv_kw

    def ler(self, passo: int) -> dict:
        return {"pv_kw": self._pv[passo], "soc_pct": None}


class FonteGoodWe:
    """Leitura em tempo real de um inversor GoodWe na rede local."""

    # IDs de sensores da biblioteca `goodwe` para inversores híbridos ET
    SENSOR_PV = "ppv"            # potência FV total (W)
    SENSOR_SOC = "battery_soc"   # estado de carga da bateria (%)
    SENSOR_REDE = "active_power"  # potência trocada com a rede (W)

    def __init__(self, ip: str):
        self.ip = ip
        self._inversor = None

    async def _conectar(self):
        import goodwe  # dependência opcional: pip install goodwe

        if self._inversor is None:
            self._inversor = await goodwe.connect(self.ip)
        return self._inversor

    async def ler_async(self) -> dict:
        inv = await self._conectar()
        dados = await inv.read_runtime_data()
        return {
            "pv_kw": dados.get(self.SENSOR_PV, 0) / 1000,
            "soc_pct": dados.get(self.SENSOR_SOC),
            "rede_kw": dados.get(self.SENSOR_REDE, 0) / 1000,
        }

    def ler(self, passo: int = 0) -> dict:
        return asyncio.run(self.ler_async())


def comando_ocpp(id_carregador: int, potencia_kw: float, tensao_v: float = 230.0) -> dict:
    """
    Converte a decisão do GreenCharge em um perfil de recarga OCPP 1.6
    (SetChargingProfile, TxProfile, limite em A). É o comando que um
    servidor OCPP enviaria a um carregador GoodWe HCA ou qualquer EVSE padrão.
    """
    corrente_a = round(potencia_kw * 1000 / tensao_v, 1)
    return {
        "connectorId": id_carregador,
        "csChargingProfiles": {
            "chargingProfileId": 1,
            "stackLevel": 0,
            "chargingProfilePurpose": "TxProfile",
            "chargingProfileKind": "Absolute",
            "chargingSchedule": {
                "chargingRateUnit": "A",
                "chargingSchedulePeriod": [{"startPeriod": 0, "limit": corrente_a}],
            },
        },
    }
