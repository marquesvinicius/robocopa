"""
main.py — Entry Point do Robocopa (Copa do Mundo 2026)

Responsabilidades deste módulo:
  - Inicializar o bot Telegram usando python-telegram-bot v20+
  - Registrar os handlers de comandos (/start, /clear, /help, /jogos, /tabela, /aovivo,
    /alertas, /preferencias, /cancelar_alertas, /artilheiros, /matamata)
  - Receber mensagens dos usuários e delegar ao agente ReAct
  - Gerenciar a instância de memória e preferências compartilhadas
  - Executar job periódico de notificações proativas via JobQueue

Arquitetura assíncrona:
  python-telegram-bot v20 usa asyncio internamente.
  A função run_agent() é bloqueante (síncrona), então usamos
  asyncio.to_thread() para executá-la sem bloquear o event loop.
  Isso permite que o bot responda a múltiplos usuários simultaneamente.

Requisito: Python 3.9+ (para asyncio.to_thread e zoneinfo)
"""

import asyncio
import atexit
import logging
import os
import sys
import threading
import time
from collections import defaultdict
from http.server import BaseHTTPRequestHandler, HTTPServer

from dotenv import load_dotenv

# Carrega .env antes de importar agent (o cliente Gemini lê GEMINI_API_KEY na importação)
load_dotenv()

# Terminal Windows (cp1252) não imprime ═/emojis por padrão
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from colorama import init, Fore, Style

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import Conflict
from telegram_format import prepare_telegram_markdown, reply_text_markdown, send_message_markdown
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

from agent import run_agent, get_session_cost, reset_session_cost
from memory import ConversationMemory
from preferences import UserPreferences
from notifications import check_and_send_alerts
from security import check_prompt_injection, log_injection_blocked
from tools.football import (
    proximos_jogos,
    classificacao,
    jogos_ao_vivo,
    jogos_hoje,
    artilheiros,
    mata_mata,
    elenco,
    escalacao,
    api_football_startup_status,
)

# ─────────────────────────────────────────────────────────────
# INICIALIZAÇÃO
# ─────────────────────────────────────────────────────────────

# Inicializa colorama para cores no Windows
init(autoreset=True)

# Suprime logs verbosos do python-telegram-bot e httpx
# (mantém apenas WARNING e acima para não poluir o terminal)
logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.WARNING
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("telegram").setLevel(logging.WARNING)

# ─────────────────────────────────────────────────────────────
# INSTÂNCIA DE MEMÓRIA COMPARTILHADA
# ─────────────────────────────────────────────────────────────
# Uma única instância é compartilhada entre todos os handlers.
# Cada chat_id tem seu próprio histórico dentro da instância.

memory = ConversationMemory(
    max_messages=int(os.getenv("MAX_HISTORY", "10")),
    save_to_file=True
)
preferences = UserPreferences()

# Impede duas instâncias do bot (causa Conflict + respostas duplicadas no Telegram)
_LOCK_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".bot.lock")
_CONFLICT_LOG_INTERVAL_SEC = 60.0
_last_conflict_log_at = 0.0


def _is_render_runtime() -> bool:
    """True quando o processo roda no Render (não no PC local)."""
    return bool(os.getenv("RENDER", "").strip() or os.getenv("RENDER_EXTERNAL_URL", "").strip())


def _local_stop_hint() -> str:
    if sys.platform == "win32":
        return (
            "  Get-CimInstance Win32_Process -Filter \"name='python.exe'\" "
            "| Where-Object { $_.CommandLine -match 'main\\.py' } "
            "| ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"
        )
    return "  pkill -f 'python.*main.py'   # ou feche o outro terminal com Ctrl+C"


def _pid_is_running(pid: int) -> bool:
    """Verifica se um processo ainda está ativo (Windows/Linux)."""
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def acquire_single_instance_lock() -> None:
    """Garante que apenas um main.py use o token do Telegram por vez (só em dev local)."""
    if _is_render_runtime():
        return

    if os.path.exists(_LOCK_FILE):
        try:
            with open(_LOCK_FILE, encoding="utf-8") as f:
                old_pid = int(f.read().strip())
            if _pid_is_running(old_pid):
                print(
                    f"{Fore.RED}[ERRO] Outra instância do bot já está rodando "
                    f"(PID {old_pid}).{Style.RESET_ALL}"
                )
                print(
                    f"{Fore.WHITE}Encerre o outro terminal (Ctrl+C) ou execute:{Style.RESET_ALL}\n"
                    f"  {_local_stop_hint()}\n"
                )
                sys.exit(1)
        except (ValueError, OSError):
            pass

    with open(_LOCK_FILE, "w", encoding="utf-8") as f:
        f.write(str(os.getpid()))


