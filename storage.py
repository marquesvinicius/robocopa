"""
storage.py — Cliente Redis compartilhado (preferences.py + notifications.py)

Se REDIS_URL estiver configurado, usa Redis (Render Redis / Upstash).
Caso contrário, retorna None e os módulos usam fallback em arquivo.

Mantém uma única conexão reutilizada por toda a aplicação.
"""

import os

_client = None
_initialized = False


def get_redis():
    """
    Retorna o cliente Redis se disponível, None caso contrário.
    Lazy initialization — testa a conexão uma única vez no primeiro uso.
    """
    global _client, _initialized
    if _initialized:
        return _client
    _initialized = True

    url = os.getenv("REDIS_URL", "").strip()
    if not url:
        return None

    try:
        import redis
        c = redis.from_url(url, decode_responses=True, socket_connect_timeout=5)
        c.ping()
        _client = c
        print(f"[storage] Redis conectado: {url[:40]}...")
    except Exception as exc:
        print(f"[storage] Redis indisponível ({exc}) — usando fallback em arquivo.")
        _client = None

    return _client
