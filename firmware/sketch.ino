// ============================================================================
// GreenCharge — Controlador do Eletroposto (EVSE) — Sprint 4
// EV Challenge 2026 — FIAP — Energias Renováveis e Sustentabilidade
//
// Equipe: Bryan Lugli (RM571350) · Beckman Lugli (RM573442) · Guilherme Xavier (RM573053)
//
// Plataforma: ESP32 DevKit V1 (simulado no Wokwi)
//
// O QUE MUDOU EM RELAÇÃO À SPRINT 3
//   Sprint 3: 6 cenários fixos, regra "solar primeiro" e cada carro a 7,4 kW.
//   Sprint 4: o controlador LÊ SENSORES e roda o MESMO algoritmo inteligente
//   do motor Python (greencharge/estrategias.py), em versão embarcada:
//     - sensor de luz (LDR)    → irradiância → geração FV (inversor GoodWe ET)
//     - 2 chaves deslizantes   → veículo conectado no carregador 1 / 2 (GoodWe HCA)
//     - bateria simulada       → GoodWe Lynx Home F (16,38 kWh, LFP)
//     - relógio acelerado      → 1,5 s real = 15 min; percorre a Tarifa Branca
//     - LEDs PWM por carregador→ brilho = potência liberada (perfil OCPP em A)
//     - LEDs de status         → verde (só sol), amarelo (sol+bateria/rede), vermelho (só rede),
//                                azul (bateria descarregando)
//     - LCD 16x2 I2C           → painel local do eletroposto
//     - Serial                 → telemetria em JSON (uma linha a cada 15 min),
//                                que o Python importa: python -m greencharge.importar_wokwi log.txt
// ============================================================================

#include <Wire.h>
#include <LiquidCrystal_I2C.h>
#include <math.h>

// ---------------------------------------------------------------- pinos
const int PIN_LDR      = 34;   // AO do sensor de luminosidade
const int PIN_EV1      = 32;   // chave: carro conectado no carregador 1
const int PIN_EV2      = 33;   // chave: carro conectado no carregador 2
const int LED_SOLAR    = 25;   // verde
const int LED_MISTO    = 26;   // amarelo
const int LED_REDE     = 27;   // vermelho
const int LED_BATERIA  = 14;   // azul
const int LED_PWM_EV1  = 18;   // brilho = potência do carregador 1
const int LED_PWM_EV2  = 19;   // brilho = potência do carregador 2

LiquidCrystal_I2C lcd(0x27, 16, 2);

// ---------------------------------------------------------------- parâmetros (iguais ao config.py)
const float PV_KWP          = 15.0;
const float PERF_RATIO      = 0.80;
const float BAT_CAP_KWH     = 16.38;
const float BAT_SOC_MIN     = 0.10;
const float BAT_SOC_MAX     = 0.95;
const float BAT_P_KW        = 7.5;
const float BAT_EF          = 0.959;  // sqrt(0,92): perda dividida entre carga e descarga
const float P_MAX           = 7.0;    // GoodWe HCA 7 kW
const float P_MIN           = 1.4;    // ~6 A (mínimo da IEC 61851)
const float RESERVA_PONTA   = 8.0;    // kWh guardados para a ponta
const float MARGEM          = 0.85;
const float DT_H            = 0.25;   // passo de 15 min
const float FATOR_CO2       = 0.0247; // kg/kWh — SIN (MCTI, média jan–abr/2025)
const float TARIFA_PONTA    = 1.48030;
const float TARIFA_INTERM   = 0.98450;
const float TARIFA_FP       = 0.66924;
const unsigned long MS_POR_PASSO = 1500;

// ---------------------------------------------------------------- estado
struct Veiculo {
  bool conectado;
  float pedido;     // kWh pedidos
  float restante;   // kWh que faltam
  int saida;        // minuto do dia em que vai embora
  float potencia;   // kW liberados agora
};

Veiculo ev[2];
float socKwh = BAT_CAP_KWH * 0.5;
int minutoDia = 6 * 60;           // começa às 06:00
float acumSolar = 0, acumBat = 0, acumRede = 0, acumCusto = 0;

