# betfair_client.py
#
# Betfair API client for:
#  - Login via identitysso
#  - Betting JSON-RPC (SportsAPING)
#  - Account JSON-RPC (AccountAPING)
#
# Supports DUMMY mode for safe UI testing.

import os
import re
import time
import json
import datetime as dt
from typing import Any, Dict, List, Optional, Tuple

import requests


IDENTITY_LOGIN_URL = "https://identitysso.betfair.com/api/login"
BETTING_RPC_URL = "https://api.betfair.com/exchange/betting/json-rpc/v1"
ACCOUNT_RPC_URL = "https://api.betfair.com/exchange/account/json-rpc/v1"

HORSE_RACING_EVENT_TYPE_ID = "7"


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _parse_iso_utc(s: str) -> Optional[dt.datetime]:
    if not s or not isinstance(s, str):
        return None
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        return dt.datetime.fromisoformat(s).astimezone(dt.timezone.utc)
    except Exception:
        return None


def _iso_z(d: dt.datetime) -> str:
    if d.tzinfo is None:
        d = d.replace(tzinfo=dt.timezone.utc)
    else:
        d = d.astimezone(dt.timezone.utc)
    return d.isoformat().replace("+00:00", "Z")


def _looks_like_novice_hurdle(text: str) -> bool:
    if not text:
        return False
    t = text.lower()
    novice = ("novice" in t) or re.search(r"\bnov\b", t) is not None
    hurdle = ("hurdle" in t) or re.search(r"\bhrd\b", t) is not None or re.search(r"\bhurd\b", t) is not None or re.search(r"\bhdl\b", t) is not None
    return bool(novice and hurdle)


