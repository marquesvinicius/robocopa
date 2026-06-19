# Deploy em produção (Render)

Guia operacional para quem for publicar o Robocopa. Uso local não precisa disto — veja o [README](../README.md).

---

## Blueprint no Render

1. Push do projeto para o GitHub
2. [Render Dashboard](https://dashboard.render.com/) → **New → Blueprint**
3. Conecte o repositório — o `render.yaml` cria:
   - **robocopa** (Web Service, Python)
   - **robocopa-redis** (Redis free)
4. Preencha as variáveis com `sync: false`:
   - `TELEGRAM_TOKEN`
   - `GEMINI_API_KEY`
   - `TAVILY_API_KEY` (ou `SERPER_API_KEY` + `SEARCH_PROVIDER=serper`)
   - `API_FOOTBALL_KEY` (opcional)
   - `FOOTBALL_DATA_KEY` (opcional)
5. **Apply** e acompanhe os logs até `[BOT INICIADO]`

O Render define automaticamente `PORT`, `REDIS_URL` e `RENDER_EXTERNAL_URL`.

**Health check:** `https://<seu-app>.onrender.com/health` → `Robocopa OK`

---

## Plano free — o que esperar

- **750 h/mês** de instância web por workspace
- Spin down após 15 min sem tráfego (o bot usa keep-alive interno a cada 14 min **enquanto ligado**)
- Redis free: 25 MB, **sem persistência** — preferências podem zerar em restart
- Não rode o bot no PC e no Render ao mesmo tempo (conflito de token no Telegram)

---

## Horário programado (10h da manhã → 3h da madrugada, BRT)

O bot fica **ligado das 10:05 às 03:05 do dia seguinte** (horário de Brasília) — ou seja, **3 da manhã**, não 15h (3 da tarde).

```
        OFF          ON (~17 horas)                   OFF
  |----------|==========================|----------|
  03:05    09:59  10:05              03:00  03:05  09:59
  (desliga)        (liga)            (ainda on) (desliga)
```

Workflows em `.github/workflows/` (evento `schedule` + `workflow_dispatch` manual):

| Horário (Brasília) | Ação | Cron |
|--------------------|------|------|
| **10:05** (manhã) | Liga | `5 10 * * *` + `timezone: America/Sao_Paulo` |
| **03:05** (madrugada) | Desliga | `5 3 * * *` + `timezone: America/Sao_Paulo` |

O cron usa **fuso de Brasília** direto no YAML (sem converter para UTC na mão). Os minutos `:05` evitam pico de fila no início da hora — recomendação do GitHub Actions.

Economia: ~510 h/mês em vez de ~744 h (24/7).

### Configurar GitHub Actions

1. [Render → API Keys](https://dashboard.render.com/u/settings#api-keys) → criar chave
2. Copiar o **Service ID** do web `robocopa` (`srv-...` na URL do dashboard)
3. No GitHub: **Settings → Secrets → Actions**
   - `RENDER_API_KEY`
   - `RENDER_SERVICE_ID`
4. Push na `master` — a partir daí o horário roda **sozinho** (veja abaixo)

### Automático vs manual

| Modo | Quando roda | Precisa fazer algo? |
|------|-------------|---------------------|
| **Automático** | Todo dia **10:05** liga · **03:05** desliga (BRT) | Não — o `schedule` do GitHub Actions cuida disso |
| **Manual** (`workflow_dispatch`) | Quando **você** clicar em Actions → Run workflow | Só para **testar** ou ligar/desligar **fora** do horário |

O passo “Testar agora” é **uma vez**, para confirmar que os secrets e a API do Render estão certos. O workflow **Ligar** agora também espera até `https://robocopa.onrender.com/health` responder `Robocopa OK` (até ~5 min de cold start no free tier) — o run só fica verde quando o bot estiver de fato no ar.

**Exceção:** se você fizer deploy ou quiser usar o bot entre **03:05 e 10:04**, aí sim pode rodar **Render — Ligar Robocopa** manualmente (ou esperar até as 10h).

> GitHub Actions em repositório **privado** consome minutos do plano free do GitHub; em repo **público** o agendamento costuma ser gratuito. O `schedule` pode atrasar alguns minutos em horários de pico — é normal (não é falha do Render).

O Redis **não** é suspenso. Entre 03:05 e 10:04 o bot fica offline (salvo se você ligar manualmente).

---

## UptimeRobot (opcional)

- Plano free: monitor HTTP a cada 5 min
- URL: `https://robocopa.onrender.com/health`
- Configure **janela de manutenção** 03:05–10:04 BRT para não receber alertas quando o desligamento for intencional
- Não substitui o agendamento — só avisa se cair fora do horário

---

## Chaves no Render

Preencha no painel do serviço as mesmas variáveis do `.env` local. Detalhes passo a passo: [DEVELOPMENT.md](DEVELOPMENT.md#como-obter-as-chaves-de-api)

---

[← Índice](README.md) · [Desenvolvimento](DEVELOPMENT.md)
