# Desenvolvimento

Guia para rodar e configurar o Robocopa localmente.

---

## Pré-requisitos

- Python 3.9 ou superior
- Conta no Telegram ([@BotFather](https://t.me/BotFather))
- Conta no [Google AI Studio](https://aistudio.google.com/app/apikey) (Gemini — gratuito)
- Conta no [Tavily](https://tavily.com) ou [Serper](https://serper.dev) (busca web)
- Opcional: [API-Football](https://dashboard.api-football.com), [football-data.org](https://www.football-data.org/client/register)

---

## Instalação

```bash
python -m venv .venv

# Windows (PowerShell)
.\.venv\Scripts\Activate.ps1

pip install -r requirements.txt
copy .env.example .env
```

Preencha o `.env` e execute:

```bash
python main.py
```

---

## Variáveis de ambiente

| Variável | Padrão | Descrição |
|----------|--------|-----------|
| `TELEGRAM_TOKEN` | — | Token do bot (obrigatório) |
| `GEMINI_API_KEY` | — | Chave Google AI Studio (obrigatório) |
| `GEMINI_MODEL` | `gemini-2.5-flash-lite` | Modelo Gemini |
| `SEARCH_PROVIDER` | `tavily` | `tavily` ou `serper` |
| `TAVILY_API_KEY` | — | Chave Tavily |
| `SERPER_API_KEY` | — | Chave Serper (se `SEARCH_PROVIDER=serper`) |
| `MAX_HISTORY` | `10` | Janela de memória (mensagens) |
| `DEBUG` | `false` | Logs extras no terminal |
| `API_FOOTBALL_KEY` | — | Dados estruturados (opcional) |
| `FOOTBALL_DATA_KEY` | — | 2ª fonte de dados da Copa (opcional) |
| `NOTIFICATION_CHECK_INTERVAL_MIN` | `5` | Intervalo do job de alertas |
| `REDIS_URL` | — | Redis local ou Render (opcional) |
| `PORT` | `8080` | Porta do `/health` (local) |
| `RENDER_EXTERNAL_URL` | — | Setado automaticamente no Render |

Referência completa com comentários: [.env.example](../.env.example)

---

## Como obter as chaves de API

### Token do Telegram

1. Abra o Telegram e procure **@BotFather**
2. Envie `/newbot`
3. Escolha nome e username do bot
4. Copie o token para `TELEGRAM_TOKEN`

### Gemini (Google AI Studio) — gratuito

1. Acesse [aistudio.google.com/app/apikey](https://aistudio.google.com/app/apikey)
2. **Create API Key**
3. Cole em `GEMINI_API_KEY`

O `gemini-2.5-flash-lite` tem cota gratuita generosa para uso acadêmico.

### Tavily (recomendado)

1. [tavily.com](https://tavily.com) → conta gratuita
2. **API Keys** → copie para `TAVILY_API_KEY`
3. Plano free: ~1.000 buscas/mês

### Serper (alternativa)

1. [serper.dev](https://serper.dev) → conta gratuita
2. Configure `SEARCH_PROVIDER=serper` e `SERPER_API_KEY`

### API-Football e football-data.org

Opcionais. Sem elas o bot usa fallbacks (`openfootball`, busca web). No plano free da API-Football a temporada 2026 é limitada — `FOOTBALL_DATA_KEY` complementa bem.

---

## Exemplos de interação

### Dados da Copa (ferramenta `dados_copa`)

```
Você: Quando joga o Brasil?
Agente: [consulta proximos_jogos] → data, horário e adversário em BRT
```

### Busca web (transmissão, notícias)

```
Você: Onde assistir Brasil x Argentina no Brasil?
Agente: [web_search] → Globo, SporTV, CazéTV, etc.
```

### Memória de contexto

```
Você: Quero alertas só da Argentina
Agente: [preferencias_copa] → time adicionado
[mais tarde]
Você: Quais são meus alertas?
Agente: lista times e tipos de notificação
```

### Cálculo com Python

```
Você: Qual o aproveitamento do Brasil se tiver 2V 1E e 0D em 3 jogos?
Agente: [execute_python] → percentual calculado
```

---

## Tecnologias

| Pacote | Uso |
|--------|-----|
| Python 3.9+ | Runtime |
| python-telegram-bot 21+ | Bot Telegram (asyncio, JobQueue) |
| google-genai | SDK Gemini + function calling |
| redis | Preferências e alertas (opcional) |
| requests | HTTP para APIs |
| python-dotenv | Variáveis de ambiente |
| colorama | Logs coloridos no terminal (Windows) |
| tzdata | Fuso horário Brasília |

---

## Deploy

Para produção no Render: [DEPLOY.md](DEPLOY.md)

---

[← Arquitetura](ARCHITECTURE.md) · [Índice](README.md) · [Deploy →](DEPLOY.md)