// ---------------------------------------------------------------- utilidades
const char* posto(int m) {
  if (m >= 17 * 60 + 30 && m < 20 * 60 + 30) return "P";   // ponta
  if ((m >= 16 * 60 + 30 && m < 17 * 60 + 30) || (m >= 20 * 60 + 30 && m < 21 * 60 + 30)) return "I";
  return "FP";
}

float precoAgora(int m) {
  const char* p = posto(m);
  if (p[0] == 'P') return TARIFA_PONTA;
  if (p[0] == 'I') return TARIFA_INTERM;
  return TARIFA_FP;
}

// curva do dia (0 à noite, 1 ao meio-dia solar) — aproximação do céu claro
float formaDoDia(int m) {
  float h = m / 60.0;
  if (h < 5.75 || h > 18.75) return 0;
  float s = sin(M_PI * (h - 5.75) / 13.0);
  return s > 0 ? pow(s, 1.3) : 0;
}

// LDR do Wokwi → lux (fórmula da documentação do componente, adaptada para 3,3 V / 12 bits)
float lerLux() {
  int bruto = analogRead(PIN_LDR);
  float v = bruto / 4095.0 * 3.3;
  if (v >= 3.29) v = 3.29;
  float r = 2000.0 * v / (1.0 - v / 3.3);
  const float GAMMA = 0.7, RL10 = 50;
  return pow(RL10 * 1e3 * pow(10, GAMMA) / r, 1.0 / GAMMA);
}

// claridade do céu 0..1 em escala logarítmica:
// 100 lux (tempestade) → 0 · 1.000 lux → 0,33 · 10.000 lux → 0,67 · 100.000 lux (sol pleno) → 1
float claridadeCeu() {
  float k = (log10(max(lerLux(), 1.0f)) - 2.0) / 3.0;
  return k < 0 ? 0 : (k > 1 ? 1 : k);
}

float geracaoPv(int m, float ceu) {
  return PV_KWP * PERF_RATIO * formaDoDia(m) * ceu;
}

// energia solar que ainda deve vir até o minuto "ate" (previsão local simples)
float previsaoSolarKwh(int de, int ate, float ceu) {
  float e = 0;
  for (int m = de; m < ate && m < 24 * 60; m += 15) e += geracaoPv(m, ceu) * DT_H;
  return e * 0.75;   // só confia em 75% da previsão
}

int passosForaPonta(int de, int ate) {
  int n = 0;
  for (int m = de; m < ate; m += 15) if (posto(m % 1440)[0] == 'F') n++;
  return n > 0 ? n : 1;
}

void lerChaves() {
  bool estado[2] = { digitalRead(PIN_EV1) == LOW, digitalRead(PIN_EV2) == LOW };
  for (int i = 0; i < 2; i++) {
    if (estado[i] && !ev[i].conectado) {          // carro acabou de chegar
      ev[i].conectado = true;
      ev[i].pedido = (i == 0) ? 22.0 : 12.0;       // kWh informados no app
      ev[i].restante = ev[i].pedido;
      ev[i].saida = minutoDia + (i == 0 ? 9 * 60 : 4 * 60);
      Serial.printf("{\"evento\":\"conectou\",\"carregador\":%d,\"pedido_kwh\":%.1f}\n", i + 1, ev[i].pedido);
    }
    if (!estado[i] && ev[i].conectado) {
      ev[i].conectado = false;
      ev[i].potencia = 0;
      Serial.printf("{\"evento\":\"desconectou\",\"carregador\":%d,\"restante_kwh\":%.2f}\n", i + 1, ev[i].restante);
    }
  }
}