def release_single_instance_lock() -> None:
    try:
        if os.path.exists(_LOCK_FILE):
            with open(_LOCK_FILE, encoding="utf-8") as f:
                if f.read().strip() == str(os.getpid()):
                    os.remove(_LOCK_FILE)
    except OSError:
        pass


atexit.register(release_single_instance_lock)


# ─────────────────────────────────────────────────────────────
# RATE LIMITING
# ─────────────────────────────────────────────────────────────

_rate_timestamps: dict[int, list[float]] = defaultdict(list)
_RATE_LIMIT_MAX = 10   # mensagens por janela
_RATE_LIMIT_WINDOW = 60  # segundos


def _is_rate_limited(chat_id: int) -> bool:
    """Retorna True se o usuário ultrapassou o limite de mensagens."""
    now = time.time()
    ts = _rate_timestamps[chat_id]
    _rate_timestamps[chat_id] = [t for t in ts if now - t < _RATE_LIMIT_WINDOW]
    if len(_rate_timestamps[chat_id]) >= _RATE_LIMIT_MAX:
        return True
    _rate_timestamps[chat_id].append(now)
    return False


# ─────────────────────────────────────────────────────────────
# BOTÕES DE NAVEGAÇÃO INLINE
# ─────────────────────────────────────────────────────────────

