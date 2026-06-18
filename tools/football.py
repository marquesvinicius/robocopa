"""
tools/football.py — Ferramenta de Dados da Copa do Mundo 2026

Fornece dados estruturados sobre a Copa do Mundo 2026 (Canadá/EUA/México) ao agente.

Fontes (em ordem de prioridade):
  1. API-Football (api-sports.io) — dados ao vivo, placar em tempo real
     Free tier: 100 requisições/dia
     Cadastro: https://dashboard.api-football.com
  2. openfootball/worldcup.json — fallback sem chave de API
     JSON estático, atualizado ~1x/dia pela comunidade

Configure no .env:
  API_FOOTBALL_KEY=sua_chave_aqui          ← obrigatório para dados ao vivo
  API_FOOTBALL_HOST=v3.football.api-sports.io  ← opcional (padrão já configurado)

A Copa do Mundo 2026 na API-Football:
  - league_id = 1
  - season    = 2026
"""

import json
import os
import time
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

import requests

# ─────────────────────────────────────────────────────────────
# CONFIGURAÇÃO
# ─────────────────────────────────────────────────────────────

_API_HOST = os.getenv("API_FOOTBALL_HOST", "v3.football.api-sports.io")
_BASE_URL = f"https://{_API_HOST}"
_LEAGUE_ID = 1       # FIFA World Cup na API-Football
_SEASON = 2026

_REQUEST_TIMEOUT = 10  # segundos
_BR_TZ = ZoneInfo("America/Sao_Paulo")

# Cache local — evita gastar quota desnecessariamente
_CACHE_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "history",
    "worldcup_cache.json"
)
# TTL em segundos para cada tipo de dado cacheado
_TTL: dict[str, int] = {
    "fixtures":    300,   # 5 min — jogos próximos mudam pouco
    "live":        60,    # 1 min — placar ao vivo
    "standings":   600,   # 10 min — classificação
    "lineups":     300,   # 5 min — escalação
    "openfootball": 3600, # 1 hora — JSON estático
}
_OPENFOOTBALL_URL = (
    "https://raw.githubusercontent.com/openfootball/"
    "worldcup.json/master/2026/worldcup.json"
)

# Último erro retornado pela API (para diagnóstico e mensagens ao usuário)
_last_api_error: str | None = None

# Detectado após primeiro erro "Free plans do not have access to this season"
# Evita bater na API-Football com temporada 2026 repetidamente
_api_football_2026_blocked: bool = False

# Nomes alternativos / apelidos de seleções → nome oficial
_ALIASES: dict[str, str] = {
    "brasil":    "Brazil",
    "brazil":    "Brazil",
    "selecao":   "Brazil",
    "seleção":   "Brazil",
    "canarinho": "Brazil",
    "alemanha":  "Germany",
    "germany":   "Germany",
    "franca":    "France",
    "fran":      "France",
    "franca":    "France",
    "france":    "France",
    "argentina": "Argentina",
    "espanha":   "Spain",
    "spain":     "Spain",
    "portugal":  "Portugal",
    "england":   "England",
    "inglaterra":"England",
    "italy":     "Italy",
    "italia":    "Italy",
    "itália":    "Italy",
    "holanda":   "Netherlands",
    "netherlands":"Netherlands",
    "estados unidos": "USA",
    "eua":       "USA",
    "usa":       "USA",
    "mexico":    "Mexico",
    "méxico":    "Mexico",
    "canada":    "Canada",
    "canadá":    "Canada",
    "uruguai":   "Uruguay",
    "uruguay":   "Uruguay",
    "colombia":  "Colombia",
    "colômbia":  "Colombia",
    "japao":     "Japan",
    "japão":     "Japan",
    "japan":     "Japan",
    "coreia":    "South Korea",
    "corea":     "South Korea",
    "marrocos":  "Morocco",
    "morocco":   "Morocco",
    "nigeria":   "Nigeria",
    "nigéria":   "Nigeria",
    "nigeria":   "Nigeria",
    "senegal":   "Senegal",
    "egito":     "Egypt",
    "egypt":     "Egypt",
    "australia": "Australia",
    "austrália": "Australia",
    "noruega":   "Norway",
    "norway":    "Norway",
    "frança":    "France",
    "suica":     "Switzerland",
    "suíça":     "Switzerland",
    "croacia":   "Croatia",
    "dinamarca": "Denmark",
    "suecia":    "Sweden",
    "polonia":   "Poland",
    "polônia":   "Poland",
}

# Tradução de nomes em inglês (como vêm das APIs) para português (exibição ao usuário)
_PT_BR_NAMES: dict[str, str] = {
    "Brazil": "Brasil",
    "Germany": "Alemanha",
    "France": "França",
    "Spain": "Espanha",
    "England": "Inglaterra",
    "Italy": "Itália",
    "Netherlands": "Holanda",
    "Belgium": "Bélgica",
    "Argentina": "Argentina",
    "Uruguay": "Uruguai",
    "Colombia": "Colômbia",
    "Chile": "Chile",
    "Ecuador": "Equador",
    "Peru": "Peru",
    "Paraguay": "Paraguai",
    "Venezuela": "Venezuela",
    "Bolivia": "Bolívia",
    "Mexico": "México",
    "USA": "EUA",
    "United States": "EUA",
    "Canada": "Canadá",
    "Costa Rica": "Costa Rica",
    "Panama": "Panamá",
    "Honduras": "Honduras",
    "Jamaica": "Jamaica",
    "Cuba": "Cuba",
    "Guatemala": "Guatemala",
    "El Salvador": "El Salvador",
    "Trinidad and Tobago": "Trinidad e Tobago",
    "Trinidad & Tobago": "Trinidad e Tobago",
    "Curaçao": "Curaçao",
    "Curacao": "Curaçao",
    "Haiti": "Haiti",
    "Suriname": "Suriname",
    "Morocco": "Marrocos",
    "Senegal": "Senegal",
    "Nigeria": "Nigéria",
    "Egypt": "Egito",
    "Ivory Coast": "Costa do Marfim",
    "Côte d'Ivoire": "Costa do Marfim",
    "Cote d'Ivoire": "Costa do Marfim",
    "Cameroon": "Camarões",
    "Ghana": "Gana",
    "Tunisia": "Tunísia",
    "Algeria": "Argélia",
    "South Africa": "África do Sul",
    "Mali": "Mali",
    "Zambia": "Zâmbia",
    "Congo DR": "R.D. do Congo",
    "DR Congo": "R.D. do Congo",
    "Congo": "Congo",
    "Kenya": "Quênia",
    "Angola": "Angola",
    "Zimbabwe": "Zimbábue",
    "Mozambique": "Moçambique",
    "Tanzania": "Tanzânia",
    "Uganda": "Uganda",
    "Rwanda": "Ruanda",
    "Ethiopia": "Etiópia",
    "Gabon": "Gabão",
    "Benin": "Benim",
    "Burkina Faso": "Burkina Faso",
    "Guinea": "Guiné",
    "Togo": "Togo",
    "Cape Verde": "Cabo Verde",
    "Cabo Verde": "Cabo Verde",
    "Japan": "Japão",
    "South Korea": "Coreia do Sul",
    "Korea Republic": "Coreia do Sul",
    "North Korea": "Coreia do Norte",
    "Korea DPR": "Coreia do Norte",
    "Australia": "Austrália",
    "Iran": "Irã",
    "IR Iran": "Irã",
    "Saudi Arabia": "Arábia Saudita",
    "Qatar": "Catar",
    "Iraq": "Iraque",
    "Uzbekistan": "Uzbequistão",
    "Indonesia": "Indonésia",
    "China PR": "China",
    "China": "China",
    "India": "Índia",
    "Thailand": "Tailândia",
    "Vietnam": "Vietnã",
    "Malaysia": "Malásia",
    "Philippines": "Filipinas",
    "New Zealand": "Nova Zelândia",
    "Switzerland": "Suíça",
    "Austria": "Áustria",
    "Croatia": "Croácia",
    "Serbia": "Sérvia",
    "Denmark": "Dinamarca",
    "Sweden": "Suécia",
    "Norway": "Noruega",
    "Poland": "Polônia",
    "Ukraine": "Ucrânia",
    "Scotland": "Escócia",
    "Romania": "Romênia",
    "Czechia": "República Tcheca",
    "Czech Republic": "República Tcheca",
    "Hungary": "Hungria",
    "Slovakia": "Eslováquia",
    "Slovenia": "Eslovênia",
    "Greece": "Grécia",
    "Turkey": "Turquia",
    "Albania": "Albânia",
    "Bosnia and Herzegovina": "Bósnia e Herzegovina",
    "Bosnia Herzegovina": "Bósnia e Herzegovina",
    "North Macedonia": "Macedônia do Norte",
    "Finland": "Finlândia",
    "Wales": "País de Gales",
    "Republic of Ireland": "Irlanda",
    "Ireland": "Irlanda",
    "Israel": "Israel",
    "Georgia": "Geórgia",
    "Azerbaijan": "Azerbaijão",
    "Armenia": "Armênia",
    "Belarus": "Bielorrússia",
    "Kazakhstan": "Cazaquistão",
    "Portugal": "Portugal",
    "Russia": "Rússia",
    "Palestine": "Palestina",
    "Bahrain": "Bahrein",
    "Jordan": "Jordânia",
    "Kuwait": "Kuwait",
    "United Arab Emirates": "Emirados Árabes Unidos",
    "Papua New Guinea": "Papua Nova Guiné",
    "Solomon Islands": "Ilhas Salomão",
    "New Caledonia": "Nova Caledônia",
    "Fiji": "Fiji",
    "Tahiti": "Taiti",
}


