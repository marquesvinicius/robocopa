"""
telegram_format.py — Formatação de texto para o Markdown legado do Telegram.

O Telegram usa *negrito* e _itálico_ (um marcador), enquanto LLMs e GitHub usam **negrito**.
Este módulo normaliza o texto antes do envio e faz fallback para texto puro se o parse falhar.
"""

import re

from telegram.error import BadRequest

_MARKDOWN_BOLD = re.compile(r"\*\*(.+?)\*\*", re.DOTALL)
_MARKDOWN_ITALIC = re.compile(r"__(.+?)__", re.DOTALL)
_BULLET_ITALIC = re.compile(r"^(\s*)\*\s+\*([^*\n]+)\*", re.MULTILINE)
_BULLET_PLAIN = re.compile(r"^(\s*)\*\s+(?!\*)", re.MULTILINE)

_STRIP_BOLD_DBL = re.compile(r"\*\*(.+?)\*\*", re.DOTALL)
_STRIP_BOLD = re.compile(r"\*(.+?)\*", re.DOTALL)
_STRIP_ITALIC_DBL = re.compile(r"__(.+?)__", re.DOTALL)
_STRIP_ITALIC = re.compile(r"_(.+?)_", re.DOTALL)
_STRIP_CODE = re.compile(r"`([^`]+)`")
_STRIP_LINK = re.compile(r"\[([^\]]+)\]\([^)]+\)")


def prepare_telegram_markdown(text: str) -> str:
    """Normaliza markdown comum (LLM/GitHub) para o Markdown legado do Telegram."""
    if not text:
        return text

    text = _MARKDOWN_BOLD.sub(r"*\1*", text)
    text = _MARKDOWN_ITALIC.sub(r"_\1_", text)
    text = _BULLET_ITALIC.sub(r"\1• *\2*", text)
    text = _BULLET_PLAIN.sub(r"\1• ", text)
    return text


def strip_markdown(text: str) -> str:
    """Remove marcadores de markdown para envio em texto puro (fallback)."""
    if not text:
        return text

    text = _STRIP_BOLD_DBL.sub(r"\1", text)
    text = _STRIP_BOLD.sub(r"\1", text)
    text = _STRIP_ITALIC_DBL.sub(r"\1", text)
    text = _STRIP_ITALIC.sub(r"\1", text)
    text = _STRIP_CODE.sub(r"\1", text)
    text = _STRIP_LINK.sub(r"\1", text)
    return text


async def reply_text_markdown(message, text: str, **kwargs):
    """reply_text com Markdown normalizado; fallback para texto puro se o parse falhar."""
    prepared = prepare_telegram_markdown(text)
    try:
        return await message.reply_text(prepared, parse_mode="Markdown", **kwargs)
    except BadRequest:
        plain = strip_markdown(text)
        kwargs.pop("parse_mode", None)
        return await message.reply_text(plain, **kwargs)


async def send_message_markdown(bot, chat_id: int, text: str, **kwargs):
    """send_message com Markdown normalizado; fallback para texto puro se o parse falhar."""
    prepared = prepare_telegram_markdown(text)
    try:
        return await bot.send_message(
            chat_id=chat_id, text=prepared, parse_mode="Markdown", **kwargs
        )
    except BadRequest:
        plain = strip_markdown(text)
        kwargs.pop("parse_mode", None)
        return await bot.send_message(chat_id=chat_id, text=plain, **kwargs)
