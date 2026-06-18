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

## Horário programado (10h–03h BRT)

Workflows em `.github/workflows/` ligam/desligam só o **Web Service** via API do Render:

| Horário (Brasília) | Ação |
|--------------------|------|
| 10:00 | Liga (`render-resume.yml`) |
| 03:01 | Desliga (`render-suspend.yml`) |

Economia: ~510 h/mês em vez de ~744 h (24/7).

### Configurar GitHub Actions

1. [Render → API Keys](https://dashboard.render.com/u/settings#api-keys) → criar chave
2. Copiar o **Service ID** do web `robocopa` (`srv-...` na URL do dashboard)
3. No GitHub: **Settings → Secrets → Actions**
   - `RENDER_API_KEY`
   - `RENDER_SERVICE_ID`
4. Push na `main` e teste: Actions → **Render — Ligar Robocopa** → Run workflow

O Redis **não** é suspenso. Entre 03:01 e 09:59 o bot fica offline.

---

## UptimeRobot (opcional)

- Plano free: monitor HTTP a cada 5 min
- URL: `https://robocopa.onrender.com/health`
- Configure **janela de manutenção** 03:01–09:59 BRT para não receber alertas quando o desligamento for intencional
- Não substitui o agendamento — só avisa se cair fora do horário

---

## Chaves no Render

Preencha no painel do serviço as mesmas variáveis do `.env` local. Detalhes passo a passo: [DEVELOPMENT.md](DEVELOPMENT.md#como-obter-as-chaves-de-api)

---

[← Índice](README.md) · [Desenvolvimento](DEVELOPMENT.md)
