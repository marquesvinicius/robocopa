"""
notifications.py — Sistema de Alertas Proativos da Copa 2026

Tipos de alerta:
  pre_match  — lembrete N minutos antes do kickoff
  lineup     — escalação publicada (~1h antes do jogo)
  result     — resultado final (status FT/AET/PEN)
  live_goals — gol marcado durante a partida (requer live_goals=True nas prefs)

Deduplicação: Redis (se disponível) ou history/alerts_sent.json.
Redis garante que alertas não são repetidos mesmo após restart.

Quota guard: chamadas à API reutilizam o cache de tools/football.py.
"""

import json
import os
import time
from datetime import datetime, timezone, timedelta

from storage import get_redis
from preferences import UserPreferences
from tools.football import (
    _api_get,
    _cache_get,
    _cache_set,
    _normalize_team,
    _resolve_team_id,
    _utc_to_brasilia,
    _team_pt,
    _BR_TZ,
    _LEAGUE_ID,
    _SEASON,
    _TTL,
    escalacao,
)

_HISTORY_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "history")
_ALERTS_FILE = os.path.join(_HISTORY_DIR, "alerts_sent.json")
_ALERTS_TTL_H = 48
_ALERT_PREFIX = "robocopa:alert:"
_ALERT_TTL_S = _ALERTS_TTL_H * 3600

# Cache em memória para placares ao vivo (não precisa persistir entre restarts)
# fixture_id -> {"home": int, "away": int}
_live_score_cache: dict[int, dict] = {}


# ─────────────────────────────────────────────────────────────
# DEDUPLICAÇÃO
# ─────────────────────────────────────────────────────────────