// ---------------------------------------------------------------- algoritmo GreenCharge
void decidir(float pv, float ceu) {
  const char* p = posto(minutoDia);
  float totalRestante = 0;
  for (int i = 0; i < 2; i++) if (ev[i].conectado) totalRestante += ev[i].restante;
  if (totalRestante <= 0) totalRestante = 1;

  float soma = 0;
  for (int i = 0; i < 2; i++) {
    Veiculo &v = ev[i];
    v.potencia = 0;
    if (!v.conectado || v.restante <= 0.001) continue;
    float teto = min(P_MAX, v.restante / DT_H);
    int passos = max(1, (v.saida - minutoDia) / 15);
    // 1. garantia de prazo
    float futura = P_MAX * DT_H * (passos - 1) * MARGEM;
    float obrig = max(0.0f, (v.restante - futura) / DT_H);
    // 2. previsão solar rateada
    float sol = previsaoSolarKwh(minutoDia, v.saida, ceu) * v.restante / totalRestante;
    float precisaRede = max(0.0f, v.restante - sol);
    // 3. rede só no fora de ponta, espalhada nas horas baratas
    float pot = obrig;
    if (p[0] == 'F' && precisaRede > 0) {
      float ritmo = max(P_MIN, precisaRede / (passosForaPonta(minutoDia, v.saida) * DT_H));
      pot = max(pot, ritmo);
    }
    v.potencia = min(pot, teto);
    soma += v.potencia;
  }
  // 4. excedente solar para quem tem menos folga
  float sobra = pv - soma;
  int ordem[2] = {0, 1};
  float folga0 = (ev[0].saida - minutoDia) / 60.0 - ev[0].restante / P_MAX;
  float folga1 = (ev[1].saida - minutoDia) / 60.0 - ev[1].restante / P_MAX;
  if (folga1 < folga0) { ordem[0] = 1; ordem[1] = 0; }
  for (int k = 0; k < 2 && sobra > 0; k++) {
    Veiculo &v = ev[ordem[k]];
    if (!v.conectado || v.restante <= 0.001) continue;
    float teto = min(P_MAX, v.restante / DT_H);
    float novo = min(teto, v.potencia + sobra);
    if (novo > 0 && novo < P_MIN) continue;      // abaixo do mínimo o carro não carrega
    sobra -= novo - v.potencia;
    v.potencia = novo;
  }
}

