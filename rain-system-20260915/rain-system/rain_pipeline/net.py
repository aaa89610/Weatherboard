"""共用 HTTP 取得：重試、逾時、錯誤分類（區分「網路授權被擋」與「服務端錯誤」）。"""
from __future__ import annotations

import time

import requests


class FetchError(RuntimeError):
    def __init__(self, source: str, kind: str, detail: str):
        super().__init__(f"[{source}] {kind}: {detail}")
        self.source, self.kind, self.detail = source, kind, detail


BLOCKED_HINTS = ("403", "407", "Tunnel connection failed", "CONNECT tunnel failed",
                 "network approval", "ProxyError")


def _request(url: str, params: dict | None, source: str, timeout: float) -> requests.Response:
    try:
        return requests.get(url, params=params, timeout=timeout)
    except requests.exceptions.ProxyError as e:
        # 代理拒絕 = 執行環境的網路允許清單沒放行，重試無用
        raise FetchError(source, "network_blocked", str(e)[:300]) from e
    except requests.exceptions.RequestException as e:
        msg = str(e)
        kind = "network_blocked" if any(h in msg for h in BLOCKED_HINTS) else "network_error"
        raise FetchError(source, kind, msg[:300]) from e


def get_json(url: str, params: dict | None, source: str, timeout: float = 30,
             retries: int = 3, backoff: float = 2.0) -> object:
    last: FetchError | None = None
    for attempt in range(retries):
        try:
            r = _request(url, params, source, timeout)
        except FetchError as e:
            if e.kind == "network_blocked":
                raise
            last = e
        else:
            if r.status_code == 200:
                return r.json()
            if r.status_code in (429,) or r.status_code >= 500:
                last = FetchError(source, "server_error", f"HTTP {r.status_code}: {r.text[:200]}")
            elif r.status_code == 400:
                raise FetchError(source, "bad_request", r.text[:300])   # 參數錯誤不重試
            else:
                raise FetchError(source, "http_error", f"HTTP {r.status_code}: {r.text[:200]}")
        if attempt < retries - 1:
            time.sleep(backoff * (attempt + 1))
    assert last is not None
    raise last


def get_bytes(url: str, source: str, timeout: float = 30) -> bytes:
    r = _request(url, None, source, timeout)
    if r.status_code != 200:
        raise FetchError(source, "http_error", f"HTTP {r.status_code}")
    return r.content