def _nav_keyboard() -> InlineKeyboardMarkup:
    """Teclado de navegação rápida exibido após respostas de dados."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📅 Hoje", callback_data="hoje"),
            InlineKeyboardButton("⚽ Ao vivo", callback_data="aovivo"),
        ],
        [
            InlineKeyboardButton("📊 Tabela", callback_data="tabela"),
            InlineKeyboardButton("🎯 Artilheiros", callback_data="artilheiros"),
        ],
    ])


# ─────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────

async def _send_long(update: Update, text: str) -> None:
    """Envia resposta dividindo em chunks se ultrapassar 4096 chars."""
    prepared = prepare_telegram_markdown(text)
    if len(prepared) <= 4096:
        await reply_text_markdown(update.message, text)
    else:
        for i in range(0, len(prepared), 4096):
            chunk = prepared[i:i + 4096]
            await reply_text_markdown(update.message, chunk)
            if i + 4096 < len(prepared):
                await asyncio.sleep(0.3)


async def _reply_with_nav(update: Update, text: str) -> None:
    """Envia resposta com botões de navegação na última mensagem."""
    keyboard = _nav_keyboard()
    prepared = prepare_telegram_markdown(text)
    if len(prepared) <= 4096:
        await reply_text_markdown(update.message, text, reply_markup=keyboard)
    else:
        chunks = [prepared[i:i + 4096] for i in range(0, len(prepared), 4096)]
        for chunk in chunks[:-1]:
            await reply_text_markdown(update.message, chunk)
            await asyncio.sleep(0.3)
        await reply_text_markdown(update.message, chunks[-1], reply_markup=keyboard)


async def _send_nav(bot, chat_id: int, text: str) -> None:
    """Envia mensagem com botões de navegação (usado em callbacks)."""
    keyboard = _nav_keyboard()
    prepared = prepare_telegram_markdown(text)
    if len(prepared) <= 4096:
        await send_message_markdown(bot, chat_id, text, reply_markup=keyboard)
    else:
        chunks = [prepared[i:i + 4096] for i in range(0, len(prepared), 4096)]
        for chunk in chunks[:-1]:
            await send_message_markdown(bot, chat_id, chunk)
            await asyncio.sleep(0.3)
        await send_message_markdown(bot, chat_id, chunks[-1], reply_markup=keyboard)


# ─────────────────────────────────────────────────────────────
# HANDLERS DE COMANDOS
# ─────────────────────────────────────────────────────────────

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handler para /start — limpa histórico e apresenta o Robocopa."""
    chat_id = update.effective_chat.id
    memory.clear(chat_id)
    reset_session_cost(chat_id)

    welcome = (
        "*Bem-vindo ao Robocopa!*\n\n"
        "Sou um assistente especializado na *Copa do Mundo 2026* "
        "(Canada, EUA e Mexico). Uso inteligencia artificial com ferramentas "
        "de dados em tempo real.\n\n"
        "*Importante:* eu entendo apenas *mensagens de texto*. "
        "Imagens, audios, videos, stickers e arquivos nao sao processados.\n\n"
        "*Dica para audios:* se preferir falar, transcreva antes de enviar. "
        "No Telegram, mantenha pressionada a mensagem de voz e toque em "
        "*Transcrever* (disponivel com Telegram Premium em alguns aparelhos). "
        "Outra opcao: use o microfone do teclado do celular para ditar o texto "
        "e envie a mensagem escrita.\n\n"
        "*O que faco:*\n"
        "- Datas, horarios e locais dos jogos (fuso de Brasilia)\n"
        "- Placares ao vivo e resultados\n"
        "- Escalacoes e titulares (~1h antes do jogo)\n"
        "- Classificacao/tabela de grupos com pontos\n"
        "- Artilheiros e assistencias da Copa\n"
        "- Fase eliminatoria (oitavas, quartas, semi, final)\n"
        "- Retrospecto historico entre selecoes (H2H)\n"
        "- Alertas automaticos: aviso pre-jogo, escalacao publicada, resultado final\n"
        "- Onde assistir no Brasil (Globo, SporTV, CazéTV, etc.)\n"
        "- Noticias e contexto sobre a Copa\n\n"
        "*O que NAO faco:*\n"
        "- Outros esportes ou competicoes fora da Copa 2026\n"
        "- Odds, apostas ou previsoes de resultado\n"
        "- Links de transmissao ao vivo ou streaming\n"
        "- Jogos de outras edicoes da Copa (Copa 2022, 2018, etc.) com dados ao vivo\n"
        "- Dados de clubes (Libertadores, Champions, Brasileirao, etc.)\n\n"
        "*Comandos rapidos:*\n"
        "/hoje              jogos de hoje\n"
        "/jogos             proximos jogos\n"
        "/tabela            classificacao dos grupos\n"
        "/grupo A           classificacao de um grupo (A-L)\n"
        "/elenco Brasil     elenco convocado de uma selecao\n"
        "/escalacao Noruega titulares da ultima partida\n"
        "/aovivo            jogos ao vivo agora\n"
        "/artilheiros       tabela de artilheiros\n"
        "/matamata          fase eliminatoria\n"
        "/alertas           suas preferencias de notificacao\n"
        "/preferencias      seguir um time (ex: /preferencias Brasil)\n"
        "/cancelar\\_alertas remover todos os alertas\n"
        "/help              mais exemplos de perguntas\n\n"
        "Pergunte livremente:\n"
        "_\"Quando joga o Brasil?\", \"Quem e o artilheiro?\", "
        "\"Me avise quando a Argentina jogar\"_"
    )

    await update.message.reply_text(welcome, parse_mode="Markdown")
    print(
        f"\n{Fore.GREEN}[BOT] Nova conversa iniciada — "
        f"chat_id={chat_id}{Style.RESET_ALL}"
    )


