# Arquitetura

## Visão geral

```
┌─────────────────────────────────────────────────────────────┐
│                    USUÁRIO (Telegram)                       │
│           "Quando joga o Brasil na Copa?"                   │
└────────────────────────┬────────────────────────────────────┘
                         │ mensagem
                         ▼
┌─────────────────────────────────────────────────────────────┐
│                      main.py                                │
│         Handlers async + comandos + JobQueue                │
│         asyncio.to_thread → agente sem bloquear o loop      │
│         HTTP /health (Render)                               │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│                      agent.py                               │
│                   AGENTIC LOOP                              │
│                                                             │
│  [system_prompt] + [memory.get_messages()] → Gemini API     │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐    │
│  │  1. THOUGHT      — raciocínio (só no terminal)      │    │
│  │  2. ACTION       — chama uma ferramenta             │    │
│  │  3. OBSERVATION  — recebe resultado                 │    │
│  │  4. (repete se necessário)                          │    │
│  │  5. FINAL ANSWER — resposta limpa no Telegram       │    │
│  └─────────────────────────────────────────────────────┘    │
└──────────┬──────────────────────────┬───────────────────────┘
           │                          │
           ▼                          ▼
┌──────────────────────┐   ┌─────────────────────────┐
│  tools/              │   │  memory.py              │
│  football.py         │   │  ConversationMemory     │
│  web_search.py       │   │  sliding window N msgs  │
│  python_exec.py      │   │  history/chat_*.json    │
└──────────────────────┘   └─────────────────────────┘
           │
           ▼
┌──────────────────────┐   ┌─────────────────────────┐
│  preferences.py      │   │  notifications.py       │
│  Redis ou arquivo    │   │  alertas proativos      │
└──────────────────────┘   └─────────────────────────┘
```

**LLM:** Google Gemini 2.5 Flash Lite (via `google-genai`, function calling nativo).

---

## O Agentic Loop

Loop **manual** inspirado no padrão ReAct da literatura — sem framework ReAct. O agente raciocina antes de responder.

### O que aparece no terminal

```
══════════════════════════════════════════════════════════════
[👤 USUÁRIO]  chat_id=123456789
Quando joga o Brasil na Copa?
──────────────────────────────────────────────────────────────

  💭 THOUGHT  (iteração 1)
  O usuário quer datas de jogos do Brasil na Copa 2026.
  Devo usar dados_copa com intencao proximos_jogos e time Brasil.

  ⚡ ACTION
  Ferramenta: dados_copa
  { "intencao": "proximos_jogos", "time": "Brasil" }

  👁  OBSERVATION
  Próximos jogos de Brasil:
  • Brasil x Marrocos — 20/06/2026 16:00 (Brasília) ...

  ✅ FINAL ANSWER
  O próximo jogo do Brasil é contra Marrocos, dia 20/06 às 16h (Brasília).
```

### O que o usuário vê no Telegram

Apenas a **resposta final** — sem `[Thought]`, sem detalhes de ferramentas.

---

## Três pilares implementados

### Pilar A — Reasoning (Agentic Loop)

- Implementado em `agent.py`
- System prompt em `prompts/system_prompt.txt` instrui o modelo a raciocinar antes de agir
- Pensamento exibido só no terminal; resposta ao usuário é sanitizada

### Pilar B — Memória (Sliding Window)

- Implementado em `memory.py`
- Mantém as últimas `MAX_HISTORY` mensagens (padrão: 10)
- Tool calls intermediários **não** entram no histórico — só pares user/assistant
- Auditoria completa em `history/chat_{id}.json`

### Pilar C — Tool Calling (Function Calling)

Ferramentas expostas ao Gemini:

| Ferramenta | Módulo | Uso |
|------------|--------|-----|
| `dados_copa` | `tools/football.py` | Jogos, tabela, escalação, elenco, H2H, artilheiros |
| `web_search` | `tools/web_search.py` | Notícias, transmissão, contexto em tempo real |
| `execute_python` | `tools/python_exec.py` | Cálculos com sandbox (timeout 10s) |
| `preferencias_copa` | `preferences.py` | Alertas e times favoritos |

---

## Estrutura de arquivos

```
Robocopa/
├── main.py                 # Entry point: bot, comandos, /health, jobs
├── agent.py                # Loop ReAct + Gemini
├── memory.py               # Memória por chat
├── preferences.py          # Preferências e alertas (Redis/arquivo)
├── notifications.py        # Job de notificações proativas
├── security.py             # Anti prompt-injection
├── storage.py              # Cliente Redis compartilhado
├── tools/
│   ├── football.py         # API-Football, football-data, openfootball
│   ├── web_search.py       # Tavily / Serper
│   └── python_exec.py      # Execução Python restrita
├── prompts/
│   └── system_prompt.txt   # Instruções do agente
├── history/                # Histórico JSON (gerado em runtime)
├── render.yaml             # Blueprint Render
├── .github/workflows/      # Agenda 10h–03h BRT (produção)
├── requirements.txt
├── .env.example
└── docs/                   # Documentação técnica
```

---

## Tratamento de erros

| Situação | Comportamento |
|----------|---------------|
| API Gemini indisponível | Mensagem amigável ao usuário, log no terminal |
| Resposta filtrada pelo Gemini | Mensagem de erro amigável |
| Timeout de busca web | Informa usuário, sugere reformular |
| Chave de API ausente | Log ao iniciar, encerra com instrução |
| Código Python inválido | Erro de sintaxe legível |
| Loop infinito no código | Timeout de 10 segundos |
| Padrão perigoso no código | Bloqueio com explicação |
| Resposta > 4096 chars | Divisão em múltiplas mensagens Telegram |
| Duas instâncias do bot (local + Render) | Erro `Conflict` no Telegram |

---

[← Índice da documentação](README.md) · [Desenvolvimento →](DEVELOPMENT.md)
