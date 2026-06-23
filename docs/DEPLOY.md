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
- Não rode o bot no PC e no Render ao mesmo tempo (conflito de token no Telegram — log `[CONFLITO TELEGRAM]`)
- Durante **deploy** no Render, esse conflito pode aparecer por ~1 min (instância antiga ainda encerrando); some sozinho se não houver `main.py` local

---

## Modo 24/7 (ativo agora)

Os agendamentos automáticos **10:05 liga / 03:05 desliga** estão **desativados**. O bot deve ficar ligado continuamente no Render (cabe no free tier: 750 h/mês ≈ 24/7 com margem).

### Ligar o bot agora (se estiver suspenso)

Escolha **uma** opção:

1. **GitHub Actions (recomendado)**  
   Repositório → **Actions** → **Render — Ligar Robocopa** → **Run workflow** → Run.  
   Aguarde o job ficar verde (ele testa `https://robocopa.onrender.com/health`).

2. **Painel Render**  
   [dashboard.render.com](https://dashboard.render.com/) → serviço **robocopa** → se aparecer **Resume** / **Retomar**, clique.  
   Ou **Manual Deploy** → **Deploy latest commit** (também sobe uma instância nova).

3. **API Render** (se tiver a chave):
   ```bash
   curl -X POST "https://api.render.com/v1/services/SEU_SERVICE_ID/resume" \
     -H "Authorization: Bearer SUA_RENDER_API_KEY"
   ```

Confirme: `https://robocopa.onrender.com/health` → `Robocopa OK` e no Telegram o bot responde.

### Manter ligado até quinta (ou além)

- **Não rode** o workflow **Render — Desligar Robocopa** (só existe disparo manual).
- Com o `schedule` removido, **nada desliga sozinho** às 3h nem espera até 10h para ligar.
- O keep-alive interno (14 min) evita spin-down por inatividade **enquanto o serviço estiver ativo**.
- Após quinta, para voltar ao horário econômico, reative os blocos `schedule` nos YAML em `.github/workflows/`.

### Workflows manuais (secrets necessários)

| Workflow | Uso |
|----------|-----|
| **Render — Ligar Robocopa** | Resume após suspend ou deploy |
| **Render — Desligar Robocopa** | Suspend voluntário (economizar horas) |

Secrets no GitHub: `RENDER_API_KEY`, `RENDER_SERVICE_ID` ([como obter](#secrets-render-para-actions)).

### Horário programado (desativado)

Antes o bot ligava às **10:05** e desligava às **03:05** (BRT) via `schedule` no GitHub Actions. Isso foi desligado porque o agendamento não estava confiável (atrasos do Actions, secrets, ou serviço já suspenso).

Para **reativar** no futuro, restaure em `.github/workflows/render-resume.yml` e `render-suspend.yml`:

```yaml
on:
  schedule:
    - cron: "5 10 * * *"   # ou "5 3 * * *" no suspend
      timezone: "America/Sao_Paulo"
  workflow_dispatch:
```

Economia com horário: ~510 h/mês vs ~744 h em 24/7.

### Secrets Render para Actions

1. [Render → API Keys](https://dashboard.render.com/u/settings#api-keys) → criar chave
2. Copiar o **Service ID** do web `robocopa` (`srv-...` na URL do dashboard)
3. No GitHub: **Settings → Secrets → Actions** → `RENDER_API_KEY`, `RENDER_SERVICE_ID`

---

## UptimeRobot (opcional)

- Plano free: monitor HTTP a cada 5 min
- URL: `https://robocopa.onrender.com/health`
- Em modo 24/7, alerta se `/health` falhar por mais de alguns minutos
- Se reativar o horário programado, use janela de manutenção 03:05–10:04 BRT

---

## Chaves no Render

Preencha no painel do serviço as mesmas variáveis do `.env` local. Detalhes passo a passo: [DEVELOPMENT.md](DEVELOPMENT.md#como-obter-as-chaves-de-api)

---

[← Índice](README.md) · [Desenvolvimento](DEVELOPMENT.md)