async def clear_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handler para /clear — limpa o histórico do chat atual e zera custo da sessão."""
    chat_id = update.effective_chat.id
    memory.clear(chat_id)
    reset_session_cost(chat_id)
    await update.message.reply_text(
        "Historico limpo! Comecando uma conversa nova.\n"
        "O que voce gostaria de saber sobre a Copa 2026?"
    )
    print(f"{Fore.YELLOW}[CLEAR] Historico limpo — chat_id={chat_id}{Style.RESET_ALL}")


async def cost_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handler para /custo — exibe o custo acumulado da sessão atual."""
    chat_id = update.effective_chat.id
    session_cost, turns = get_session_cost(chat_id)

    if turns == 0:
        await update.message.reply_text(
            "*Custo da sessao atual*\n\n"
            "Nenhuma interacao realizada ainda nesta sessao.\n"
            "_Envie uma mensagem e depois use /custo para ver o gasto._",
            parse_mode="Markdown"
        )
        return

    model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash-lite")
    await update.message.reply_text(
        f"*Custo da sessao atual*\n\n"
        f"- Interacoes realizadas: *{turns}*\n"
        f"- Custo total: *${session_cost:.6f} USD*\n"
        f"- Custo medio por turno: *${session_cost / turns:.6f} USD*\n"
        f"- Modelo: `{model}`\n\n"
        f"_Use /clear para zerar o contador e iniciar nova sessao._",
        parse_mode="Markdown"
    )
    print(
        f"{Fore.GREEN}[CUSTO] Sessao chat_id={chat_id} — "
        f"${session_cost:.6f} USD em {turns} turno(s){Style.RESET_ALL}"
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handler para /help — exibe exemplos de perguntas."""
    help_text = (
        "*Robocopa — Exemplos de Perguntas*\n\n"
        "*Jogos e horarios:*\n"
        "- \"Quando joga o Brasil?\"\n"
        "- \"Quais os jogos de hoje na Copa?\"\n"
        "- \"Que horas joga Argentina x Franca?\"\n\n"
        "*Resultados e placares:*\n"
        "- \"Qual foi o placar do Brasil ontem?\"\n"
        "- \"Resultado de Alemanha x Espanha\"\n\n"
        "*Tabela e classificacao:*\n"
        "- \"Como esta o grupo do Brasil?\"\n"
        "- \"Quais times estao classificados?\"\n"
        "- \"Classificacao do Grupo A\"\n\n"
        "*Escalacao:*\n"
        "- \"Qual a escalacao do Brasil?\"\n"
        "- \"Quem joga titularmente?\"\n\n"
        "*Transmissao:*\n"
        "- \"Onde assistir Brasil x Argentina?\"\n"
        "- \"Tem jogo na Globo hoje?\"\n\n"
        "*Artilheiros e estatisticas:*\n"
        "- \"Quem e o artilheiro da Copa?\"\n"
        "- \"Quantos gols o Vinicius fez?\"\n\n"
        "*Mata-mata:*\n"
        "- \"Qual o chaveamento das oitavas?\"\n"
        "- \"Quem joga nas quartas de final?\"\n\n"
        "*Retrospecto H2H:*\n"
        "- \"Retrospecto Brasil x Argentina em Copas\"\n"
        "- \"Historico Franca x Alemanha\"\n\n"
        "*Alertas proativos:*\n"
        "- \"Me avise quando o Brasil jogar\"\n"
        "- \"Quero alertas do jogo da Argentina\"\n"
        "- /preferencias Brasil\n"
        "- /alertas (ver configuracoes)\n"
        "- /cancelar\\_alertas\n\n"
        "*Atalhos:*\n"
        "/jogos          - proximos jogos\n"
        "/tabela         - classificacao dos grupos\n"
        "/aovivo         - jogos ao vivo agora\n"
        "/artilheiros    - artilheiros da Copa\n"
        "/elenco         - elenco convocado\n"
        "/escalacao      - titulares da ultima partida\n"
        "/matamata       - fase eliminatoria\n"
        "/alertas        - suas preferencias\n"
        "/preferencias   - adicionar time\n"
        "/custo          - custo em USD da sessao\n"
        "/clear          - limpar historico\n\n"
        "_O raciocinio do agente aparece no terminal, nao aqui._"
    )
    await update.message.reply_text(help_text, parse_mode="Markdown")


async def jogos_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handler para /jogos — exibe os próximos jogos da Copa 2026."""
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    result = await asyncio.to_thread(proximos_jogos, None, 8)
    await _reply_with_nav(update, result)
    print(f"{Fore.CYAN}[/jogos] chat_id={update.effective_chat.id}{Style.RESET_ALL}")


async def hoje_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handler para /hoje — exibe todos os jogos da Copa 2026 de hoje."""
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    result = await asyncio.to_thread(jogos_hoje)
    await _reply_with_nav(update, result)
    print(f"{Fore.CYAN}[/hoje] chat_id={update.effective_chat.id}{Style.RESET_ALL}")


async def tabela_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handler para /tabela — exibe a classificação dos grupos."""
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    result = await asyncio.to_thread(classificacao, None)
    await _reply_with_nav(update, result)
    print(f"{Fore.CYAN}[/tabela] chat_id={update.effective_chat.id}{Style.RESET_ALL}")


async def aovivo_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handler para /aovivo — exibe os jogos em andamento agora."""
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    result = await asyncio.to_thread(jogos_ao_vivo)
    await _reply_with_nav(update, result)
    print(f"{Fore.CYAN}[/aovivo] chat_id={update.effective_chat.id}{Style.RESET_ALL}")


async def artilheiros_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handler para /artilheiros — exibe a tabela de artilheiros."""
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    result = await asyncio.to_thread(artilheiros)
    await _reply_with_nav(update, result)
    print(f"{Fore.CYAN}[/artilheiros] chat_id={update.effective_chat.id}{Style.RESET_ALL}")


async def matamata_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handler para /matamata — exibe a fase eliminatória."""
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    fase = " ".join(context.args).strip().lower() if context.args else ""
    result = await asyncio.to_thread(mata_mata, fase)
    await _reply_with_nav(update, result)
    print(f"{Fore.CYAN}[/matamata] chat_id={update.effective_chat.id}{Style.RESET_ALL}")


async def grupo_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handler para /grupo A — classificação de um grupo específico."""
    if not context.args:
        await update.message.reply_text(
            "Informe o grupo: /grupo A, /grupo B, /grupo C...\n"
            "A Copa 2026 tem grupos de A a L (48 seleções, 12 grupos)."
        )
        return
    grupo = context.args[0].strip().upper()
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    result = await asyncio.to_thread(classificacao, grupo)
    await _reply_with_nav(update, result)
    print(f"{Fore.CYAN}[/grupo {grupo}] chat_id={update.effective_chat.id}{Style.RESET_ALL}")


async def elenco_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handler para /elenco [time] — elenco convocado de uma seleção."""
    if not context.args:
        await update.message.reply_text(
            "Informe a seleção: /elenco Brasil, /elenco Argentina, /elenco Noruega..."
        )
        return
    time_arg = " ".join(context.args).strip()
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    result = await asyncio.to_thread(elenco, time_arg)
    await _reply_with_nav(update, result)
    print(f"{Fore.CYAN}[/elenco {time_arg}] chat_id={update.effective_chat.id}{Style.RESET_ALL}")


async def escalacao_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handler para /escalacao [time] — titulares da última partida da seleção."""
    if not context.args:
        await update.message.reply_text(
            "Informe a seleção: /escalacao Brasil, /escalacao Noruega, /escalacao França..."
        )
        return
    time_arg = " ".join(context.args).strip()
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    result = await asyncio.to_thread(escalacao, time_arg)
    await _reply_with_nav(update, result)
    print(f"{Fore.CYAN}[/escalacao {time_arg}] chat_id={update.effective_chat.id}{Style.RESET_ALL}")


async def alertas_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handler para /alertas — exibe e mostra preferências atuais do usuário."""
    chat_id = update.effective_chat.id
    summary = preferences.format_summary(chat_id)
    tip = (
        '\n\nPara seguir um time, diga: "Me avise quando o Brasil jogar".\n'
        "Ou use /preferencias Brasil"
    )
    await update.message.reply_text(summary + tip, parse_mode="Markdown")
    print(f"{Fore.CYAN}[/alertas] chat_id={chat_id}{Style.RESET_ALL}")


async def preferencias_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handler para /preferencias [time1] [time2] ...
    Sem args: exibe preferências. Com args: adiciona times diretamente.
    """
    from tools.football import _normalize_team

    chat_id = update.effective_chat.id

    if not context.args:
        # Sem argumentos: mostra preferências atuais
        summary = preferences.format_summary(chat_id)
        tip = (
            "\n\n*Dica:* use /preferencias Brasil para adicionar um time.\n"
            'Ou diga ao bot: "Quero alertas do Brasil"'
        )
        await update.message.reply_text(summary + tip, parse_mode="Markdown")
        return

    # Adiciona times passados como argumento
    added, already = [], []
    for t in context.args:
        norm = _normalize_team(t)
        if preferences.add_team(chat_id, norm):
            added.append(norm)
        else:
            already.append(norm)

    msgs = []
    if added:
        msgs.append(f"Agora seguindo: *{', '.join(added)}*.")
    if already:
        msgs.append(f"Ja seguindo: {', '.join(already)}.")
    msgs.append("\nVoce recebera alertas automaticos antes dos jogos desses times.")
    msgs.append("Use /alertas para ver e configurar seus alertas.")

    await update.message.reply_text("\n".join(msgs), parse_mode="Markdown")
    print(
        f"{Fore.CYAN}[/preferencias] chat_id={chat_id} — "
        f"adicionados={added}{Style.RESET_ALL}"
    )


async def cancelar_alertas_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handler para /cancelar_alertas — remove todas as preferências do usuário."""
    chat_id = update.effective_chat.id
    preferences.clear(chat_id)
    await update.message.reply_text(
        "Todas as suas preferencias e alertas foram removidos.\n"
        "Voce nao recebera mais notificacoes automaticas.\n\n"
        "Para reativar, use /preferencias ou diga "
        '"Me avise quando o Brasil jogar".',
        parse_mode="Markdown",
    )
    print(f"{Fore.CYAN}[/cancelar_alertas] chat_id={chat_id}{Style.RESET_ALL}")


# ─────────────────────────────────────────────────────────────
# CALLBACK DE BOTÕES INLINE
# ─────────────────────────────────────────────────────────────

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handler para cliques nos botões de navegação inline."""
    query = update.callback_query
    await query.answer()  # encerra o loading indicator no Telegram

    chat_id = update.effective_chat.id
    await context.bot.send_chat_action(chat_id=chat_id, action="typing")

    _dispatch = {
        "hoje":        jogos_hoje,
        "aovivo":      jogos_ao_vivo,
        "tabela":      lambda: classificacao(None),
        "artilheiros": artilheiros,
        "jogos":       lambda: proximos_jogos(None, 8),
        "matamata":    lambda: mata_mata(""),
    }

    fn = _dispatch.get(query.data)
    if fn is None:
        return

    result = await asyncio.to_thread(fn)
    await _send_nav(context.bot, chat_id, result)
    print(f"{Fore.CYAN}[btn:{query.data}] chat_id={chat_id}{Style.RESET_ALL}")


# ─────────────────────────────────────────────────────────────
# JOB DE NOTIFICAÇÕES PROATIVAS
# ─────────────────────────────────────────────────────────────

async def _notifications_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Job periódico que verifica e envia alertas proativos a todos os assinantes."""
    try:
        await check_and_send_alerts(context.bot, preferences)
    except Exception as e:
        print(f"{Fore.RED}[ALERTAS] Erro no job de notificações: {e}{Style.RESET_ALL}")


# ─────────────────────────────────────────────────────────────
# HANDLER PRINCIPAL DE MENSAGENS
# ─────────────────────────────────────────────────────────────

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handler para mensagens de texto comuns.

    Fluxo:
    1. Filtro de segurança (injeção de prompt) — custo zero de tokens
    2. Exibe indicador "digitando..." no Telegram
    3. Executa run_agent() em thread separada (não bloqueia o event loop)
    4. Envia a resposta final ao usuário (divide se > 4096 chars)
    """
    chat_id = update.effective_chat.id
    user_message = update.message.text

    # ── RATE LIMITING ─────────────────────────────────────────────────────────
    if _is_rate_limited(chat_id):
        await update.message.reply_text(
            "Muitas mensagens em pouco tempo. Aguarde um momento antes de continuar.\n"
            "Ou use os comandos rapidos: /hoje /jogos /tabela /aovivo"
        )
        return
    # ─────────────────────────────────────────────────────────────────────────

    # ── FILTRO DE SEGURANÇA — injeção de prompt ──────────────────────────────
    is_injection, matched_label = check_prompt_injection(user_message)
    if is_injection:
        log_injection_blocked(chat_id, user_message, matched_label)
        await update.message.reply_text(
            "Mensagem bloqueada.\n\n"
            "Detectei uma tentativa de manipulacao das minhas instrucoes de sistema. "
            "Esse tipo de mensagem nao e processado por seguranca.\n\n"
            "Se quiser perguntar sobre a Copa 2026, estou a disposicao!"
        )
        return
    # ────────────────────────────────────────────────────────────────────────

    await context.bot.send_chat_action(chat_id=chat_id, action="typing")

    try:
        response = await asyncio.to_thread(run_agent, user_message, chat_id, memory)
    except Exception as e:
        print(f"{Fore.RED}[ERRO INESPERADO] {type(e).__name__}: {e}{Style.RESET_ALL}")
        response = (
            "Assistente temporariamente indisponivel. Use os comandos diretos:\n\n"
            "/hoje          jogos de hoje\n"
            "/jogos         proximos jogos\n"
            "/tabela        classificacao\n"
            "/aovivo        jogos ao vivo\n"
            "/artilheiros   artilheiros da Copa"
        )

    try:
        await _send_long(update, response)
    except Exception as send_error:
        print(f"{Fore.RED}[ERRO AO ENVIAR] {send_error}{Style.RESET_ALL}")


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Trata erros do polling sem stack trace repetitivo no terminal."""
    global _last_conflict_log_at
    err = context.error
    if isinstance(err, Conflict):
        now = time.time()
        if now - _last_conflict_log_at < _CONFLICT_LOG_INTERVAL_SEC:
            return
        _last_conflict_log_at = now

        print(f"\n{Fore.RED}[CONFLITO TELEGRAM] Duas instancias do bot estao rodando.{Style.RESET_ALL}")
        if _is_render_runtime():
            print(
                f"{Fore.YELLOW}No Render isso costuma ser:{Style.RESET_ALL}\n"
                "  1. Overlap de deploy (instancia antiga ainda encerrando) — normal por ~1 min\n"
                "  2. main.py rodando no seu PC com o MESMO TELEGRAM_TOKEN\n\n"
                "Confira se nao ha python main.py local. O comando PowerShell abaixo "
                "so vale no Windows do seu PC, nao no servidor Render."
            )
        else:
            print(f"{Fore.YELLOW}Encerre todas as copias locais:{Style.RESET_ALL}\n  {_local_stop_hint()}\n")
    else:
        print(f"\n{Fore.RED}[TELEGRAM] {type(err).__name__}: {err}{Style.RESET_ALL}\n")


async def on_startup(application: Application) -> None:
    """Limpa webhook e fila pendente antes do polling."""
    await application.bot.delete_webhook(drop_pending_updates=True)


# ─────────────────────────────────────────────────────────────
# SERVIDOR HTTP DE SAÚDE (Render Web Service keep-alive)
# ─────────────────────────────────────────────────────────────

class _HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path in ("/", "/health"):
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"Robocopa OK")
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, fmt: str, *args: object) -> None:
        pass  # silencia logs do http.server


def _start_health_server() -> int:
    """Inicia servidor HTTP mínimo em thread daemon. Retorna a porta."""
    port = int(os.getenv("PORT", "8080"))
    server = HTTPServer(("0.0.0.0", port), _HealthHandler)
    t = threading.Thread(target=server.serve_forever, daemon=True, name="health-server")
    t.start()
    return port


async def _keepalive_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Pinga o próprio endpoint /health para evitar sleep no Render free tier."""
    url = os.getenv("RENDER_EXTERNAL_URL", "").strip()
    if not url:
        return
    try:
        import requests as _req
        _req.get(f"{url}/health", timeout=10)
    except Exception:
        pass


# ─────────────────────────────────────────────────────────────
# VALIDAÇÃO DE CONFIGURAÇÃO
# ─────────────────────────────────────────────────────────────

def validate_config() -> bool:
    """
    Verifica se as variáveis de ambiente obrigatórias estão configuradas.
    Exibe avisos para chaves opcionais ausentes.

    Returns:
        True se configuração está OK, False caso contrário
    """
    errors = []
    warnings = []

    if not os.getenv("TELEGRAM_TOKEN"):
        errors.append("TELEGRAM_TOKEN nao configurado")

    if not os.getenv("GEMINI_API_KEY"):
        errors.append("GEMINI_API_KEY nao configurado")

    provider = os.getenv("SEARCH_PROVIDER", "tavily").lower()
    if provider == "tavily" and not os.getenv("TAVILY_API_KEY"):
        warnings.append("TAVILY_API_KEY nao configurada — busca web nao funcionara")
    elif provider == "serper" and not os.getenv("SERPER_API_KEY"):
        warnings.append("SERPER_API_KEY nao configurada — busca web nao funcionara")

    if not os.getenv("API_FOOTBALL_KEY"):
        warnings.append(
            "API_FOOTBALL_KEY nao configurada — "
            "dados ao vivo da Copa usarao fallback (openfootball)"
        )

    for error in errors:
        print(f"{Fore.RED}[ERRO] {error}{Style.RESET_ALL}")

    for warning in warnings:
        print(f"{Fore.YELLOW}[AVISO] {warning}{Style.RESET_ALL}")

    return len(errors) == 0


# ─────────────────────────────────────────────────────────────
# INICIALIZAÇÃO DO BOT
# ─────────────────────────────────────────────────────────────

def main() -> None:
    """
    Ponto de entrada principal.
    Configura e inicia o bot Telegram em modo polling.
    """
    print(f"\n{Fore.GREEN}{'=' * 62}")
    print(f"{Fore.GREEN}   ROBOCOPA — Copa do Mundo 2026")
    print(f"{Fore.GREEN}{'=' * 62}{Style.RESET_ALL}")
    print(f"  {Fore.CYAN}Modelo:      {os.getenv('GEMINI_MODEL', 'gemini-2.5-flash-lite')} (Google Gemini)")
    print(f"  {Fore.CYAN}Memoria:     ultimas {os.getenv('MAX_HISTORY', '10')} mensagens")
    print(f"  {Fore.CYAN}Busca:       {os.getenv('SEARCH_PROVIDER', 'tavily')}")
    print(f"  {Fore.CYAN}API-Football: {api_football_startup_status()}")
    fdorg_status = "configurado" if os.getenv("FOOTBALL_DATA_KEY", "").strip() else "sem chave (opcional)"
    print(f"  {Fore.CYAN}football-data: {fdorg_status}")
    print(f"  {Fore.CYAN}Debug:        {os.getenv('DEBUG', 'false')}")
    print(f"  {Fore.CYAN}Notif. job:   a cada {os.getenv('NOTIFICATION_CHECK_INTERVAL_MIN', '5')} min")

    # Inicia servidor de saúde (Render Web Service)
    health_port = _start_health_server()
    render_url = os.getenv("RENDER_EXTERNAL_URL", "")
    print(f"  {Fore.CYAN}Health:       0.0.0.0:{health_port}/health")
    if render_url:
        print(f"  {Fore.CYAN}Render URL:   {render_url}")
    print(f"{Fore.GREEN}{'-' * 62}{Style.RESET_ALL}\n")

    if not validate_config():
        print(f"\n{Fore.RED}Configure o arquivo .env e tente novamente.{Style.RESET_ALL}")
        print(f"{Fore.WHITE}Copie .env.example para .env e preencha as chaves.{Style.RESET_ALL}\n")
        sys.exit(1)

    acquire_single_instance_lock()

    token = os.getenv("TELEGRAM_TOKEN")

    app = (
        Application.builder()
        .token(token)
        .post_init(on_startup)
        .build()
    )

    # Comandos gerais
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("clear", clear_command))
    app.add_handler(CommandHandler("custo", cost_command))
    app.add_handler(CommandHandler("help", help_command))
    # Atalhos Copa 2026 — dados
    app.add_handler(CommandHandler("hoje", hoje_command))
    app.add_handler(CommandHandler("jogos", jogos_command))
    app.add_handler(CommandHandler("tabela", tabela_command))
    app.add_handler(CommandHandler("grupo", grupo_command))
    app.add_handler(CommandHandler("elenco", elenco_command))
    app.add_handler(CommandHandler("escalacao", escalacao_command))
    app.add_handler(CommandHandler("aovivo", aovivo_command))
    app.add_handler(CommandHandler("artilheiros", artilheiros_command))
    app.add_handler(CommandHandler("matamata", matamata_command))
    # Alertas e preferências
    app.add_handler(CommandHandler("alertas", alertas_command))
    app.add_handler(CommandHandler("preferencias", preferencias_command))
    app.add_handler(CommandHandler("cancelar_alertas", cancelar_alertas_command))
    # Botões inline de navegação
    app.add_handler(CallbackQueryHandler(button_callback))
    # Mensagens livres
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_error_handler(error_handler)

    # ── JOB DE NOTIFICAÇÕES PROATIVAS ────────────────────────────
    interval_min = int(os.getenv("NOTIFICATION_CHECK_INTERVAL_MIN", "5"))
    if app.job_queue is not None:
        app.job_queue.run_repeating(
            _notifications_job,
            interval=interval_min * 60,
            first=30,
            name="copa_alerts",
        )
        print(
            f"  {Fore.CYAN}Alertas:      job registrado "
            f"(intervalo={interval_min}min){Style.RESET_ALL}"
        )
        # Keep-alive para Render free tier (pinga o próprio /health a cada 14 min)
        if os.getenv("RENDER_EXTERNAL_URL", "").strip():
            app.job_queue.run_repeating(
                _keepalive_job,
                interval=14 * 60,
                first=90,
                name="keepalive",
            )
            print(f"  {Fore.CYAN}Keep-alive:   job registrado (intervalo=14min){Style.RESET_ALL}")
    else:
        print(
            f"  {Fore.YELLOW}[AVISO] JobQueue nao disponivel. "
            f"Instale: pip install python-telegram-bot[job-queue]{Style.RESET_ALL}"
        )

    print(f"{Fore.GREEN}[BOT INICIADO] Aguardando mensagens no Telegram...{Style.RESET_ALL}")
    if not _is_render_runtime():
        print(f"{Fore.WHITE}Pressione Ctrl+C para encerrar.\n{Style.RESET_ALL}")
    else:
        print(f"{Fore.WHITE}Render: encerramento via SIGTERM no deploy.\n{Style.RESET_ALL}")

    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)


if __name__ == "__main__":
    main()