def _load_sent() -> dict:
    try:
        with open(_ALERTS_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save_sent(data: dict) -> None:
    os.makedirs(_HISTORY_DIR, exist_ok=True)
    try:
        with open(_ALERTS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except OSError:
        pass


def _was_sent(chat_id: int, fixture_id: int, alert_type: str) -> bool:
    key = f"{chat_id}_{fixture_id}_{alert_type}"
    r = get_redis()
    if r is not None:
        try:
            return bool(r.exists(f"{_ALERT_PREFIX}{key}"))
        except Exception:
            pass  # Redis falhou — tenta arquivo
    # Fallback: arquivo
    return key in _load_sent()


def _mark_sent(chat_id: int, fixture_id: int, alert_type: str) -> None:
    key = f"{chat_id}_{fixture_id}_{alert_type}"
    r = get_redis()
    if r is not None:
        try:
            r.setex(f"{_ALERT_PREFIX}{key}", _ALERT_TTL_S, "1")
            return
        except Exception:
            pass  # Redis falhou — tenta arquivo
    # Fallback: arquivo
    sent = _load_sent()
    cutoff = time.time() - _ALERTS_TTL_H * 3600
    sent = {k: v for k, v in sent.items() if v >= cutoff}
    sent[key] = time.time()
    _save_sent(sent)


# ─────────────────────────────────────────────────────────────
# BUSCA DE FIXTURES POR TIME (com cache)
# ─────────────────────────────────────────────────────────────

def _get_fixtures_for_team(team_api: str) -> list[dict]:
    """Retorna fixtures das próximas 24h + últimas 3h para um time."""
    tid = _resolve_team_id(team_api)
    if not tid:
        return []

    cache_key = f"notif_fixtures_{tid}"
    cached = _cache_get(cache_key, 300)
    if cached is not None:
        return cached

    results = []

    data = _api_get("fixtures", {
        "league": _LEAGUE_ID,
        "season": _SEASON,
        "team": tid,
        "next": 3,
    })
    if data and data.get("response"):
        results.extend(data["response"])

    data_last = _api_get("fixtures", {
        "league": _LEAGUE_ID,
        "season": _SEASON,
        "team": tid,
        "last": 2,
    })
    if data_last and data_last.get("response"):
        seen_ids = {f.get("fixture", {}).get("id") for f in results}
        for f in data_last["response"]:
            if f.get("fixture", {}).get("id") not in seen_ids:
                results.append(f)

    _cache_set(cache_key, results)
    return results


# ─────────────────────────────────────────────────────────────
# FORMATAÇÃO DE ALERTAS
# ─────────────────────────────────────────────────────────────

def _format_pre_match(fixture: dict, team_name: str) -> str:
    home = _team_pt(fixture.get("teams", {}).get("home", {}).get("name", "?"))
    away = _team_pt(fixture.get("teams", {}).get("away", {}).get("name", "?"))
    date_str = _utc_to_brasilia(fixture.get("fixture", {}).get("date", ""))
    venue = fixture.get("fixture", {}).get("venue", {}).get("name", "")
    city = fixture.get("fixture", {}).get("venue", {}).get("city", "")
    local = f"{venue}, {city}" if venue and city else venue or city or "?"
    return (
        f"Lembrete Copa 2026!\n\n"
        f"{home} x {away}\n"
        f"Hoje as {date_str}\n"
        f"Local: {local}\n\n"
        f"Boa sorte, {_team_pt(team_name)}!"
    )


def _format_result(fixture: dict) -> str:
    home = _team_pt(fixture.get("teams", {}).get("home", {}).get("name", "?"))
    away = _team_pt(fixture.get("teams", {}).get("away", {}).get("name", "?"))
    gh = fixture.get("goals", {}).get("home", 0)
    ga = fixture.get("goals", {}).get("away", 0)
    status = fixture.get("fixture", {}).get("status", {}).get("long", "Encerrado")
    return (
        f"Resultado final - Copa 2026\n\n"
        f"{home} {gh} x {ga} {away}\n"
        f"({status})"
    )


def _format_lineup(fixture: dict, lineup_text: str) -> str:
    home = _team_pt(fixture.get("teams", {}).get("home", {}).get("name", "?"))
    away = _team_pt(fixture.get("teams", {}).get("away", {}).get("name", "?"))
    date_str = _utc_to_brasilia(fixture.get("fixture", {}).get("date", ""))
    return (
        f"Escalacao publicada - Copa 2026\n\n"
        f"{home} x {away} ({date_str})\n\n"
        f"{lineup_text}"
    )


def _format_goal(fixture: dict, gh: int, ga: int, scorer_side: str) -> str:
    home = _team_pt(fixture.get("teams", {}).get("home", {}).get("name", "?"))
    away = _team_pt(fixture.get("teams", {}).get("away", {}).get("name", "?"))
    elapsed = fixture.get("fixture", {}).get("status", {}).get("elapsed", "?")
    scorer_team = home if scorer_side == "home" else away
    return (
        f"GOL! Copa 2026\n\n"
        f"{home} {gh} x {ga} {away}\n"
        f"Gol de {scorer_team} aos {elapsed}'"
    )


# ─────────────────────────────────────────────────────────────
# LOOP PRINCIPAL
# ─────────────────────────────────────────────────────────────

async def check_and_send_alerts(bot, preferences: UserPreferences) -> None:
    """
    Verifica todos os assinantes e envia alertas pendentes.
    Chamada pelo JobQueue do python-telegram-bot a cada N minutos.
    """
    subscribers = preferences.get_all_subscribers()
    if not subscribers:
        return

    now_utc = datetime.now(tz=timezone.utc)

    for chat_id, prefs in subscribers.items():
        teams = prefs.get("teams", [])
        alerts = prefs.get("alerts", {})
        pre_minutes = alerts.get("pre_match_minutes", 60)

        for team_raw in teams:
            team_api = _normalize_team(team_raw)
            fixtures = _get_fixtures_for_team(team_api)

            for fixture in fixtures:
                fid = fixture.get("fixture", {}).get("id")
                if not fid:
                    continue

                date_raw = fixture.get("fixture", {}).get("date", "")
                if not date_raw:
                    continue

                try:
                    kickoff = datetime.fromisoformat(date_raw.replace("Z", "+00:00"))
                except ValueError:
                    continue

                status_short = fixture.get("fixture", {}).get("status", {}).get("short", "")

                # ── ALERTA PRÉ-JOGO ──────────────────────────────────
                if alerts.get("pre_match_minutes") is not None:
                    window_start = kickoff - timedelta(minutes=pre_minutes + 5)
                    window_end = kickoff
                    if window_start <= now_utc <= window_end:
                        if not _was_sent(chat_id, fid, "pre_match"):
                            try:
                                msg = _format_pre_match(fixture, team_raw)
                                await bot.send_message(chat_id=chat_id, text=msg)
                                _mark_sent(chat_id, fid, "pre_match")
                            except Exception:
                                pass

                # ── ALERTA DE ESCALAÇÃO ───────────────────────────────
                if alerts.get("lineups") and status_short in ("NS", "1H", "HT"):
                    time_to_kickoff = (kickoff - now_utc).total_seconds()
                    if -300 <= time_to_kickoff <= 10800:
                        if not _was_sent(chat_id, fid, "lineup"):
                            try:
                                lineup_text = escalacao(team_raw)
                                if ("ainda não disponível" not in lineup_text
                                        and "Não encontrei" not in lineup_text):
                                    msg = _format_lineup(fixture, lineup_text)
                                    await bot.send_message(chat_id=chat_id, text=msg)
                                    _mark_sent(chat_id, fid, "lineup")
                            except Exception:
                                pass

                # ── ALERTA DE RESULTADO ───────────────────────────────
                if alerts.get("results") and status_short in ("FT", "AET", "PEN"):
                    if not _was_sent(chat_id, fid, "result"):
                        try:
                            msg = _format_result(fixture)
                            await bot.send_message(chat_id=chat_id, text=msg)
                            _mark_sent(chat_id, fid, "result")
                        except Exception:
                            pass

                # ── ALERTA DE GOL AO VIVO ─────────────────────────────
                if alerts.get("live_goals") and status_short in (
                    "1H", "HT", "2H", "ET", "BT", "P", "LIVE"
                ):
                    gh = fixture.get("goals", {}).get("home") or 0
                    ga = fixture.get("goals", {}).get("away") or 0
                    last = _live_score_cache.get(fid)

                    if last is None:
                        # Primeiro check — registra placar sem alertar
                        _live_score_cache[fid] = {"home": gh, "away": ga}
                    else:
                        # Verifica se houve gol desde o último check
                        if gh > last["home"] or ga > last["away"]:
                            scorer_side = "home" if gh > last["home"] else "away"
                            # Dedup por placar exato: evita duplicar se job rodar 2x
                            dedup_key = f"goal_{gh}_{ga}"
                            if not _was_sent(chat_id, fid, dedup_key):
                                try:
                                    msg = _format_goal(fixture, gh, ga, scorer_side)
                                    await bot.send_message(chat_id=chat_id, text=msg)
                                    _mark_sent(chat_id, fid, dedup_key)
                                except Exception:
                                    pass
                        _live_score_cache[fid] = {"home": gh, "away": ga}
