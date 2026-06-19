"""
preferences.py — Preferências e Alertas do Usuário

Backend duplo: Redis (se REDIS_URL configurado) ou arquivo JSON.
Redis garante persistência entre restarts no Render.com.
Fallback em arquivo para desenvolvimento local sem Redis.

Estrutura de dados por usuário:
{
  "teams": ["Brazil", "Argentina"],
  "alerts": {
    "pre_match_minutes": 60,
    "lineups": true,
    "results": true,
    "live_goals": false
  }
}
"""

import json
import os

from storage import get_redis

_HISTORY_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "history")
_REDIS_PREFIX = "robocopa:prefs:"

_DEFAULTS: dict = {
    "teams": [],
    "alerts": {
        "pre_match_minutes": 60,
        "lineups": True,
        "results": True,
        "live_goals": False,
    },
}


# ─────────────────────────────────────────────────────────────
# HELPERS INTERNOS
# ─────────────────────────────────────────────────────────────

def _prefs_path(chat_id: int) -> str:
    return os.path.join(_HISTORY_DIR, f"prefs_{chat_id}.json")


def _deep_copy_defaults() -> dict:
    return {"teams": [], "alerts": dict(_DEFAULTS["alerts"])}


def _merge_defaults(data: dict) -> dict:
    result = _deep_copy_defaults()
    if isinstance(data.get("teams"), list):
        result["teams"] = data["teams"]
    if isinstance(data.get("alerts"), dict):
        result["alerts"].update(data["alerts"])
    return result


def _load(chat_id: int) -> dict:
    r = get_redis()
    if r is not None:
        try:
            raw = r.get(f"{_REDIS_PREFIX}{chat_id}")
            if raw:
                return _merge_defaults(json.loads(raw))
        except Exception:
            pass  # Redis falhou — tenta arquivo

    # Fallback: arquivo
    path = _prefs_path(chat_id)
    if not os.path.exists(path):
        return _deep_copy_defaults()
    try:
        with open(path, encoding="utf-8") as f:
            return _merge_defaults(json.load(f))
    except (json.JSONDecodeError, OSError):
        return _deep_copy_defaults()


def _save(chat_id: int, data: dict) -> None:
    r = get_redis()
    if r is not None:
        try:
            r.set(f"{_REDIS_PREFIX}{chat_id}", json.dumps(data, ensure_ascii=False))
            return
        except Exception:
            pass  # Redis falhou — tenta arquivo

    # Fallback: arquivo
    os.makedirs(_HISTORY_DIR, exist_ok=True)
    try:
        with open(_prefs_path(chat_id), "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except OSError:
        pass


# ─────────────────────────────────────────────────────────────
# INTERFACE PÚBLICA
# ─────────────────────────────────────────────────────────────

class UserPreferences:
    """Gerencia preferências persistentes de todos os usuários."""

    def get(self, chat_id: int) -> dict:
        """Retorna prefs atuais (com defaults para campos ausentes)."""
        return _load(chat_id)

    def set_teams(self, chat_id: int, teams: list[str]) -> None:
        """Substitui a lista completa de times seguidos."""
        data = _load(chat_id)
        data["teams"] = list(dict.fromkeys(t.strip() for t in teams if t.strip()))
        _save(chat_id, data)

    def add_team(self, chat_id: int, team: str) -> bool:
        """Adiciona um time. Retorna True se adicionado, False se já existia."""
        team = team.strip()
        if not team:
            return False
        data = _load(chat_id)
        if team not in data["teams"]:
            data["teams"].append(team)
            _save(chat_id, data)
            return True
        return False

    def remove_team(self, chat_id: int, team: str) -> bool:
        """Remove um time. Retorna True se removido, False se não encontrado."""
        team = team.strip()
        data = _load(chat_id)
        if team in data["teams"]:
            data["teams"].remove(team)
            _save(chat_id, data)
            return True
        return False

    def set_alerts(self, chat_id: int, **kwargs) -> None:
        """Atualiza campos de alerta individualmente."""
        data = _load(chat_id)
        valid_keys = set(_DEFAULTS["alerts"].keys())
        for k, v in kwargs.items():
            if k in valid_keys:
                if k == "pre_match_minutes":
                    data["alerts"][k] = max(1, int(v))
                else:
                    data["alerts"][k] = bool(v)
        _save(chat_id, data)

    def get_all_subscribers(self) -> dict[int, dict]:
        """
        Retorna {chat_id: prefs} de todos os usuários com ao menos um time seguido.
        Usado pelo scheduler para saber a quem enviar alertas.
        """
        subscribers: dict[int, dict] = {}

        r = get_redis()
        if r is not None:
            try:
                cursor = 0
                while True:
                    cursor, keys = r.scan(cursor, match=f"{_REDIS_PREFIX}*", count=100)
                    for key in keys:
                        try:
                            chat_id = int(key[len(_REDIS_PREFIX):])
                            prefs = _load(chat_id)
                            if prefs["teams"]:
                                subscribers[chat_id] = prefs
                        except (ValueError, Exception):
                            continue
                    if cursor == 0:
                        break
                return subscribers
            except Exception:
                pass  # Redis falhou — tenta arquivo

        # Fallback: arquivo
        if not os.path.exists(_HISTORY_DIR):
            return subscribers
        for fname in os.listdir(_HISTORY_DIR):
            if not fname.startswith("prefs_") or not fname.endswith(".json"):
                continue
            try:
                chat_id = int(fname[len("prefs_"):-len(".json")])
            except ValueError:
                continue
            prefs = _load(chat_id)
            if prefs["teams"]:
                subscribers[chat_id] = prefs
        return subscribers

    def clear(self, chat_id: int) -> None:
        """Remove todas as preferências do usuário (cancela tudo)."""
        r = get_redis()
        if r is not None:
            try:
                r.delete(f"{_REDIS_PREFIX}{chat_id}")
            except Exception:
                pass

        # Também remove arquivo se existir
        path = _prefs_path(chat_id)
        try:
            if os.path.exists(path):
                os.remove(path)
        except OSError:
            pass

    def format_summary(self, chat_id: int) -> str:
        """Retorna texto formatado das preferências para exibir ao usuário."""
        prefs = self.get(chat_id)
        teams = prefs["teams"]
        alerts = prefs["alerts"]

        if not teams:
            teams_str = "Nenhum time seguido"
        else:
            from tools.football import _team_pt
            teams_str = ", ".join(_team_pt(t) for t in teams)

        alert_lines = []
        pre = alerts.get("pre_match_minutes", 60)
        alert_lines.append(f"Lembrete pre-jogo: {pre} min antes")
        if alerts.get("lineups"):
            alert_lines.append("Escalacoes (quando publicadas)")
        if alerts.get("results"):
            alert_lines.append("Resultados finais")
        if alerts.get("live_goals"):
            alert_lines.append("Gols ao vivo")

        alerts_str = "\n  - ".join(alert_lines) if alert_lines else "Nenhum"

        backend = "Redis" if get_redis() is not None else "arquivo local"
        return (
            "*Suas preferencias no Robocopa:*\n\n"
            f"Times seguidos: *{teams_str}*\n\n"
            f"Alertas ativos:\n  - {alerts_str}\n\n"
            f"Preferencias salvas em: {backend}.\n"
            "Use /cancelar_alertas para remover tudo."
        )
