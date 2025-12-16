# betfair_client.py
#
# Betfair read-only client + SAFE "simulation" guardrails.
#
# Modes:
#   BOT_MODE=dummy        -> built-in dummy markets + dummy odds + dummy results
#   BOT_MODE=simulation   -> REAL markets/odds/results, PAPER bank (NO bets placed)
#   BOT_MODE=live         -> real betting only if ALSO ALLOW_LIVE_BETS=true
#
# Env:
#   BETFAIR_APP_KEY
#   BETFAIR_USERNAME
#   BETFAIR_PASSWORD
#   BOT_MODE = dummy|simulation|live
#   ALLOW_LIVE_BETS = true|false   (required for real bet placement)
#
# Notes:
# - getAccountFunds must be called on the ACCOUNT endpoint, not betting.
# - "Novice hurdle-ish" filter: novice/nov + hurdle/hrd/hdl.
# - UK/IE only, WIN only, +36 hours.
#
import os
import json
import datetime as dt
from typing import Any, Dict, List, Optional, Tuple

import requests


class BetfairClient:
    VERSION = "2025-12-16-SIM-SAFE-ACCOUNTFIX"

    BETTING_RPC_URL = "https://api.betfair.com/exchange/betting/json-rpc/v1"
    ACCOUNT_RPC_URL = "https://api.betfair.com/exchange/account/json-rpc/v1"

    def __init__(self, mode: Optional[str] = None):
        self.mode = (mode or os.getenv("BOT_MODE", "dummy")).strip().lower()
        if self.mode not in ("dummy", "simulation", "live"):
            self.mode = "dummy"

        self.allow_live_bets = os.getenv("ALLOW_LIVE_BETS", "false").strip().lower() == "true"

        self.app_key = os.getenv("BETFAIR_APP_KEY", "")
        self.username = os.getenv("BETFAIR_USERNAME", "")
        self.password = os.getenv("BETFAIR_PASSWORD", "")

        self.session_token: Optional[str] = None

        # caches
        self._market_catalogue_cache: Dict[str, Dict[str, Any]] = {}  # marketId -> catalogue item
        self._runner_name_cache: Dict[str, Dict[int, str]] = {}       # marketId -> {selectionId: name}

        print(f"[BETFAIR] Client version: {self.VERSION}")
        print(f"[BETFAIR] Initialising client. mode={self.mode}")
        print(f"[BETFAIR] APP_KEY set: {bool(self.app_key)} | USERNAME set: {bool(self.username)}")

        if self.mode != "dummy":
            self._login()

    # -------------------------
    # Auth / RPC helpers
    # -------------------------

    def _login(self) -> None:
        if not (self.app_key and self.username and self.password):
            raise RuntimeError("BETFAIR_APP_KEY / BETFAIR_USERNAME / BETFAIR_PASSWORD env vars not set")

        url = "https://identitysso.betfair.com/api/login"
        headers = {
            "X-Application": self.app_key,
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        }
        data = {"username": self.username, "password": self.password}

        print("[BETFAIR] Logging in via identitysso...")
        r = requests.post(url, headers=headers, data=data, timeout=20)
        print("[BETFAIR] Login HTTP status:", r.status_code)

        try:
            js = r.json()
        except Exception:
            raise RuntimeError(f"Login failed (non-JSON): {r.text[:300]}")

        print("[BETFAIR] Raw JSON login response:", js)
        if js.get("status") != "SUCCESS":
            raise RuntimeError(f"Login failed: {js}")

        self.session_token = js.get("token")
        if not self.session_token:
            raise RuntimeError("Login succeeded but no session token returned")

        print("[BETFAIR] Logged in, session token acquired.")

    def _rpc_common(self, url: str, api_prefix: str, method: str, params: Dict[str, Any]) -> Any:
        """
        Generic JSON-RPC caller. api_prefix is:
          - "SportsAPING" for betting endpoints
          - "AccountAPING" for account endpoints
        """
        if self.mode == "dummy":
            raise RuntimeError("RPC not available in dummy mode")

        headers = {
            "X-Application": self.app_key,
            "X-Authentication": self.session_token or "",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        payload = [{
            "jsonrpc": "2.0",
            "method": f"{api_prefix}/v1.0/{method}",
            "params": params,
            "id": 1,
        }]

        r = requests.post(url, headers=headers, data=json.dumps(payload), timeout=25)
        print(f"[BETFAIR] RPC {method} HTTP status: {r.status_code}")

        try:
            data = r.json()
        except Exception:
            raise RuntimeError(f"Betfair RPC non-JSON response: {r.text[:500]}")

        if not isinstance(data, list) or not data:
            raise RuntimeError(f"Betfair RPC invalid response: {data}")

        if "error" in data[0] and data[0]["error"]:
            raise RuntimeError(f"Betfair RPC error: {data[0]['error']}")

        return data[0].get("result")

    def _rpc(self, method: str, params: Dict[str, Any]) -> Any:
        """Betting API (SportsAPING) calls."""
        return self._rpc_common(self.BETTING_RPC_URL, "SportsAPING", method, params)

    def _rpc_account(self, method: str, params: Dict[str, Any]) -> Any:
        """Account API (AccountAPING) calls."""
        return self._rpc_common(self.ACCOUNT_RPC_URL, "AccountAPING", method, params)

    # -------------------------
    # Public: account / markets
    # -------------------------

    def get_account_funds(self) -> Dict[str, Any]:
        if self.mode == "dummy":
            print("[BETFAIR] Returning DUMMY account funds.")
            return {"available_to_bet": 1000.0, "exposure": 0.0}

        print("[BETFAIR] Fetching REAL account funds.")
        # Safest across accounts: call without wallet.
        # If you ever need it: {"wallet":"UK"} or {"wallet":"AU"} etc.
        return self._rpc_account("getAccountFunds", {})

    def get_todays_novice_hurdle_markets(self) -> List[Dict[str, Any]]:
        """
        Returns UK & Ireland novice hurdle-ish WIN markets for the next ~36 hours.
        No fallback: can return empty.
        """
        if self.mode == "dummy":
            print("[BETFAIR] Returning DUMMY novice hurdle markets.")
            now = dt.datetime.now(dt.timezone.utc)
            dummy = []
            for i in range(6):
                st = now + dt.timedelta(minutes=30 + i * 40)
                dummy.append({
                    "market_id": f"DUMMY-{i+1}",
                    "name": f"Dummy Track | 2m Nov Hrd | R{i+1}",
                    "start_time": st.isoformat().replace("+00:00", "Z"),
                })
            return dummy

        print("[BETFAIR] Fetching REAL UK/IE WIN markets (+36h) and filtering novice hurdles...")
        now = dt.datetime.now(dt.timezone.utc)
        to = now + dt.timedelta(hours=36)

        params = {
            "filter": {
                "eventTypeIds": ["7"],            # Horse Racing
                "marketTypeCodes": ["WIN"],       # WIN markets
                "marketCountries": ["GB", "IE"],  # UK/IE only
                "marketStartTime": {
                    "from": now.isoformat().replace("+00:00", "Z"),
                    "to": to.isoformat().replace("+00:00", "Z"),
                },
            },
            "maxResults": 200,
            "marketProjection": ["EVENT", "MARKET_START_TIME"],
            "sort": "FIRST_TO_START",
        }

        res = self._rpc("listMarketCatalogue", params) or []
        out: List[Dict[str, Any]] = []

        for m in res:
            market_id = m.get("marketId")
            start_time = m.get("marketStartTime")  # ISO string
            event = m.get("event") or {}
            event_name = event.get("name", "")
            market_name = m.get("marketName", "")

            combined = f"{event_name} | {market_name}".lower()

            has_nov = ("novice" in combined) or (" nov " in f" {combined} ") or ("nov" in combined)
            has_hrd = ("hurdle" in combined) or (" hrd" in combined) or (" hurd" in combined) or ("hdl" in combined)

            if not (has_nov and has_hrd):
                continue

            out.append({
                "market_id": market_id,
                "name": f"{event_name} | {market_name}".strip(" |"),
                "start_time": start_time or "",
            })

            if market_id:
                self._market_catalogue_cache[market_id] = {
                    "marketId": market_id,
                    "event": event,
                    "marketName": market_name,
                    "marketStartTime": start_time,
                }

        print(f"[BETFAIR] UK/IE novice hurdle-ish WIN markets found: {len(out)}")
        return out

    # -------------------------
    # Market helpers: name/start time/runners
    # -------------------------

    def get_market_start_time(self, market_id: str) -> Optional[dt.datetime]:
        if self.mode == "dummy":
            return dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=45)

        cat = self._market_catalogue_cache.get(market_id)
        if not cat:
            res = self._rpc("listMarketCatalogue", {
                "filter": {"marketIds": [market_id]},
                "maxResults": 1,
                "marketProjection": ["EVENT", "MARKET_START_TIME"],
            }) or []
            if res:
                cat = res[0]
                self._market_catalogue_cache[market_id] = cat

        if not cat:
            return None

        s = cat.get("marketStartTime")
        if not s:
            return None

        try:
            if s.endswith("Z"):
                s = s.replace("Z", "+00:00")
            return dt.datetime.fromisoformat(s).astimezone(dt.timezone.utc)
        except Exception:
            return None

    def get_market_name(self, market_id: str) -> str:
        if self.mode == "dummy":
            return market_id

        cat = self._market_catalogue_cache.get(market_id)
        if cat:
            ev = cat.get("event") or {}
            return f"{ev.get('name','')} | {cat.get('marketName','')}".strip(" |")

        res = self._rpc("listMarketCatalogue", {
            "filter": {"marketIds": [market_id]},
            "maxResults": 1,
            "marketProjection": ["EVENT"],
        }) or []
        if not res:
            return market_id
        cat = res[0]
        self._market_catalogue_cache[market_id] = cat
        ev = cat.get("event") or {}
        return f"{ev.get('name','')} | {cat.get('marketName','')}".strip(" |")

    def _ensure_runner_names(self, market_id: str) -> None:
        if market_id in self._runner_name_cache:
            return
        if self.mode == "dummy":
            self._runner_name_cache[market_id] = {1: "Dummy Fav 1", 2: "Dummy Fav 2"}
            return

        res = self._rpc("listMarketCatalogue", {
            "filter": {"marketIds": [market_id]},
            "maxResults": 1,
            "marketProjection": ["RUNNER_DESCRIPTION"],
        }) or []
        mapping: Dict[int, str] = {}
        if res:
            runners = res[0].get("runners") or []
            for r in runners:
                sid = r.get("selectionId")
                nm = r.get("runnerName")
                if isinstance(sid, int) and nm:
                    mapping[sid] = nm
        self._runner_name_cache[market_id] = mapping

    def get_top_two_favourites(self, market_id: str) -> List[Dict[str, Any]]:
        """
        Returns list of 2 dicts: {selection_id, name, back}
        Sorted by lowest back price (favourite first).
        """
        if self.mode == "dummy":
            return [{"selection_id": 1, "name": "Dummy Fav 1", "back": 2.8},
                    {"selection_id": 2, "name": "Dummy Fav 2", "back": 3.2}]

        self._ensure_runner_names(market_id)

        books = self._rpc("listMarketBook", {
            "marketIds": [market_id],
            "priceProjection": {"priceData": ["EX_BEST_OFFERS"]},
        }) or []

        if not books:
            return []

        runners = (books[0].get("runners") or [])
        rows: List[Tuple[float, int]] = []

        for r in runners:
            sid = r.get("selectionId")
            ex = r.get("ex") or {}
            atb = ex.get("availableToBack") or []
            if not atb:
                continue
            price = atb[0].get("price")
            if not isinstance(price, (int, float)):
                continue
            if isinstance(sid, int):
                rows.append((float(price), sid))

        rows.sort(key=lambda x: x[0])
        top = rows[:2]
        out: List[Dict[str, Any]] = []
        name_map = self._runner_name_cache.get(market_id, {})

        for price, sid in top:
            out.append({
                "selection_id": sid,
                "name": name_map.get(sid, str(sid)),
                "back": float(price),
            })

        return out

    def get_market_result(self, market_id: str) -> Dict[str, Any]:
        """
        Returns:
          {
            "status": "OPEN"|"SUSPENDED"|"CLOSED"|...,
            "is_closed": bool,
            "winner_selection_id": Optional[int]
          }
        """
        if self.mode == "dummy":
            return {"status": "CLOSED", "is_closed": True, "winner_selection_id": 1}

        books = self._rpc("listMarketBook", {
            "marketIds": [market_id],
            "priceProjection": {"priceData": []},
        }) or []
        if not books:
            return {"status": "UNKNOWN", "is_closed": False, "winner_selection_id": None}

        b = books[0]
        status = b.get("status", "UNKNOWN")
        is_closed = status == "CLOSED"

        winner: Optional[int] = None
        for r in (b.get("runners") or []):
            if r.get("status") == "WINNER":
                sid = r.get("selectionId")
                if isinstance(sid, int):
                    winner = sid
                    break

        return {"status": status, "is_closed": is_closed, "winner_selection_id": winner}

    # -------------------------
    # Betting (guarded)
    # -------------------------

    def place_dutch_bets(self, market_id: str, bets: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        bets: [{selectionId:int, side:"BACK", size:float, price:float}, ...]
        This is SAFE-GUARDED:
          - dummy/simulation -> NEVER places
          - live -> only if ALLOW_LIVE_BETS=true
        """
        if self.mode in ("dummy", "simulation"):
            print(f"[SIM] Would place bets on {market_id}: {bets}")
            return {"placed": False, "mode": self.mode, "bets": bets}

        if self.mode == "live" and not self.allow_live_bets:
            print("[SAFE] BOT_MODE=live but ALLOW_LIVE_BETS!=true, blocking placeOrders.")
            return {"placed": False, "blocked": True, "reason": "ALLOW_LIVE_BETS not enabled"}

        # Real placeOrders (only when explicitly allowed)
        res = self._rpc("placeOrders", {
            "marketId": market_id,
            "instructions": [
                {
                    "selectionId": b["selectionId"],
                    "side": b.get("side", "BACK"),
                    "orderType": "LIMIT",
                    "limitOrder": {
                        "size": round(float(b["size"]), 2),
                        "price": float(b["price"]),
                        "persistenceType": "LAPSE",
                    },
                } for b in bets
            ],
        })
        return {"placed": True, "result": res}
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