def _team_pt(name: str) -> str:
    """Translates an English API team name to Portuguese for display."""
    return _PT_BR_NAMES.get(name, name)


# ─────────────────────────────────────────────────────────────
# CACHE
# ─────────────────────────────────────────────────────────────

def _load_cache() -> dict:
    try:
        with open(_CACHE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save_cache(cache: dict) -> None:
    os.makedirs(os.path.dirname(_CACHE_FILE), exist_ok=True)
    try:
        with open(_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
    except OSError:
        pass  # falha de escrita não deve quebrar o bot


def _cache_get(key: str, ttl: int) -> Any | None:
    cache = _load_cache()
    entry = cache.get(key)
    if not entry:
        return None
    if time.time() - entry.get("ts", 0) > ttl:
        return None
    return entry.get("data")


def _cache_set(key: str, data: Any) -> None:
    cache = _load_cache()
    cache[key] = {"ts": time.time(), "data": data}
    _save_cache(cache)


# ─────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────

def _normalize_team(name: str) -> str:
    """Converte apelidos/nomes PT-BR para o nome oficial da API."""
    return _ALIASES.get(name.lower().strip(), name.strip())


def _utc_to_brasilia(iso_str: str) -> str:
    """Converte string ISO UTC para horário de Brasília formatado."""
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        dt_br = dt.astimezone(_BR_TZ)
        return dt_br.strftime("%d/%m/%Y %H:%M (Brasília)")
    except Exception:
        return iso_str


def _api_headers() -> dict:
    key = os.getenv("API_FOOTBALL_KEY", "").strip()
    return {
        "x-apisports-key": key,
        "x-rapidapi-key": key,
        "x-rapidapi-host": _API_HOST,
    }


def _api_get(endpoint: str, params: dict) -> dict | None:
    """
    Faz GET na API-Football com tratamento de erros.
    Retorna None se a chave não estiver configurada ou em caso de erro.
    """
    global _last_api_error
    key = os.getenv("API_FOOTBALL_KEY", "").strip()
    if not key:
        _last_api_error = "API_FOOTBALL_KEY não configurada"
        return None

    try:
        resp = requests.get(
            f"{_BASE_URL}/{endpoint}",
            headers=_api_headers(),
            params=params,
            timeout=_REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
        # A API retorna erros na chave "errors"
        if data.get("errors"):
            global _api_football_2026_blocked
            _last_api_error = str(data["errors"])
            if "Free plans" in _last_api_error:
                _api_football_2026_blocked = True
            if os.getenv("DEBUG", "false").lower() == "true":
                print(f"[API-Football] {endpoint} {params}: {data['errors']}")
            return None
        _last_api_error = None
        return data
    except requests.Timeout:
        _last_api_error = "timeout na API-Football"
        return None
    except requests.HTTPError as exc:
        _last_api_error = f"HTTP {exc.response.status_code if exc.response else '?'} na API-Football"
        return None
    except requests.RequestException:
        _last_api_error = "erro de rede na API-Football"
        return None
    except Exception:
        _last_api_error = "erro inesperado na API-Football"
        return None


def _has_api_football_key() -> bool:
    return bool(os.getenv("API_FOOTBALL_KEY", "").strip())


def _fallback_source_note() -> str:
    if not _has_api_football_key():
        return "_(fonte: openfootball — sem chave API)_"
    if _last_api_error and "Free plans" in _last_api_error:
        return (
            "_(fonte: openfootball — plano Free da API-Football não inclui "
            "temporada 2026 completa)_"
        )
    return "_(fonte: openfootball — API-Football indisponível no momento)_"


def _format_fixture_lines(fixtures: list[dict], detailed: bool = True) -> list[str]:
    lines = []
    for f in fixtures:
        fixture = f.get("fixture", {})
        home = _team_pt(f.get("teams", {}).get("home", {}).get("name", "?"))
        away = _team_pt(f.get("teams", {}).get("away", {}).get("name", "?"))
        date = _utc_to_brasilia(fixture.get("date", ""))
        if detailed:
            venue = fixture.get("venue", {}).get("name", "")
            city = fixture.get("venue", {}).get("city", "")
            loc = f"{venue}, {city}" if venue and city else venue or city or "?"
            stage = f.get("league", {}).get("round", "")
            lines.append(
                f"• {home} x {away}\n  Data: {date}\n  Local: {loc}\n  Fase: {stage}"
            )
        else:
            stage = f.get("league", {}).get("round", "")
            lines.append(f"• {home} x {away} — {date} | {stage}")
    return lines


def _fixtures_by_date_free_tier(
    team_api: str | None,
    limit: int,
    days_ahead: int = 14,
) -> list[dict]:
    """
    Plano Free: consulta /fixtures?date=YYYY-MM-DD (sem season=2026)
    e filtra apenas jogos da Copa (league_id=1).
    """
    today = datetime.now(tz=timezone.utc).date()
    collected: list[tuple[str, dict]] = []

    for offset in range(days_ahead + 1):
        day = (today + timedelta(days=offset)).isoformat()
        data = _api_get("fixtures", {"date": day})
        if not data or not data.get("response"):
            continue
        for f in data["response"]:
            if f.get("league", {}).get("id") != _LEAGUE_ID:
                continue
            status = f.get("fixture", {}).get("status", {}).get("short", "")
            if status in ("FT", "AET", "PEN"):
                continue
            if team_api:
                home = f.get("teams", {}).get("home", {}).get("name", "")
                away = f.get("teams", {}).get("away", {}).get("name", "")
                if (
                    team_api.lower() not in home.lower()
                    and team_api.lower() not in away.lower()
                ):
                    continue
            collected.append((f.get("fixture", {}).get("date", ""), f))

    collected.sort(key=lambda x: x[0])
    return [f for _, f in collected[:limit]]


def api_football_startup_status() -> str:
    """Verifica se a chave funciona e se o plano cobre a temporada 2026."""
    if not _has_api_football_key():
        return "sem chave (fallback openfootball)"

    data = _api_get("fixtures", {
        "league": _LEAGUE_ID,
        "season": _SEASON,
        "next": 1,
    })
    if data is not None:
        return "OK (temporada 2026 completa)"

    if _last_api_error and "Free plans" in _last_api_error:
        global _api_football_2026_blocked
        _api_football_2026_blocked = True
        return "chave OK — plano Free (Copa 2026 parcial; upgrade para dados completos)"

    if _last_api_error:
        return f"chave configurada (erro: {_last_api_error[:70]})"

    return "chave OK (verificação inconclusiva)"


# ─────────────────────────────────────────────────────────────
# FALLBACK: openfootball/worldcup.json
# ─────────────────────────────────────────────────────────────

def _load_openfootball() -> dict | None:
    cached = _cache_get("openfootball", _TTL["openfootball"])
    if cached:
        return cached

    try:
        resp = requests.get(_OPENFOOTBALL_URL, timeout=_REQUEST_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        _cache_set("openfootball", data)
        return data
    except Exception:
        return None


def _parse_openfootball_dt(date_str: str, time_str: str) -> datetime | None:
    """
    Parseia data + hora do openfootball para datetime UTC.
    O campo time pode conter offset: "13:00 UTC-6", "18:00 UTC-4", "12:00".
    """
    if not date_str:
        return None
    import re as _re
    raw_time = (time_str or "00:00").strip()
    # Extrai offset: "UTC-6" → -6, "UTC+3" → +3
    match = _re.search(r"UTC([+-])(\d+)", raw_time)
    offset_hours = 0
    if match:
        sign = 1 if match.group(1) == "+" else -1
        offset_hours = sign * int(match.group(2))
    # Mantém só HH:MM
    hhmm = _re.sub(r"\s*UTC[+-]\d+", "", raw_time).strip() or "00:00"
    try:
        from datetime import timedelta
        dt_local = datetime.strptime(f"{date_str} {hhmm}", "%Y-%m-%d %H:%M")
        dt_utc = dt_local - timedelta(hours=offset_hours)
        return dt_utc.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _openfootball_proximos(team_name: str | None, limit: int = 5) -> str:
    data = _load_openfootball()
    if not data:
        return ""

    # openfootball/worldcup.json usa estrutura flat: {"name": ..., "matches": [...]}
    # cada match: {round, date, time, team1, team2, score, group, ground}
    now_utc = datetime.now(tz=timezone.utc)
    matches = []

    for match in data.get("matches", []):
        dt_utc = _parse_openfootball_dt(match.get("date", ""), match.get("time", ""))
        if dt_utc is None or dt_utc < now_utc:
            continue
        t1 = match.get("team1", {})
        t2 = match.get("team2", {})
        n1 = t1.get("name", str(t1)) if isinstance(t1, dict) else str(t1)
        n2 = t2.get("name", str(t2)) if isinstance(t2, dict) else str(t2)
        if team_name:
            if team_name.lower() not in n1.lower() and team_name.lower() not in n2.lower():
                continue
        grp = match.get("group", match.get("round", ""))
        matches.append((dt_utc, n1, n2, grp))

    matches.sort(key=lambda x: x[0])
    if not matches:
        return ""

    lines = []
    for dt_utc, n1, n2, grp in matches[:limit]:
        n1 = _team_pt(n1)
        n2 = _team_pt(n2)
        dt_br = dt_utc.astimezone(_BR_TZ)
        hora_br = dt_br.strftime("%d/%m/%Y %H:%M (Brasilia)")
        lines.append(f"• {n1} x {n2} — {hora_br} | {grp}")

    header = f"Proximos jogos{' de ' + team_name if team_name else ''}:"
    return header + "\n" + "\n".join(lines) + "\n" + _fallback_source_note()


def _openfootball_resultado(time_ou_data: str) -> str:
    """
    Busca placar de partidas encerradas no openfootball.
    Retorna texto formatado ou string vazia se não encontrado.
    """
    import re as _re
    data = _load_openfootball()
    if not data:
        return ""

    team_api = None
    date_filter = None
    try:
        parsed = datetime.strptime(time_ou_data.strip(), "%d/%m/%Y")
        date_filter = parsed.strftime("%Y-%m-%d")
    except ValueError:
        # Pode ser "Brasil x Marrocos" ou só "Brasil"
        raw = time_ou_data.strip()
        partes = [p.strip() for p in raw.replace(" x ", "x").replace(" X ", "x").split("x")]
        team_api = _normalize_team(partes[0]) if partes else _normalize_team(raw)

    results = []
    for match in data.get("matches", []):
        score = match.get("score", {})
        ft = score.get("ft")
        if not ft or len(ft) < 2:
            continue  # jogo ainda não encerrado

        t1_raw = match.get("team1", {})
        t2_raw = match.get("team2", {})
        n1 = t1_raw.get("name", str(t1_raw)) if isinstance(t1_raw, dict) else str(t1_raw)
        n2 = t2_raw.get("name", str(t2_raw)) if isinstance(t2_raw, dict) else str(t2_raw)
        match_date = match.get("date", "")

        if date_filter:
            if match_date != date_filter:
                continue
        elif team_api:
            if (
                team_api.lower() not in n1.lower()
                and team_api.lower() not in n2.lower()
            ):
                continue

        dt_utc = _parse_openfootball_dt(match_date, match.get("time", ""))
        if dt_utc:
            date_br = dt_utc.astimezone(_BR_TZ).strftime("%d/%m/%Y (Brasilia)")
        else:
            date_br = match_date
        grp = match.get("group", match.get("round", ""))
        g1, g2 = ft[0], ft[1]
        results.append(f"**{_team_pt(n1)} {g1} x {g2} {_team_pt(n2)}** — {date_br} | {grp}")

    if not results:
        return ""
    return "\n".join(results[-3:]) + "\n" + _fallback_source_note()


def _openfootball_classificacao(grupo: str | None) -> str:
    data = _load_openfootball()
    if not data:
        return ""

    # Extrai times únicos por grupo a partir da lista de matches
    grupos: dict[str, set] = {}
    for match in data.get("matches", []):
        grp = match.get("group", "")
        if not grp:
            continue
        if grupo and grupo.upper() not in grp.upper():
            continue
        t1 = match.get("team1", {})
        t2 = match.get("team2", {})
        n1 = _team_pt(t1.get("name", str(t1)) if isinstance(t1, dict) else str(t1))
        n2 = _team_pt(t2.get("name", str(t2)) if isinstance(t2, dict) else str(t2))
        grupos.setdefault(grp, set())
        if n1:
            grupos[grp].add(n1)
        if n2:
            grupos[grp].add(n2)

    if not grupos:
        return ""

    lines = ["Grupos da Copa 2026 (times — sem pontuacao, use API-Football para tabela completa):"]
    for grp_name in sorted(grupos.keys()):
        lines.append(f"\n**{grp_name}**")
        for team in sorted(grupos[grp_name]):
            lines.append(f"  • {team}")

    return "\n".join(lines) + "\n" + _fallback_source_note()


# ─────────────────────────────────────────────────────────────
# FOOTBALL-DATA.ORG — 2ª Fonte Estruturada (Copa 2026, gratuita)
# Cadastro: https://www.football-data.org/client/register
# Configure: FOOTBALL_DATA_KEY=seu_token no .env
# Free plan: 10 req/min, Copa (WC) inclusa, atraso ~1min no ao vivo
# ─────────────────────────────────────────────────────────────

_FDORG_BASE = "https://api.football-data.org/v4"
_FDORG_COMP = "WC"  # Copa do Mundo 2026
_FDORG_TEAMS_TTL = 3600   # elenco muda raramente
_FDORG_MATCHES_TTL = 300  # placares/última partida mudam com mais frequência
_FDORG_CACHE_TEAMS = f"fdorg_{_FDORG_COMP}_teams"
_FDORG_CACHE_MATCHES = f"fdorg_{_FDORG_COMP}_matches_all"


def _has_fdorg_key() -> bool:
    return bool(os.getenv("FOOTBALL_DATA_KEY", "").strip())


def _fdorg_get(path: str, params: dict | None = None) -> dict | None:
    """GET na football-data.org API v4. Retorna None em qualquer erro."""
    key = os.getenv("FOOTBALL_DATA_KEY", "").strip()
    if not key:
        return None
    try:
        resp = requests.get(
            f"{_FDORG_BASE}/{path}",
            headers={"X-Auth-Token": key},
            params=params or {},
            timeout=_REQUEST_TIMEOUT,
        )
        if resp.status_code == 429:
            return None
        resp.raise_for_status()
        return resp.json()
    except Exception:
        return None


def _fdorg_competition_teams() -> list[dict] | None:
    """Lista de seleções da Copa 2026 — cache compartilhado (elenco, escalacao, etc.)."""
    cached = _cache_get(_FDORG_CACHE_TEAMS, _FDORG_TEAMS_TTL)
    if cached is not None:
        return cached

    data = _fdorg_get(f"competitions/{_FDORG_COMP}/teams")
    if not data or "teams" not in data:
        return None

    teams = data["teams"]
    _cache_set(_FDORG_CACHE_TEAMS, teams)
    return teams


def _fdorg_competition_matches() -> list[dict] | None:
    """Todas as partidas da Copa 2026 — cache compartilhado."""
    cached = _cache_get(_FDORG_CACHE_MATCHES, _FDORG_MATCHES_TTL)
    if cached is not None:
        return cached

    data = _fdorg_get(f"competitions/{_FDORG_COMP}/matches")
    if not data or "matches" not in data:
        return None

    matches = data["matches"]
    _cache_set(_FDORG_CACHE_MATCHES, matches)
    return matches


def _fdorg_match_line(m: dict, detailed: bool = False) -> str:
    home = _team_pt(m.get("homeTeam", {}).get("name", "?"))
    away = _team_pt(m.get("awayTeam", {}).get("name", "?"))
    date = _utc_to_brasilia(m.get("utcDate", ""))
    status = m.get("status", "")
    grp_raw = m.get("group") or m.get("stage", "")
    grp = grp_raw.replace("GROUP_", "Grupo ").replace("_", " ").title()
    score = m.get("score", {}).get("fullTime", {})

    if status in ("FINISHED", "AWARDED"):
        gh = score.get("home", "?")
        ga = score.get("away", "?")
        return f"**{home} {gh} x {ga} {away}** — {date} | {grp}"
    elif status in ("IN_PLAY", "PAUSED"):
        gh = score.get("home", 0)
        ga = score.get("away", 0)
        return f"⚽ **{home} {gh} x {ga} {away}** (AO VIVO) | {grp}"
    else:
        if detailed:
            venue = m.get("venue") or ""
            return f"• {home} x {away}\n  Data: {date}\n  Local: {venue or '?'}\n  Fase: {grp}"
        return f"• {home} x {away} — {date} | {grp}"


def _fdorg_proximos(team_name: str | None, limite: int) -> list[dict]:
    cache_key = f"fdorg_sched_{team_name or 'all'}"
    cached = _cache_get(cache_key, 300)
    if cached is not None:
        return cached

    all_matches = _fdorg_competition_matches()
    if all_matches is None:
        return []

    now = datetime.now(tz=timezone.utc)
    cutoff = (now + timedelta(days=14)).isoformat()
    now_iso = now.isoformat()
    matches = [
        m for m in all_matches
        if m.get("status") in ("SCHEDULED", "TIMED")
        and now_iso <= m.get("utcDate", "") <= cutoff
    ]
    if team_name:
        t = team_name.lower()
        matches = [
            m for m in matches
            if t in m.get("homeTeam", {}).get("name", "").lower()
            or t in m.get("awayTeam", {}).get("name", "").lower()
        ]
    result = matches[:limite]
    _cache_set(cache_key, result)
    return result


def _fdorg_resultado(team_name: str | None, date_filter: str | None) -> list[dict]:
    cache_key = f"fdorg_fin_{team_name or 'all'}_{date_filter or 'recent'}"
    cached = _cache_get(cache_key, 120)
    if cached is not None:
        return cached

    all_matches = _fdorg_competition_matches()
    if all_matches is None:
        return []

    matches = [m for m in all_matches if m.get("status") in ("FINISHED", "AWARDED")]
    if date_filter:
        matches = [m for m in matches if m.get("utcDate", "").startswith(date_filter)]
    if team_name:
        t = team_name.lower()
        matches = [
            m for m in matches
            if t in m.get("homeTeam", {}).get("name", "").lower()
            or t in m.get("awayTeam", {}).get("name", "").lower()
        ]
    result = matches[-5:]
    _cache_set(cache_key, result)
    return result


def _fdorg_ao_vivo() -> list[dict]:
    cached = _cache_get("fdorg_live", 60)
    if cached is not None:
        return cached

    all_matches = _fdorg_competition_matches()
    if all_matches is not None:
        result = [m for m in all_matches if m.get("status") in ("IN_PLAY", "PAUSED")]
        _cache_set("fdorg_live", result)
        return result

    # Fallback direto só se o cache compartilhado não retornou nada
    result = []
    for status in ("IN_PLAY", "PAUSED"):
        data = _fdorg_get(f"competitions/{_FDORG_COMP}/matches", {"status": status})
        if data and "matches" in data:
            result.extend(data["matches"])
    _cache_set("fdorg_live", result)
    return result


def _fdorg_classificacao(grupo: str | None) -> str:
    cache_key = f"fdorg_stand_{grupo or 'all'}"
    cached = _cache_get(cache_key, 600)
    if cached is not None:
        return cached

    data = _fdorg_get(f"competitions/{_FDORG_COMP}/standings")
    if not data or "standings" not in data:
        return ""

    lines = ["**Classificação — Copa do Mundo 2026**"]
    for standing in data["standings"]:
        if standing.get("type") != "TOTAL":
            continue
        grp_raw = standing.get("group", "")
        grp_name = grp_raw.replace("GROUP_", "Grupo ")
        if grupo and grupo.upper() not in grp_name.upper():
            continue

        lines.append(f"\n**{grp_name}**")
        lines.append(
            f"{'#':<3} {'Seleção':<20} {'J':>3} {'V':>3} {'E':>3} {'D':>3} {'GP':>4} {'GC':>4} {'Pts':>4}"
        )
        lines.append("-" * 52)
        for team in standing.get("table", []):
            pos = team.get("position", "?")
            name = _team_pt(team.get("team", {}).get("name", "?"))[:18]
            j = team.get("playedGames", 0)
            v = team.get("won", 0)
            e = team.get("draw", 0)
            d = team.get("lost", 0)
            gp = team.get("goalsFor", 0)
            gc = team.get("goalsAgainst", 0)
            pts = team.get("points", 0)
            lines.append(
                f"{pos:<3} {name:<20} {j:>3} {v:>3} {e:>3} {d:>3} {gp:>4} {gc:>4} {pts:>4}"
            )

    if len(lines) <= 1:
        return ""

    result = "\n".join(lines) + "\n_(fonte: football-data.org)_"
    _cache_set(cache_key, result)
    return result


def _fdorg_artilheiros(limite: int) -> str:
    cache_key = f"fdorg_scorers_{limite}"
    cached = _cache_get(cache_key, 1800)
    if cached is not None:
        return cached

    data = _fdorg_get(f"competitions/{_FDORG_COMP}/scorers", {"limit": limite})
    if not data or "scorers" not in data:
        return ""

    scorers = data["scorers"]
    if not scorers:
        return ""

    lines = ["**Artilheiros — Copa do Mundo 2026**\n"]
    lines.append(f"{'#':<4} {'Jogador':<22} {'Seleção':<14} {'G':>4} {'A':>4}")
    lines.append("-" * 50)
    for i, entry in enumerate(scorers[:limite], 1):
        player = entry.get("player", {}).get("name", "?")[:20]
        team = _team_pt(entry.get("team", {}).get("name", "?"))[:12]
        goals = entry.get("goals", 0) or 0
        assists = entry.get("assists", 0) or 0
        lines.append(f"{i:<4} {player:<22} {team:<14} {goals:>4} {assists:>4}")

    result = "\n".join(lines) + "\n_(G=Gols, A=Assistencias | fonte: football-data.org)_"
    _cache_set(cache_key, result)
    return result


# ─────────────────────────────────────────────────────────────
# FUNÇÕES PÚBLICAS (chamadas pelo agente via dados_copa)
# ─────────────────────────────────────────────────────────────

def proximos_jogos(time: str | None = None, limite: int = 5) -> str:
    """
    Retorna os próximos jogos da Copa 2026 (todos ou filtrado por seleção).

    Args:
        time: Nome da seleção (PT-BR ou EN). None = todos os jogos.
        limite: Quantos jogos retornar (máximo).

    Returns:
        Texto formatado pronto para o LLM.
    """
    team_api = _normalize_team(time) if time else None
    cache_key = f"fixtures_next_{team_api or 'all'}"
    cached = _cache_get(cache_key, _TTL["fixtures"])
    if cached:
        return cached

    # Tenta API-Football (pula se plano Free já bloqueou temporada 2026)
    data = None
    if not _api_football_2026_blocked:
        params: dict = {
            "league": _LEAGUE_ID,
            "season": _SEASON,
            "next": limite,
            "status": "NS",  # Not Started
        }
        if team_api:
            params["team"] = _resolve_team_id(team_api)
            if not params["team"]:
                params.pop("team")
        data = _api_get("fixtures", params)
    if data and data.get("response"):
        fixtures = data["response"]
        if not fixtures:
            result = f"Nenhum jogo futuro encontrado{' para ' + time if time else ''}."
        else:
            header = f"Próximos jogos{' de ' + time if time else ' da Copa 2026'}:"
            result = header + "\n\n" + "\n\n".join(
                _format_fixture_lines(fixtures[:limite], detailed=True)
            )

        _cache_set(cache_key, result)
        return result

    # 2ª fonte: football-data.org (gratuita, Copa 2026 completa)
    if _has_fdorg_key():
        fdorg_matches = _fdorg_proximos(team_api, limite)
        if fdorg_matches:
            header = f"Próximos jogos{' de ' + time if time else ' da Copa 2026'}:"
            lines = [_fdorg_match_line(m, detailed=True) for m in fdorg_matches]
            result = header + "\n\n" + "\n\n".join(lines) + "\n_(fonte: football-data.org)_"
            _cache_set(cache_key, result)
            return result

    # 3ª: API-Football por data (workaround plano Free)
    free_fixtures = _fixtures_by_date_free_tier(team_api, limite)
    if free_fixtures:
        header = f"Próximos jogos{' de ' + time if time else ' da Copa 2026'}:"
        result = (
            header + "\n\n"
            + "\n\n".join(_format_fixture_lines(free_fixtures, detailed=True))
            + "\n_(fonte: API-Football — plano Free)_"
        )
        _cache_set(cache_key, result)
        return result

    # 4ª: openfootball (calendário estático)
    result = _openfootball_proximos(time, limite)
    if result:
        _cache_set(cache_key, result)
        return result

    return (
        "Não foi possível obter os jogos no momento. "
        + (
            "Seu plano Free da API-Football não inclui a temporada 2026 completa. "
            if _has_api_football_key() and _last_api_error and "Free plans" in _last_api_error
            else "A API-Football pode estar offline ou sem chave configurada. "
        )
        + "Tente usar web_search para buscar os próximos jogos da Copa 2026."
    )


def resultado_jogo(time_ou_data: str) -> str:
    """
    Retorna o placar e eventos (gols, cartões) de um jogo recente.

    Args:
        time_ou_data: Nome da seleção ou data no formato DD/MM/YYYY.

    Returns:
        Texto formatado com placar e eventos principais.
    """
    cache_key = f"result_{time_ou_data.lower().replace('/', '_')}"
    cached = _cache_get(cache_key, _TTL["fixtures"])
    if cached:
        return cached

    # Interpreta o argumento: data ou nome de time
    team_api = None
    date_param = None
    try:
        parsed = datetime.strptime(time_ou_data.strip(), "%d/%m/%Y")
        date_param = parsed.strftime("%Y-%m-%d")
    except ValueError:
        team_api = _normalize_team(time_ou_data)

    params: dict = {
        "league": _LEAGUE_ID,
        "season": _SEASON,
        "last": 5,
    }
    if date_param:
        params = {
            "league": _LEAGUE_ID,
            "season": _SEASON,
            "date": date_param,
        }
    elif team_api:
        tid = _resolve_team_id(team_api)
        if tid:
            params["team"] = tid
        params["last"] = 5

    data = _api_get("fixtures", params)
    if data and data.get("response"):
        fixtures = [
            f for f in data["response"]
            if f.get("fixture", {}).get("status", {}).get("short") in ("FT", "AET", "PEN")
        ]
        if fixtures:
            lines = []
            for f in fixtures[:3]:
                home = _team_pt(f.get("teams", {}).get("home", {}).get("name", "?"))
                away = _team_pt(f.get("teams", {}).get("away", {}).get("name", "?"))
                goals_h = f.get("goals", {}).get("home", 0)
                goals_a = f.get("goals", {}).get("away", 0)
                date = _utc_to_brasilia(f.get("fixture", {}).get("date", ""))
                fid = f.get("fixture", {}).get("id")
                events_str = _get_events(fid)
                lines.append(
                    f"**{home} {goals_h} x {goals_a} {away}**\n"
                    f"Data: {date}\n"
                    f"{events_str}"
                )
            result = "\n\n---\n\n".join(lines)
            _cache_set(cache_key, result)
            return result

    # 2ª fonte: football-data.org
    if _has_fdorg_key():
        fdorg_matches = _fdorg_resultado(team_api, date_param)
        if fdorg_matches:
            lines = [_fdorg_match_line(m) for m in reversed(fdorg_matches[-3:])]
            result = "\n".join(lines) + "\n_(fonte: football-data.org)_"
            _cache_set(cache_key, result)
            return result

    # 3ª fonte: openfootball (tem placares dos jogos encerrados)
    openfb_result = _openfootball_resultado(time_ou_data)
    if openfb_result:
        _cache_set(cache_key, openfb_result)
        return openfb_result

    return (
        "Resultado não disponível nas minhas fontes de dados estruturados. "
        "Não use web_search para inferir o placar — resultados de busca podem estar incorretos. "
        "Informe ao usuário que o resultado ainda não está disponível e sugira verificar "
        "em fontes oficiais: FIFA.com, CBF (para o Brasil) ou Globoesporte."
    )


def _get_events(fixture_id: int | None) -> str:
    """Busca eventos (gols, cartões) de uma partida específica."""
    if not fixture_id:
        return ""
    data = _api_get("fixtures/events", {"fixture": fixture_id})
    if not data or not data.get("response"):
        return ""
    events = data["response"]
    gols = []
    cartoes = []
    for ev in events:
        minuto = ev.get("time", {}).get("elapsed", "?")
        tipo = ev.get("type", "")
        detail = ev.get("detail", "")
        jogador = ev.get("player", {}).get("name", "")
        team = _team_pt(ev.get("team", {}).get("name", ""))
        if tipo == "Goal":
            gols.append(f"  ⚽ {minuto}' {jogador} ({team}){' — ' + detail if detail not in ('Normal Goal', '') else ''}")
        elif tipo == "Card":
            emoji = "🟨" if "Yellow" in detail else "🟥"
            cartoes.append(f"  {emoji} {minuto}' {jogador} ({team})")
    parts = []
    if gols:
        parts.append("Gols:\n" + "\n".join(gols))
    if cartoes:
        parts.append("Cartões:\n" + "\n".join(cartoes))
    return "\n".join(parts)


def escalacao(jogo: str) -> str:
    """
    Retorna a escalação de uma partida da Copa 2026.

    Args:
        jogo: Nome de uma das seleções ou "ultima" para o jogo mais recente do Brasil.

    Returns:
        Texto com titulares, banco e técnico de cada equipe.
    """
    cache_key = f"lineup_{jogo.lower().strip()}"
    cached = _cache_get(cache_key, _TTL["lineups"])
    if cached:
        return cached

    # Descobre o fixture_id do último jogo da equipe
    team_api = _normalize_team(jogo) if jogo.lower() != "ultima" else "Brazil"
    fdorg_team = _find_fdorg_team(team_api)
    if fdorg_team:
        team_api = fdorg_team.get("name", team_api)

    tid = _resolve_team_id(team_api)
    if not tid:
        if fdorg_team:
            team_pt = _team_pt(fdorg_team.get("name", team_api))
            last = _fdorg_last_finished_match(fdorg_team)
            return _escalacao_indisponivel(jogo, team_pt, last)
        return (
            "Não consegui identificar a seleção. "
            "Tente: 'Brasil', 'Argentina', 'França', 'Noruega', etc."
        )

    data = _api_get("fixtures", {
        "league": _LEAGUE_ID,
        "season": _SEASON,
        "team": tid,
        "last": 1,
    })
    if not data or not data.get("response"):
        team_pt = _team_pt(team_api)
        last = _fdorg_last_finished_match(fdorg_team) if fdorg_team else None
        if last or (_last_api_error and "season" in str(_last_api_error).lower()):
            return _escalacao_indisponivel(jogo, team_pt, last)
        return (
            "Não encontrei partidas recentes para buscar escalação. "
            "Use web_search para buscar a escalação na Copa 2026."
        )

    fixture_id = data["response"][0].get("fixture", {}).get("id")
    if not fixture_id:
        return "Não foi possível obter o ID da partida."

    lineup_data = _api_get("fixtures/lineups", {"fixture": fixture_id})
    if not lineup_data or not lineup_data.get("response"):
        return (
            "Escalação ainda não disponível para essa partida. "
            "(Normalmente publicada ~1h antes do jogo.)"
        )

    lines = []
    for team_lineup in lineup_data["response"]:
        tname = _team_pt(team_lineup.get("team", {}).get("name", "?"))
        coach = team_lineup.get("coach", {}).get("name", "")
        formation = team_lineup.get("formation", "")
        starters = [
            f"  {p['player']['number']}. {p['player']['name']} ({p['player']['pos']})"
            for p in team_lineup.get("startXI", [])
            if p.get("player")
        ]
        subs = [
            f"  {p['player']['number']}. {p['player']['name']}"
            for p in team_lineup.get("substitutes", [])
            if p.get("player")
        ]
        block = f"**{tname}** (Formação: {formation})\nTécnico: {coach}\nTitulares:\n"
        block += "\n".join(starters)
        if subs:
            block += f"\nBanco:\n" + "\n".join(subs)
        lines.append(block)

    result = "\n\n".join(lines)
    _cache_set(cache_key, result)
    return result


def _find_fdorg_team(time: str) -> dict | None:
    """Busca uma seleção na lista football-data.org da Copa 2026."""
    team_api = _normalize_team(time)
    teams = _fdorg_competition_teams()
    if not teams:
        return None

    target = team_api.lower()
    for t in teams:
        for n in (t.get("name", ""), t.get("shortName", ""), t.get("tla", "")):
            if n.lower() == target or target in n.lower():
                return t

    time_lower = time.lower().strip()
    for t in teams:
        pt = _team_pt(t.get("name", "")).lower()
        if time_lower == pt or time_lower in pt or pt in time_lower:
            return t
    return None


def _fdorg_last_finished_match(team: dict) -> dict | None:
    """Última partida encerrada da seleção na Copa 2026 (football-data.org)."""
    tname = team.get("name", "")
    matches = _fdorg_competition_matches()
    if not matches:
        return None

    finished = [
        m for m in matches
        if tname in (
            m.get("homeTeam", {}).get("name"),
            m.get("awayTeam", {}).get("name"),
        )
        and m.get("status") == "FINISHED"
    ]
    if not finished:
        return None
    return sorted(finished, key=lambda m: m.get("utcDate", ""), reverse=True)[0]


def _escalacao_indisponivel(time: str, team_pt: str, match: dict | None = None) -> str:
    """Mensagem quando a escalação titular não está nas fontes estruturadas."""
    lines = [
        f"Escalação titular de *{team_pt}* não disponível nas fontes estruturadas "
        "(limite do plano gratuito da API-Football para a temporada 2026).",
    ]
    if match:
        home = _team_pt(match["homeTeam"]["name"])
        away = _team_pt(match["awayTeam"]["name"])
        score = match.get("score", {}).get("fullTime", {})
        sh, sa = score.get("home"), score.get("away")
        placar = f"{sh} x {sa}" if sh is not None and sa is not None else "—"
        date = match.get("utcDate", "")[:10]
        lines.append(
            f"\nÚltima partida na Copa: *{home}* {placar} *{away}* ({date})."
        )
    lines.append(
        "\n*Alternativas:*\n"
        f"- Pergunte em texto livre (ex.: escalação titular da {team_pt}) para eu buscar na web\n"
        f"- /elenco {time} — elenco convocado (26 jogadores)\n"
        "- Escalação oficial de partida costuma sair ~1h antes do jogo"
    )
    return "\n".join(lines)


def elenco(time: str) -> str:
    """
    Retorna o elenco convocado de uma seleção para a Copa 2026.
    Fonte: football-data.org /v4/competitions/WC/teams
    """
    team_api = _normalize_team(time)
    cache_key = f"elenco_{team_api.lower()}"
    cached = _cache_get(cache_key, 3600)
    if cached:
        return cached

    found = _find_fdorg_team(time)
    if not found:
        return (
            f"Não encontrei '{time}' entre os participantes da Copa 2026. "
            "Tente: 'Brasil', 'Argentina', 'França', 'Noruega', etc."
        )

    squad = found.get("squad", [])
    team_name = _team_pt(found.get("name", time))

    if not squad:
        return f"Elenco de {team_name} ainda não publicado.\n_(fonte: football-data.org)_"

    coach_info = found.get("coach") or {}
    coach_name = coach_info.get("name", "")

    pos_order = ["Goalkeeper", "Defence", "Midfield", "Offence"]
    pos_label = {
        "Goalkeeper": "Goleiros",
        "Defence": "Defensores",
        "Midfield": "Meias",
        "Offence": "Atacantes",
    }
    groups: dict[str, list[str]] = {p: [] for p in pos_order}
    for p in squad:
        pos = p.get("position", "Offence")
        if pos not in groups:
            pos = "Offence"
        num = p.get("shirtNumber")
        name = p.get("name", "?")
        entry = f"  {'#'+str(num):<4} {name}" if num else f"  {name}"
        groups[pos].append(entry)

    lines = [f"**Elenco — {team_name} (Copa 2026)**"]
    if coach_name:
        lines.append(f"Técnico: {coach_name}\n")
    for pos in pos_order:
        if groups[pos]:
            lines.append(f"**{pos_label[pos]}**")
            lines.extend(groups[pos])
            lines.append("")

    lines.append("_(fonte: football-data.org)_")
    result = "\n".join(lines)
    _cache_set(cache_key, result)
    return result


def classificacao(grupo: str | None = None) -> str:
    """
    Retorna a classificação da fase de grupos da Copa 2026.

    Args:
        grupo: Letra do grupo ("A", "B", ...) ou None para todos.

    Returns:
        Tabela de classificação formatada.
    """
    cache_key = f"standings_{grupo or 'all'}"
    cached = _cache_get(cache_key, _TTL["standings"])
    if cached:
        return cached

    data = None
    if not _api_football_2026_blocked:
        data = _api_get("standings", {
            "league": _LEAGUE_ID,
            "season": _SEASON,
        })

    if data and data.get("response"):
        league_data = data["response"][0].get("league", {})
        standings = league_data.get("standings", [])
        if not standings:
            return "Classificação não disponível ainda (fase de grupos não iniciada)."

        lines = []
        for group_standings in standings:
            if not group_standings:
                continue
            grp_name = group_standings[0].get("group", "Grupo")
            if grupo and grupo.upper() not in grp_name.upper():
                continue
            lines.append(f"\n**{grp_name}**")
            lines.append(f"{'#':<3} {'Seleção':<20} {'J':>3} {'V':>3} {'E':>3} {'D':>3} {'GP':>4} {'GC':>4} {'Pts':>4}")
            lines.append("-" * 52)
            for team in group_standings:
                pos = team.get("rank", "?")
                name = _team_pt(team.get("team", {}).get("name", "?"))[:18]
                all_s = team.get("all", {})
                j = all_s.get("played", 0)
                v = all_s.get("win", 0)
                e = all_s.get("draw", 0)
                d = all_s.get("lose", 0)
                gp = all_s.get("goals", {}).get("for", 0)
                gc = all_s.get("goals", {}).get("against", 0)
                pts = team.get("points", 0)
                lines.append(f"{pos:<3} {name:<20} {j:>3} {v:>3} {e:>3} {d:>3} {gp:>4} {gc:>4} {pts:>4}")

        if not lines:
            return f"Grupo {grupo} não encontrado." if grupo else "Nenhuma classificação disponível."

        result = "**Classificação — Copa do Mundo 2026**\n" + "\n".join(lines)
        _cache_set(cache_key, result)
        return result

    # 2ª fonte: football-data.org (classificação completa com pontuação)
    if _has_fdorg_key():
        fdorg_stand = _fdorg_classificacao(grupo)
        if fdorg_stand:
            _cache_set(cache_key, fdorg_stand)
            return fdorg_stand

    # Fallback: openfootball (lista de times por grupo, sem pontuação)
    result = _openfootball_classificacao(grupo)
    if result:
        _cache_set(cache_key, result)
        return result

    return (
        "Classificação indisponível no momento. "
        + (
            "O plano Free da API-Football não inclui standings da temporada 2026. "
            if _has_api_football_key() and _last_api_error and "Free plans" in _last_api_error
            else "A fase de grupos pode ainda não ter começado, "
            "ou a API-Football está indisponível. "
        )
    )


def jogos_ao_vivo() -> str:
    """
    Retorna os jogos da Copa 2026 em andamento neste momento.

    Returns:
        Placar ao vivo e minuto de cada partida em andamento.
    """
    cached = _cache_get("live", _TTL["live"])
    if cached:
        return cached

    fixtures: list[dict] | None = None
    if not _api_football_2026_blocked:
        data = _api_get("fixtures", {
            "league": _LEAGUE_ID,
            "season": _SEASON,
            "live": "all",
        })
        if data is not None and "response" in data:
            fixtures = data["response"]

    if fixtures is None and _has_api_football_key():
        # Plano Free: season=2026 bloqueada — busca todos ao vivo e filtra Copa
        live_data = _api_get("fixtures", {"live": "all"})
        if live_data is not None and "response" in live_data:
            fixtures = [
                f for f in live_data["response"]
                if f.get("league", {}).get("id") == _LEAGUE_ID
            ]

    if fixtures is not None:
        if not fixtures:
            # Sem jogos ao vivo na API-Football — tenta football-data.org
            if _has_fdorg_key():
                fdorg_live = _fdorg_ao_vivo()
                if fdorg_live:
                    lines = [_fdorg_match_line(m) for m in fdorg_live]
                    result = "**Jogos ao vivo — Copa 2026:**\n" + "\n".join(lines) + "\n_(fonte: football-data.org)_"
                    _cache_set("live", result)
                    return result
            result = "Nenhum jogo da Copa 2026 acontecendo agora."
        else:
            lines = []
            for f in fixtures:
                home = _team_pt(f.get("teams", {}).get("home", {}).get("name", "?"))
                away = _team_pt(f.get("teams", {}).get("away", {}).get("name", "?"))
                gh = f.get("goals", {}).get("home", 0)
                ga = f.get("goals", {}).get("away", 0)
                elapsed = f.get("fixture", {}).get("status", {}).get("elapsed", "?")
                lines.append(f"⚽ **{home} {gh} x {ga} {away}** — {elapsed}'")
            result = "**Jogos ao vivo — Copa 2026:**\n" + "\n".join(lines)

        _cache_set("live", result)
        return result

    # API-Football não respondeu — tenta football-data.org
    if _has_fdorg_key():
        fdorg_live = _fdorg_ao_vivo()
        if fdorg_live:
            lines = [_fdorg_match_line(m) for m in fdorg_live]
            result = "**Jogos ao vivo — Copa 2026:**\n" + "\n".join(lines) + "\n_(fonte: football-data.org)_"
            _cache_set("live", result)
            return result
        result = "Nenhum jogo da Copa 2026 acontecendo agora."
        _cache_set("live", result)
        return result

    if not _has_api_football_key():
        msg = "Não há jogos ao vivo no momento (chave API_FOOTBALL_KEY não configurada)."
    elif _last_api_error and "Free plans" in _last_api_error:
        msg = "Não há jogos ao vivo no momento."
    else:
        msg = "Não há jogos ao vivo no momento ou a API-Football está indisponível."

    return msg + "\nUse /jogos para ver os próximos jogos."


# ─────────────────────────────────────────────────────────────
# NOVAS FUNÇÕES — ARTILHEIROS, MATA-MATA, H2H
# ─────────────────────────────────────────────────────────────

def artilheiros(limite: int = 10) -> str:
    """
    Retorna a tabela de artilheiros e assistências da Copa 2026.

    Args:
        limite: Quantos jogadores retornar.

    Returns:
        Texto formatado com posição, jogador, seleção, gols, assistências.
    """
    cache_key = "topscorers"
    cached = _cache_get(cache_key, 1800)  # 30 min
    if cached:
        return cached

    data = None
    if not _api_football_2026_blocked:
        data = _api_get("players/topscorers", {
            "league": _LEAGUE_ID,
            "season": _SEASON,
        })

    if data and data.get("response"):
        players = data["response"][:limite]
        if not players:
            return "Artilharia ainda não disponível (nenhum gol marcado)."

        lines = ["**Artilheiros — Copa do Mundo 2026**\n"]
        lines.append(f"{'#':<4} {'Jogador':<22} {'Seleção':<14} {'G':>4} {'A':>4} {'CA':>4} {'CV':>4}")
        lines.append("-" * 58)
        for i, entry in enumerate(players, 1):
            player = entry.get("player", {})
            stats = entry.get("statistics", [{}])[0]
            name = player.get("name", "?")[:20]
            team = _team_pt(stats.get("team", {}).get("name", "?"))[:12]
            goals = stats.get("goals", {}).get("total", 0) or 0
            assists = stats.get("goals", {}).get("assists", 0) or 0
            yellow = stats.get("cards", {}).get("yellow", 0) or 0
            red = stats.get("cards", {}).get("red", 0) or 0
            lines.append(f"{i:<4} {name:<22} {team:<14} {goals:>4} {assists:>4} {yellow:>4} {red:>4}")

        result = "\n".join(lines) + "\n_(G=Gols, A=Assistencias, CA=Amarelo, CV=Vermelho)_"
        _cache_set(cache_key, result)
        return result

    # 2ª fonte: football-data.org (artilheiros da Copa)
    if _has_fdorg_key():
        fdorg_result = _fdorg_artilheiros(limite)
        if fdorg_result:
            _cache_set(cache_key, fdorg_result)
            return fdorg_result

    return (
        "Artilharia indisponível no momento nas fontes estruturadas. "
        "Use web_search para buscar os artilheiros da Copa 2026."
    )


_KNOCKOUT_ROUNDS = [
    "Round of 32",
    "Round of 16",
    "Quarter-finals",
    "Semi-finals",
    "3rd Place Final",
    "Final",
]

_FASE_MAP: dict[str, str] = {
    "oitavas": "Round of 16",
    "quartas": "Quarter-finals",
    "semifinal": "Semi-finals",
    "semis": "Semi-finals",
    "terceiro": "3rd Place Final",
    "terceiro lugar": "3rd Place Final",
    "final": "Final",
    "round of 32": "Round of 32",
    "round of 16": "Round of 16",
}


def mata_mata(fase: str = "") -> str:
    """
    Retorna os jogos do mata-mata (fase eliminatória) da Copa 2026.

    Args:
        fase: Fase específica ("oitavas", "quartas", "semifinal", "final") ou
              vazia para o round mais avançado disponível.

    Returns:
        Texto formatado com as partidas do mata-mata.
    """
    fase_api = _FASE_MAP.get(fase.lower().strip(), fase.strip() or "")
    cache_key = f"knockout_{fase_api or 'all'}"
    cached = _cache_get(cache_key, 600)
    if cached:
        return cached

    data = _api_get("fixtures", {
        "league": _LEAGUE_ID,
        "season": _SEASON,
    })

    if not data or not data.get("response"):
        result = (
            "Dados do mata-mata indisponiveis no momento. "
            "Tente web_search para buscar o chaveamento da Copa 2026."
        )
        return result

    # Filtra apenas rounds de mata-mata
    knockout_fixtures: dict[str, list] = {}
    for f in data["response"]:
        round_name = f.get("league", {}).get("round", "")
        if not any(kr.lower() in round_name.lower() for kr in _KNOCKOUT_ROUNDS):
            continue
        # Filtro de fase específica
        if fase_api and fase_api.lower() not in round_name.lower():
            continue
        knockout_fixtures.setdefault(round_name, []).append(f)

    if not knockout_fixtures:
        if fase_api:
            result = (
                f"Fase '{fase_api}' ainda nao disponivel ou nao iniciada. "
                "A Copa 2026 pode ainda estar na fase de grupos."
            )
        else:
            result = (
                "Mata-mata ainda nao iniciado. "
                "A fase de grupos da Copa 2026 ainda esta em andamento."
            )
        return result

    # Ordena rounds pelo índice em _KNOCKOUT_ROUNDS
    def round_order(r: str) -> int:
        for i, kr in enumerate(_KNOCKOUT_ROUNDS):
            if kr.lower() in r.lower():
                return i
        return 99

    lines = ["**Mata-mata — Copa do Mundo 2026**"]
    for round_name in sorted(knockout_fixtures.keys(), key=round_order):
        lines.append(f"\n{round_name}")
        lines.append("-" * 40)
        for f in sorted(knockout_fixtures[round_name],
                        key=lambda x: x.get("fixture", {}).get("date", "")):
            home = _team_pt(f.get("teams", {}).get("home", {}).get("name", "?"))
            away = _team_pt(f.get("teams", {}).get("away", {}).get("name", "?"))
            status = f.get("fixture", {}).get("status", {}).get("short", "NS")
            date_str = _utc_to_brasilia(f.get("fixture", {}).get("date", ""))
            if status in ("FT", "AET", "PEN"):
                gh = f.get("goals", {}).get("home", 0)
                ga = f.get("goals", {}).get("away", 0)
                lines.append(f"  {home} {gh} x {ga} {away} (Encerrado)")
            else:
                lines.append(f"  {home} x {away} — {date_str}")

    result = "\n".join(lines)
    _cache_set(cache_key, result)
    return result


def h2h(time1: str, time2: str) -> str:
    """
    Retorna o histórico de confrontos diretos entre duas seleções na Copa do Mundo.

    Args:
        time1: Nome da primeira seleção (PT-BR aceito).
        time2: Nome da segunda seleção (PT-BR aceito).

    Returns:
        Texto com total de jogos, vitórias e últimos confrontos em Copa.
    """
    t1_api = _normalize_team(time1)
    t2_api = _normalize_team(time2)
    id1 = _resolve_team_id(t1_api)
    id2 = _resolve_team_id(t2_api)

    if not id1 or not id2:
        unresolved = time1 if not id1 else time2
        return (
            f"Nao consegui identificar a selecao '{unresolved}'. "
            "Tente o nome em ingles ou use web_search para o retrospecto."
        )

    # Cache — H2H historico nao muda
    cache_key = f"h2h_{min(id1, id2)}_{max(id1, id2)}"
    cached = _cache_get(cache_key, 86400)
    if cached:
        return cached

    data = _api_get("fixtures/headtohead", {
        "h2h": f"{id1}-{id2}",
        "league": _LEAGUE_ID,
    })

    if not data or not data.get("response"):
        return (
            f"Historico de {t1_api} x {t2_api} em Copas do Mundo nao encontrado. "
            "Tente web_search para buscar o retrospecto completo."
        )

    fixtures = data["response"]
    if not fixtures:
        return f"Nenhum confronto entre {t1_api} e {t2_api} em Copas do Mundo encontrado."

    t1_wins = 0
    t2_wins = 0
    draws = 0
    recent: list[str] = []

    for f in fixtures:
        home_id = f.get("teams", {}).get("home", {}).get("id")
        away_id = f.get("teams", {}).get("away", {}).get("id")
        home_name = _team_pt(f.get("teams", {}).get("home", {}).get("name", "?"))
        away_name = _team_pt(f.get("teams", {}).get("away", {}).get("name", "?"))
        gh = f.get("goals", {}).get("home", 0) or 0
        ga = f.get("goals", {}).get("away", 0) or 0
        date_str = _utc_to_brasilia(f.get("fixture", {}).get("date", ""))

        # Contabiliza vitórias pelo ID (independente de home/away)
        if gh > ga:
            if home_id == id1:
                t1_wins += 1
            else:
                t2_wins += 1
        elif ga > gh:
            if away_id == id1:
                t1_wins += 1
            else:
                t2_wins += 1
        else:
            draws += 1

        recent.append(f"  {home_name} {gh} x {ga} {away_name} ({date_str})")

    total = len(fixtures)
    t1_pt = _team_pt(t1_api)
    t2_pt = _team_pt(t2_api)
    lines = [
        f"**{t1_pt} x {t2_pt} — Retrospecto em Copas do Mundo**\n",
        f"Total de jogos: {total}",
        f"Vitórias {t1_pt}: {t1_wins}",
        f"Empates: {draws}",
        f"Vitórias {t2_pt}: {t2_wins}",
        "",
        "Confrontos:",
    ]
    lines.extend(recent[-5:])  # últimos 5

    result = "\n".join(lines)
    _cache_set(cache_key, result)
    return result


# ─────────────────────────────────────────────────────────────
# RESOLUÇÃO DE TEAM ID (API-Football)
# ─────────────────────────────────────────────────────────────

_TEAM_IDS: dict[str, int] = {
    # Cacheado localmente para evitar uma chamada à API por pergunta
    # Fonte: endpoint /teams?league=1&season=2026
    "Brazil": 6,
    "Argentina": 26,
    "France": 2,
    "Germany": 25,
    "England": 10,
    "Spain": 9,
    "Portugal": 27,
    "Netherlands": 1024,
    "Italy": 768,
    "USA": 2415,
    "Mexico": 16,
    "Canada": 96,
    "Uruguay": 28,
    "Colombia": 60,
    "Japan": 35,
    "South Korea": 36,
    "Morocco": 652,
    "Senegal": 859,
    "Nigeria": 89,
    "Egypt": 88,
    "Australia": 742,
}


def _resolve_team_id(team_name: str) -> int | None:
    """Resolve o ID de uma seleção na API-Football."""
    if team_name in _TEAM_IDS:
        return _TEAM_IDS[team_name]

    for name, tid in _TEAM_IDS.items():
        if name.lower() == team_name.lower():
            return tid

    # Cache de buscas dinâmicas — inclusive resultados negativos (sentinel "__none__")
    cache_key = f"team_id_{team_name.lower()}"
    cached = _cache_get(cache_key, 3600)
    if cached is not None:
        return None if cached == "__none__" else int(cached)

    data = _api_get("teams", {
        "league": _LEAGUE_ID,
        "season": _SEASON,
        "search": team_name,
    })
    if data and data.get("response"):
        tid = data["response"][0].get("team", {}).get("id")
        if tid:
            _cache_set(cache_key, tid)
            return tid

    _cache_set(cache_key, "__none__")
    return None


def jogos_hoje() -> str:
    """
    Retorna todos os jogos da Copa 2026 programados para hoje (horário de Brasília).
    Inclui resultado se o jogo já encerrou, ou horário se ainda não começou.
    """
    today_br = datetime.now(tz=_BR_TZ).date()
    today_str = today_br.isoformat()
    cache_key = f"today_{today_str}"

    cached = _cache_get(cache_key, 300)
    if cached:
        return cached

    header = f"Jogos de hoje — {today_br.strftime('%d/%m/%Y')}:\n\n"

    # API-Football — consulta por data (funciona no free tier)
    data = _api_get("fixtures", {"date": today_str})
    if data and data.get("response"):
        copa_fixtures = [
            f for f in data["response"]
            if f.get("league", {}).get("id") == _LEAGUE_ID
        ]
        if copa_fixtures:
            result = header + "\n\n".join(_format_fixture_lines(copa_fixtures, detailed=True))
            _cache_set(cache_key, result)
            return result
        result = f"Nenhum jogo da Copa 2026 hoje ({today_br.strftime('%d/%m/%Y')})."
        _cache_set(cache_key, result)
        return result

    # football-data.org — filtra do cache compartilhado (evita req extra)
    if _has_fdorg_key():
        all_matches = _fdorg_competition_matches()
        if all_matches:
            today_matches = [
                m for m in all_matches
                if m.get("utcDate", "").startswith(today_str)
                or datetime.fromisoformat(
                    m.get("utcDate", "1970-01-01T00:00:00+00:00")
                ).astimezone(_BR_TZ).date().isoformat() == today_str
            ]
            if today_matches:
                lines = [_fdorg_match_line(m, detailed=True) for m in today_matches]
                result = header + "\n\n".join(lines) + "\n_(fonte: football-data.org)_"
                _cache_set(cache_key, result)
                return result

    # openfootball — filtra por data exata
    of_data = _load_openfootball()
    if of_data:
        lines = []
        for match in of_data.get("matches", []):
            if match.get("date", "") != today_str:
                continue
            t1 = match.get("team1", {})
            t2 = match.get("team2", {})
            n1 = _team_pt(t1.get("name", str(t1)) if isinstance(t1, dict) else str(t1))
            n2 = _team_pt(t2.get("name", str(t2)) if isinstance(t2, dict) else str(t2))
            grp = match.get("group", match.get("round", ""))
            score = match.get("score", {})
            ft = score.get("ft")
            dt_utc = _parse_openfootball_dt(match.get("date", ""), match.get("time", ""))
            if ft and len(ft) >= 2:
                lines.append(f"• **{n1} {ft[0]} x {ft[1]} {n2}** (Encerrado) | {grp}")
            elif dt_utc:
                hora = dt_utc.astimezone(_BR_TZ).strftime("%H:%M")
                lines.append(f"• {n1} x {n2} — {hora} (Brasília) | {grp}")
        if lines:
            result = header + "\n".join(lines) + "\n" + _fallback_source_note()
            _cache_set(cache_key, result)
            return result

    result = f"Nenhum jogo da Copa 2026 hoje ({today_br.strftime('%d/%m/%Y')})."
    _cache_set(cache_key, result)
    return result


# ─────────────────────────────────────────────────────────────
# INTERFACE UNIFICADA (chamada pelo agente)
# ─────────────────────────────────────────────────────────────

def dados_copa(intencao: str, time: str = "", grupo: str = "") -> str:
    """
    Interface unificada para o agente consultar dados da Copa 2026.

    Args:
        intencao: O que o agente quer saber. Valores:
            "proximos_jogos"  — próximos jogos (geral ou de uma seleção)
            "resultado"       — placar de jogo recente
            "escalacao"       — escalação de uma partida
            "elenco"          — elenco convocado de uma seleção (26 jogadores)
            "classificacao"   — tabela da fase de grupos
            "ao_vivo"         — jogos acontecendo agora
            "artilheiros"     — tabela de artilheiros e assistências
            "mata_mata"       — fase eliminatória (oitavas, quartas, semi, final)
            "h2h"             — retrospecto entre dois times (use time="Brasil x Argentina")
        time: Nome da seleção (PT-BR aceito), ou "Time1 x Time2" para h2h.
        grupo: Letra do grupo ("A"–"L"). Usado com intenção "classificacao".

    Returns:
        String com os dados formatados para o LLM.
    """
    intencao = intencao.strip().lower()

    if intencao in ("hoje", "jogos_hoje", "today"):
        return jogos_hoje()

    if intencao in ("proximos_jogos", "proximo", "jogos", "agenda"):
        return proximos_jogos(time or None)

    elif intencao in ("resultado", "placar", "resultado_jogo"):
        if not time:
            return "Especifique um time ou data para buscar o resultado."
        return resultado_jogo(time)

    elif intencao in ("escalacao", "lineup", "escalação"):
        if not time:
            return "Especifique a seleção para buscar a escalação."
        return escalacao(time)

    elif intencao in ("elenco", "convocados", "squad", "convocacao", "convocação", "elenco_time"):
        if not time:
            return "Especifique uma seleção. Exemplo: 'elenco Brasil'."
        return elenco(time)

    elif intencao in ("classificacao", "tabela", "grupo", "classificação"):
        return classificacao(grupo or None)

    elif intencao in ("ao_vivo", "live", "agora"):
        return jogos_ao_vivo()

    elif intencao in ("artilheiros", "artilheiro", "gols", "goleadores", "estatisticas"):
        return artilheiros()

    elif intencao in ("mata_mata", "eliminatorias", "eliminatórias", "oitavas",
                      "quartas", "semifinal", "semis", "final", "knockout"):
        _fase_intencao_map = {
            "oitavas": "Round of 16",
            "quartas": "Quarter-finals",
            "semifinal": "Semi-finals",
            "semis": "Semi-finals",
            "final": "Final",
        }
        fase = _fase_intencao_map.get(intencao, "")
        return mata_mata(fase)

    elif intencao in ("h2h", "historico", "histórico", "retrospecto", "confronto"):
        if not time:
            return (
                "Especifique dois times para o retrospecto. "
                "Exemplo: use o campo 'time' com 'Brasil x Argentina'."
            )
        partes = [p.strip() for p in time.replace(" x ", "x").replace(" X ", "x").split("x")]
        if len(partes) == 2:
            return h2h(partes[0], partes[1])
        return (
            f"Formato inválido para H2H: '{time}'. "
            "Use 'Time1 x Time2', por exemplo: 'Brasil x Argentina'."
        )

    else:
        return (
            f"Intenção '{intencao}' não reconhecida. "
            "Valores válidos: proximos_jogos, resultado, escalacao, elenco, classificacao, "
            "ao_vivo, artilheiros, mata_mata, h2h."
        )