class BetfairClient:
    def __init__(self, use_dummy: bool = False):
        self.use_dummy = bool(use_dummy)

        self.app_key = os.getenv("BETFAIR_APP_KEY", "").strip()
        self.username = os.getenv("BETFAIR_USERNAME", "").strip()
        self.password = os.getenv("BETFAIR_PASSWORD", "").strip()

        self.session_token: Optional[str] = None

        # Cache: market_id -> {"name": str, "start": datetime, "start_iso": str}
        self._market_cache: Dict[str, Dict[str, Any]] = {}

        # Cache: market_id -> {selectionId(str): runnerName(str)}
        self._runner_name_cache: Dict[str, Dict[str, str]] = {}

        self._last_catalogue_fetch_ts = 0.0

        print("[BETFAIR] Client version: 2025-12-14-ACCOUNTAPING-FIX")
        print(f"[BETFAIR] Initialising client. use_dummy={self.use_dummy}")
        print(f"[BETFAIR] APP_KEY set: {bool(self.app_key)} | USERNAME set: {bool(self.username)}")

        if not self.use_dummy:
            self._login()

    # -------------------------
    # Login + headers
    # -------------------------

    def _login(self) -> None:
        if not self.app_key or not self.username or not self.password:
            raise RuntimeError("BETFAIR_APP_KEY / BETFAIR_USERNAME / BETFAIR_PASSWORD env vars not set")

        print("[BETFAIR] Logging in via identitysso...")
        headers = {
            "X-Application": self.app_key,
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        }
        data = {"username": self.username, "password": self.password}

        r = requests.post(IDENTITY_LOGIN_URL, headers=headers, data=data, timeout=12)
        print("[BETFAIR] Login HTTP status:", r.status_code)

        try:
            js = r.json()
        except Exception:
            js = {"raw": r.text}

        print("[BETFAIR] Raw JSON login response:", js)

        token = js.get("token")
        status = js.get("status")

        if r.status_code != 200 or status != "SUCCESS" or not token:
            raise RuntimeError(f"Betfair login failed: status={status} response={js}")

        self.session_token = token
        print("[BETFAIR] Logged in, session token acquired.")

    def _headers(self) -> Dict[str, str]:
        if self.use_dummy:
            return {}
        if not self.session_token:
            self._login()
        return {
            "X-Application": self.app_key,
            "X-Authentication": self.session_token or "",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    # -------------------------
    # RPC method name normalisation
    # -------------------------

    def _is_account_method(self, method: str) -> bool:
        if "AccountAPING/" in method:
            return True
        # short names that belong to account API
        return method in {"getAccountFunds", "getAccountDetails", "getAccountStatement"}

    def _normalise_method(self, method: str) -> str:
        """
        Betfair JSON-RPC generally wants fully-qualified method names.
        This makes your app resilient if the rest of your code uses short names.
        """
        if "APING/" in method:
            return method

        # Account methods
        if self._is_account_method(method):
            return f"AccountAPING/v1.0/{method}"

        # Betting methods (we use these in this project)
        betting = {
            "listMarketCatalogue",
            "listMarketBook",
            "listEventTypes",
            "listEvents",
            "listMarketTypes",
            "listCompetitions",
        }
        if method in betting:
            return f"SportsAPING/v1.0/{method}"

        # fallback: leave as-is
        return method

    # -------------------------
    # JSON-RPC (Betting + Account)
    # -------------------------

    def _rpc(self, method: str, params: dict) -> Any:
        if self.use_dummy:
            return self._dummy_rpc(method, params)

        m = self._normalise_method(method)
        url = ACCOUNT_RPC_URL if self._is_account_method(m) else BETTING_RPC_URL

        payload = [{
            "jsonrpc": "2.0",
            "method": m,
            "params": params,
            "id": 1,
        }]

        r = requests.post(url, headers=self._headers(), data=json.dumps(payload), timeout=12)
        print(f"[BETFAIR] RPC {m} HTTP status: {r.status_code}")
        r.raise_for_status()

        data = r.json()
        if isinstance(data, list) and data and "error" in data[0]:
            raise RuntimeError(f"Betfair RPC error: {data[0]['error']}")

        if isinstance(data, list) and data:
            return data[0].get("result")
        return data

    # -------------------------
    # DUMMY responses
    # -------------------------

    def _dummy_rpc(self, method: str, params: dict) -> Any:
        m = self._normalise_method(method)

        if m.endswith("getAccountFunds"):
            print("[BETFAIR] Returning DUMMY account funds.")
            return {"availableToBetBalance": 500.0, "exposure": 0.0}

        if m.endswith("listMarketCatalogue"):
            print("[BETFAIR] Returning DUMMY novice hurdle markets.")
            now = _utcnow()
            m1 = {
                "marketId": "1.DUMMY001",
                "marketName": "2m Nov Hrd",
                "marketStartTime": _iso_z(now + dt.timedelta(minutes=45)),
                "event": {"name": "Cheltenham 14th Dec"},
                "runners": [{"selectionId": 101, "runnerName": "Dummy Fav A"},
                            {"selectionId": 102, "runnerName": "Dummy Fav B"},
                            {"selectionId": 103, "runnerName": "Dummy Other"}],
            }
            m2 = {
                "marketId": "1.DUMMY002",
                "marketName": "2m3f Nov Hrd",
                "marketStartTime": _iso_z(now + dt.timedelta(hours=2)),
                "event": {"name": "Fairyhouse 14th Dec"},
                "runners": [{"selectionId": 201, "runnerName": "Dummy Fav C"},
                            {"selectionId": 202, "runnerName": "Dummy Fav D"}],
            }
            return [m1, m2]

        if m.endswith("listMarketBook"):
            market_ids = params.get("marketIds") or []
            out = []
            for mid in market_ids:
                out.append({
                    "marketId": mid,
                    "runners": [
                        {"selectionId": 101, "ex": {"availableToBack": [{"price": 2.5, "size": 100.0}]}},
                        {"selectionId": 102, "ex": {"availableToBack": [{"price": 3.2, "size": 100.0}]}},
                        {"selectionId": 103, "ex": {"availableToBack": [{"price": 6.0, "size": 100.0}]}},
                    ]
                })
            return out

        return {}

    # -------------------------
    # Public API used by webapp/strategy
    # -------------------------

    def get_account_funds(self) -> Dict[str, Any]:
        """
        LIVE: calls AccountAPING getAccountFunds at the ACCOUNT endpoint.
        DUMMY: returns a fixed balance.
        """
        if self.use_dummy:
            res = self._rpc("getAccountFunds", {})
            return {"available_to_bet": float(res.get("availableToBetBalance", 0.0)), **res}

        print("[BETFAIR] Fetching REAL account funds.")
        res = self._rpc("getAccountFunds", {})  # method will normalise to AccountAPING/v1.0/getAccountFunds

        avail = res.get("availableToBetBalance")
        if avail is None:
            # some responses differ; keep compatibility
            avail = res.get("available_to_bet")

        return {"available_to_bet": float(avail) if avail is not None else None, **res}

    def get_todays_novice_hurdle_markets(self) -> List[Dict[str, Any]]:
        """
        UK & Ireland novice hurdle-ish WIN markets (+36h).
        Returns list: [{"market_id": "...", "name": "...", "start_time": "ISOZ"}]
        """
        if self.use_dummy:
            cats = self._rpc("listMarketCatalogue", {"filter": {}})
            out = []
            for m in cats:
                self._prime_market_cache_from_catalogue(m)
                mid = m.get("marketId")
                name = f"{(m.get('event') or {}).get('name','?').split()[0]} | {m.get('marketName','WIN')} | {m.get('marketStartTime','')}"
                out.append({"market_id": mid, "name": name, "start_time": m.get("marketStartTime", "")})
            return out

        now = _utcnow()
        to = now + dt.timedelta(hours=36)

        # light throttle
        self._last_catalogue_fetch_ts = time.time()

        print("[BETFAIR] Fetching REAL UK/IE WIN markets (+36h) and filtering novice hurdles...")

        res = self._rpc(
            "listMarketCatalogue",
            {
                "filter": {
                    "eventTypeIds": [HORSE_RACING_EVENT_TYPE_ID],
                    "marketTypeCodes": ["WIN"],
                    "marketCountries": ["GB", "IE"],
                    "marketStartTime": {"from": _iso_z(now), "to": _iso_z(to)},
                },
                "maxResults": 200,
                "marketProjection": ["EVENT", "MARKET_START_TIME", "RUNNER_DESCRIPTION"],
                "sort": "FIRST_TO_START",
            },
        ) or []

        out: List[Dict[str, Any]] = []
        for m in res:
            self._prime_market_cache_from_catalogue(m)

            market_id = m.get("marketId")
            market_name = m.get("marketName", "")
            event_name = (m.get("event") or {}).get("name", "")
            start_time = m.get("marketStartTime", "")

            if not market_id:
                continue
            if not _looks_like_novice_hurdle(market_name):
                continue

            venue = event_name.split()[0] if event_name else "Unknown"
            pretty = f"{venue} | {market_name} | {start_time} ({market_id})"

            out.append({"market_id": market_id, "name": pretty, "start_time": start_time})

        print(f"[BETFAIR] UK/IE novice hurdle-ish WIN markets found: {len(out)}")
        return out

    def _prime_market_cache_from_catalogue(self, m: Dict[str, Any]) -> None:
        try:
            mid = m.get("marketId")
            if not mid:
                return

            event_name = (m.get("event") or {}).get("name", "")
            market_name = m.get("marketName", "") or ""
            start_iso = m.get("marketStartTime", "") or ""

            venue = event_name.split()[0] if event_name else "Unknown"
            pretty_name = f"{venue} | {market_name}"

            start_dt = _parse_iso_utc(start_iso) if start_iso else None

            self._market_cache[mid] = {"name": pretty_name, "start": start_dt, "start_iso": start_iso}

            runners = m.get("runners") or []
            if runners:
                mp = self._runner_name_cache.get(mid) or {}
                for r in runners:
                    sid = r.get("selectionId")
                    rn = r.get("runnerName")
                    if sid is not None and rn:
                        mp[str(sid)] = rn
                self._runner_name_cache[mid] = mp
        except Exception:
            return

    def get_market_name(self, market_id: str) -> str:
        if market_id in self._market_cache and self._market_cache[market_id].get("name"):
            return str(self._market_cache[market_id]["name"])

        res = self._rpc(
            "listMarketCatalogue",
            {"filter": {"marketIds": [market_id]}, "maxResults": 1, "marketProjection": ["EVENT", "MARKET_START_TIME"]},
        ) or []

        if res:
            self._prime_market_cache_from_catalogue(res[0])
            return str(self._market_cache.get(market_id, {}).get("name", market_id))
        return market_id

    def get_market_start_time(self, market_id: str) -> Optional[dt.datetime]:
        if market_id in self._market_cache and self._market_cache[market_id].get("start"):
            return self._market_cache[market_id]["start"]

        res = self._rpc(
            "listMarketCatalogue",
            {"filter": {"marketIds": [market_id]}, "maxResults": 1, "marketProjection": ["MARKET_START_TIME", "EVENT"]},
        ) or []

        if res:
            self._prime_market_cache_from_catalogue(res[0])
            return self._market_cache.get(market_id, {}).get("start")
        return None

    def _ensure_runner_names(self, market_id: str) -> None:
        if market_id in self._runner_name_cache and self._runner_name_cache[market_id]:
            return
        res = self._rpc(
            "listMarketCatalogue",
            {
                "filter": {"marketIds": [market_id]},
                "maxResults": 1,
                "marketProjection": ["RUNNER_DESCRIPTION", "EVENT", "MARKET_START_TIME"],
            },
        ) or []
        if res:
            self._prime_market_cache_from_catalogue(res[0])

    def get_top_two_favourites(self, market_id: str) -> List[Dict[str, Any]]:
        """
        Returns top 2 favourites by lowest best available back price.
        """
        self._ensure_runner_names(market_id)
        name_map = self._runner_name_cache.get(market_id, {})

        books = self._rpc(
            "listMarketBook",
            {"marketIds": [market_id], "priceProjection": {"priceData": ["EX_BEST_OFFERS"]}},
        ) or []

        if not books:
            return []

        runners = (books[0] or {}).get("runners") or []
        priced: List[Tuple[float, int]] = []

        for r in runners:
            sid = r.get("selectionId")
            ex = r.get("ex") or {}
            atb = ex.get("availableToBack") or []
            if sid is None or not atb:
                continue
            p = atb[0].get("price")
            if p is None:
                continue
            try:
                priced.append((float(p), int(sid)))
            except Exception:
                continue

        priced.sort(key=lambda x: x[0])
        top = priced[:2]

        out: List[Dict[str, Any]] = []
        for p, sid in top:
            rn = name_map.get(str(sid)) or f"Runner {sid}"
            out.append({"name": rn, "selection_id": sid, "back": float(p)})

        return out