// ---------------------------------------------------------------- física + saídas
void aplicar(float pv) {
  float carga = ev[0].potencia + ev[1].potencia;
  float pvEv = min(pv, carga);
  float deficit = carga - pvEv;

  // bateria: guarda reserva para a ponta até 16h30, depois libera
  float minimo = BAT_CAP_KWH * BAT_SOC_MIN;
  float descargaMax = BAT_P_KW;
  if (minutoDia >= 6 * 60 && minutoDia < 16 * 60 + 30) {
    descargaMax = max(0.0f, min(BAT_P_KW, (socKwh - minimo - RESERVA_PONTA) / DT_H));
  }
  float batEv = 0;
  if (deficit > 0) {
    float disp = max(0.0f, (socKwh - minimo) * BAT_EF / DT_H);
    batEv = min(min(deficit, descargaMax), min(BAT_P_KW, disp));
    socKwh -= batEv * DT_H / BAT_EF;
  }
  float rede = deficit - batEv;
  float excedente = pv - pvEv;
  float cargaBat = min(min(excedente, BAT_P_KW), max(0.0f, (BAT_CAP_KWH * BAT_SOC_MAX - socKwh) / (BAT_EF * DT_H)));
  socKwh += cargaBat * BAT_EF * DT_H;
  float injecao = excedente - cargaBat;

  for (int i = 0; i < 2; i++) {
    if (ev[i].conectado) ev[i].restante = max(0.0f, ev[i].restante - ev[i].potencia * DT_H);
  }
  acumSolar += (pvEv + batEv) * DT_H;
  acumBat += batEv * DT_H;
  acumRede += rede * DT_H;
  acumCusto += rede * DT_H * precoAgora(minutoDia);

  // LEDs de status da fonte de energia
  digitalWrite(LED_SOLAR, LOW); digitalWrite(LED_MISTO, LOW); digitalWrite(LED_REDE, LOW);
  if (carga > 0.01) {
    if (rede < 0.01 && batEv < 0.01) digitalWrite(LED_SOLAR, HIGH);
    else if (pvEv + batEv < 0.01) digitalWrite(LED_REDE, HIGH);
    else digitalWrite(LED_MISTO, HIGH);
  }
  digitalWrite(LED_BATERIA, batEv > 0.01 ? HIGH : LOW);
  // brilho proporcional à potência liberada (em produção: limite de corrente OCPP)
  analogWrite(LED_PWM_EV1, (int)(255 * ev[0].potencia / P_MAX));
  analogWrite(LED_PWM_EV2, (int)(255 * ev[1].potencia / P_MAX));

  // painel LCD
  char l1[24], l2[24];   // folga: o LCD mostra só 16 colunas
  snprintf(l1, sizeof(l1), "%02d:%02d %-2s PV%4.1f", minutoDia / 60, minutoDia % 60, posto(minutoDia), pv);
  snprintf(l2, sizeof(l2), "B%3d%% %3.1f %3.1f", (int)(100 * socKwh / BAT_CAP_KWH), ev[0].potencia, ev[1].potencia);
  l1[16] = l2[16] = 0;
  lcd.setCursor(0, 0); lcd.print(l1);
  lcd.setCursor(0, 1); lcd.print(l2);

  // telemetria JSON — mesmo formato de colunas do simulador Python
  Serial.printf("{\"hora\":\"%02d:%02d\",\"posto\":\"%s\",\"pv_kw\":%.2f,\"soc_pct\":%.1f,"
                "\"ev1_kw\":%.2f,\"ev2_kw\":%.2f,\"pv_para_ev_kw\":%.2f,\"bateria_para_ev_kw\":%.2f,"
                "\"rede_para_ev_kw\":%.2f,\"injecao_kw\":%.2f,\"ev1_restante_kwh\":%.2f,\"ev2_restante_kwh\":%.2f}\n",
                minutoDia / 60, minutoDia % 60, posto(minutoDia), pv, 100 * socKwh / BAT_CAP_KWH,
                ev[0].potencia, ev[1].potencia, pvEv, batEv, rede, injecao,
                ev[0].conectado ? ev[0].restante : 0.0, ev[1].conectado ? ev[1].restante : 0.0);
}

void resumoDoDia() {
  float total = acumSolar + acumRede;
  Serial.printf("{\"resumo\":true,\"solar_kwh\":%.2f,\"bateria_kwh\":%.2f,\"rede_kwh\":%.2f,"
                "\"fracao_solar_pct\":%.1f,\"custo_rede_rs\":%.2f,\"co2_rede_kg\":%.3f}\n",
                acumSolar, acumBat, acumRede, total > 0 ? 100 * acumSolar / total : 0.0, acumCusto,
                acumRede * FATOR_CO2);
  acumSolar = acumBat = acumRede = acumCusto = 0;
}

// ---------------------------------------------------------------- setup / loop
void setup() {
  Serial.begin(115200);
  pinMode(PIN_EV1, INPUT_PULLUP);
  pinMode(PIN_EV2, INPUT_PULLUP);
  int leds[] = {LED_SOLAR, LED_MISTO, LED_REDE, LED_BATERIA, LED_PWM_EV1, LED_PWM_EV2};
  for (int p : leds) pinMode(p, OUTPUT);
  lcd.init();
  lcd.backlight();
  lcd.print("GreenCharge S4");
  lcd.setCursor(0, 1);
  lcd.print("GoodWe ET+HCA");
  delay(1500);
  Serial.println("{\"evento\":\"inicio\",\"versao\":\"sprint4\"}");
}

void loop() {
  lerChaves();
  float ceu = claridadeCeu();
  float pv = geracaoPv(minutoDia, ceu);
  decidir(pv, ceu);
  aplicar(pv);

  minutoDia += 15;
  if (minutoDia >= 24 * 60) {
    minutoDia = 0;
    resumoDoDia();
    for (int i = 0; i < 2; i++) ev[i].saida -= 24 * 60;   // prazos continuam valendo no dia seguinte
  }
  delay(MS_POR_PASSO);
}
