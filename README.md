# Robocopa — Assistente da Copa do Mundo 2026

Bot Telegram especializado na **Copa do Mundo 2026** (Canadá, EUA e México). Usa um agente ReAct com **Google Gemini** e ferramentas de dados em tempo real (futebol, busca web, alertas).

Trabalho da disciplina **Tópicos em Engenharia de Software** (UNIRV).

---

## Para quem usa o bot

Converse em **texto** (sem imagem, áudio ou arquivos). Pergunte sobre jogos, tabela, escalação, transmissão, alertas, etc.

| Comando | Descrição |
|---------|-----------|
| `/start` | Apresentação |
| `/help` | Exemplos de perguntas |
| `/hoje` | Jogos de hoje |
| `/jogos` | Próximos jogos |
| `/tabela` | Classificação dos grupos |
| `/grupo A` | Um grupo específico |
| `/aovivo` | Jogos ao vivo |
| `/artilheiros` | Artilheiros |
| `/matamata` | Fase eliminatória |
| `/elenco Brasil` | Elenco convocado |
| `/escalacao Noruega` | Titulares da última partida |
| `/alertas` | Suas notificações |
| `/preferencias Brasil` | Seguir um time |
| `/clear` | Limpar histórico |

---

## Início rápido (local)

```bash
python -m venv .venv
.\.venv\Scripts\Activate.ps1          # Windows
pip install -r requirements.txt
copy .env.example .env                # preencha TELEGRAM_TOKEN, GEMINI_API_KEY, TAVILY_API_KEY
python main.py
```

Requisitos: Python 3.9+, contas gratuitas no Telegram, Google AI Studio e Tavily.

---

## Documentação

| Documento | Para quem |
|-----------|-----------|
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Arquitetura, loop ReAct, pilares, estrutura do código |
| [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) | Instalação, `.env`, chaves de API, exemplos |
| [docs/DEPLOY.md](docs/DEPLOY.md) | Deploy no Render, horário 10h–03h, Redis |
| [docs/README.md](docs/README.md) | Índice da pasta `docs/` |

---

## Stack

Python · python-telegram-bot · google-genai · Redis · Tavily · API-Football / football-data.org
