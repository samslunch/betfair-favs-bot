# betfair_client.py
#
# BetfairClient with:
#   - login via identitysso
#   - listMarketCatalogue (for markets, names, start times)
#   - listMarketBook (for top two favourites)
#   - getAccountFunds (Betfair balance)
#   - get_todays_novice_hurdle_markets() with relaxed filter & fallback
#
# Environment variables required (for live mode):
#   BETFAIR_APP_KEY
#   BETFAIR_USERNAME
#   BETFAIR_PASSWORD

import os
import datetime as dt
from typing import List, Dict, Any, Optional

import requests


BETTING_ENDPOINT = "https://api.betfair.com/exchange/betting/json-rpc/v1"
ACCOUNT_ENDPOINT = "https://api.betfair.com/exchange/account/json-rpc/v1"
IDENTITY_ENDPOINT = "https://identitysso.betfair.com/api/login"


class BetfairClient:
    def __init__(self, use_dummy: bool = True):
        """
        use_dummy=True  -> no real API calls, returns fake data
        use_dummy=False -> real Betfair API-NG (needs env vars)
        """
        print("[BETFAIR] Client version: 2025-12-06-FALLBACK-RELAXED")
        self.use_dummy = use_dummy
        self.app_key = os.getenv("BETFAIR_APP_KEY", "")
        self.username = os.getenv("BETFAIR_USERNAME", "")
        self.password = os.getenv("BETFAIR_PASSWORD", "")
        self.session_token: Optional[str] = None

        print(f"[BETFAIR] Initialising client. use_dummy={self.use_dummy}")
        if not self.use_dummy:
            print(
                f"[BETFAIR] APP_KEY set: {bool(self.app_key)} | "
                f"USERNAME set: {bool(self.username)}"
            )
            self._login()

    # -------------------------
    # Auth
    # -------------------------

    def _login(self):
        """
        Simple username/password interactive login.
        For production, you should migrate to certificate auth.
        """
        if not (self.app_key and self.username and self.password):
            raise RuntimeError(
                "BETFAIR_APP_KEY / BETFAIR_USERNAME / BETFAIR_PASSWORD env vars not set"
            )

        headers = {
            "X-Application": self.app_key,
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        }
        data = {
            "username": self.username,
            "password": self.password,
        }

        print("[BETFAIR] Logging in via identitysso...")
        resp = requests.post(IDENTITY_ENDPOINT, headers=headers, data=data, timeout=10)
        print(f"[BETFAIR] Login HTTP status: {resp.status_code}")

        try:
            js = resp.json()
            print("[BETFAIR] Raw JSON login response:", js)
        except Exception:
            print("[BETFAIR] Login response was not JSON. Raw body (trimmed):")
            print(resp.text[:500])
            raise RuntimeError(
                "Betfair login did not return JSON. "
                "Check app key / credentials / API access / interactive login."
            )

        if js.get("status") != "SUCCESS":
            raise RuntimeError(f"Betfair login failed: {js}")

        self.session_token = js["token"]
        print("[BETFAIR] Logged in, session token acquired.")

    def _headers(self) -> Dict[str, str]:
        if self.use_dummy:
            return {}
        if not self.session_token:
            self._login()
        return {
            "X-Application": self.app_key,
            "X-Authentication": self.session_token,
            "Content-Type": "application/json",
        }

    def _rpc(self, method: str, params: Dict[str, Any]) -> Any:
        """
        Low-level JSON-RPC helper for betting endpoint.
        """
        payload = {
            "jsonrpc": "2.0",
            "method": f"SportsAPING/v1.0/{method}",
            "params": params,
            "id": 1,
        }
        resp = requests.post(
            BETTING_ENDPOINT,
            headers=self._headers(),
            json=payload,
            timeout=10,
        )
        print(f"[BETFAIR] RPC {method} HTTP status: {resp.status_code}")
        resp.raise_for_status()
        js = resp.json()
        if "error" in js:
            print("[BETFAIR] RPC error response:", js["error"])
            raise RuntimeError(f"Betfair API error: {js['error']}")
        return js["result"]

    def _account_rpc(self, method: str, params: Dict[str, Any]) -> Any:
        """
        JSON-RPC helper for account endpoint (getAccountFunds, etc).
        """
        payload = {
            "jsonrpc": "2.0",
            "method": f"AccountAPING/v1.0/{method}",
            "params": params,
            "id": 1,
        }
        resp = requests.post(
            ACCOUNT_ENDPOINT,
            headers=self._headers(),
            json=payload,
            timeout=10,
        )
        print(f"[BETFAIR] ACCOUNT RPC {method} HTTP status: {resp.status_code}")
        resp.raise_for_status()
        js = resp.json()
        if "error" in js:
            print("[BETFAIR] ACCOUNT RPC error response:", js["error"])
            raise RuntimeError(f"Betfair Account API error: {js['error']}")
        return js["result"]

    # -------------------------
    # Markets
    # -------------------------

    def get_todays_novice_hurdle_markets(self) -> List[Dict[str, Any]]:
        """
        Returns a list of dicts: { 'market_id': str, 'name': str }

        Strategy:
          1) Ask Betfair for up to 200 UK/IRE WIN horse-racing markets (no time filter).
          2) Filter to "today" based on the event's openDate (UTC date).
          3) Inside that, prefer Novice Hurdle/Hrd markets.
          4) If no novice hurdles today, fall back to all today's WIN markets.
          5) If still nothing, fall back to all WIN markets returned.
        """

        if self.use_dummy:
            print("[BETFAIR] Returning DUMMY novice hurdle markets.")
            return [
                {"market_id": "1.234567891", "name": "Dummy Novice Hurdle 13:30"},
                {"market_id": "1.234567892", "name": "Dummy Novice Hurdle 14:05"},
                {"market_id": "1.234567893", "name": "Dummy Novice Hurdle 15:15"},
            ]

        print("[BETFAIR] Fetching REAL novice hurdle markets (relaxed filter).")

        today_utc = dt.datetime.utcnow().date()

        # Simpler filter: no time filter here; we filter by date ourselves.
        base_filter = {
            "eventTypeIds": ["7"],          # Horse Racing
            "marketCountries": ["GB", "IE"],
            "marketTypeCodes": ["WIN"],
        }

        params = {
            "filter": base_filter,
            "maxResults": 200,
            "marketProjection": ["MARKET_START_TIME", "EVENT"],
        }

        try:
            result = self._rpc("listMarketCatalogue", params)
        except Exception as e:
            print("[BETFAIR] Error fetching market catalogue:", e)
            return []

        all_any: List[Dict[str, Any]] = []        # all markets returned
        all_today: List[Dict[str, Any]] = []      # only today's markets
        novice_today: List[Dict[str, Any]] = []   # today's Novice Hurdle markets

        for m in result:
            name = m.get("marketName", "")
            event = m.get("event", {})
            venue = event.get("venue", "")
            open_date_str = event.get("openDate", "")

            nice_name = f"{venue} {name} ({open_date_str})".strip()
            entry = {
                "market_id": m["marketId"],
                "name": nice_name,
            }
            all_any.append(entry)

            # Parse event date (openDate is ISO 8601 string)
            event_date = None
            if open_date_str:
                try:
                    s = open_date_str
                    if s.endswith("Z"):
                        s = s.replace("Z", "+00:00")
                    dt_val = dt.datetime.fromisoformat(s)
                    event_date = dt_val.date()
                except Exception:
                    event_date = None

            # Only keep "today" in all_today / novice_today
            if event_date == today_utc:
                all_today.append(entry)
                if "Novice" in name and ("Hurdle" in name or "Hrd" in name):
                    novice_today.append(entry)

        print(
            f"[BETFAIR] Raw markets: {len(all_any)} total; "
            f"{len(all_today)} for today; {len(novice_today)} novice hurdles today."
        )

        # First choice: Novice hurdles today
        if novice_today:
            return novice_today

        # Second choice: all today's WIN markets
        if all_today:
            print("[BETFAIR] No novice hurdles today – using all WIN markets for today.")
            return all_today

        # Last resort: if somehow nothing matches "today", return everything
        print("[BETFAIR] No markets matched today's date – returning all WIN markets.")
        return all_any

    def get_market_name(self, market_id: str) -> str:
        """
        Look up a human-readable name for a market.
        """
        if self.use_dummy:
            return f"Dummy market {market_id}"

        params = {
            "filter": {"marketIds": [market_id]},
            "maxResults": 1,
            "marketProjection": ["MARKET_START_TIME", "EVENT"],
        }
        result = self._rpc("listMarketCatalogue", params)
        if not result:
            return market_id
        m = result[0]
        return f"{m['event']['venue']} {m['marketName']}"

    def get_market_start_time(self, market_id: str) -> dt.datetime:
        """
        Return the scheduled market start time as a timezone-aware UTC datetime.
        Used for the '1 minute before off' auto-bet timing.
        """
        if self.use_dummy:
            # For dummy mode, pretend the race is 10 minutes from now
            return dt.datetime.utcnow().replace(microsecond=0) + dt.timedelta(minutes=10)

        params = {
            "filter": {"marketIds": [market_id]},
            "maxResults": 1,
            "marketProjection": ["MARKET_START_TIME"],
        }
        result = self._rpc("listMarketCatalogue", params)
        if not result:
            raise RuntimeError(f"No marketStartTime found for market {market_id}")

        raw = result[0].get("marketStartTime")
        if not raw:
            raise RuntimeError(f"Missing marketStartTime in catalogue for {market_id}")

        # Convert ISO8601 string (with 'Z') to aware UTC datetime
        if raw.endswith("Z"):
            raw = raw.replace("Z", "+00:00")
        start = dt.datetime.fromisoformat(raw)
        if start.tzinfo is None:
            start = start.replace(tzinfo=dt.timezone.utc)
        else:
            start = start.astimezone(dt.timezone.utc)

        return start

    # -------------------------
    # Prices / favourites
    # -------------------------

    def get_top_two_favourites(self, market_id: str) -> List[Dict[str, Any]]:
        """
        Returns list of up to 2 dicts:
        { 'selection_id': int, 'name': str, 'back': float, 'lay': float }
        """
        if self.use_dummy:
            print(f"[BETFAIR] Returning DUMMY favourites for market {market_id}.")
            return [
                {"selection_id": 1, "name": "Dummy Fav 1", "back": 2.4, "lay": 2.46},
                {"selection_id": 2, "name": "Dummy Fav 2", "back": 3.1, "lay": 3.2},
            ]

        print(f"[BETFAIR] Fetching REAL favourites for market {market_id}.")

        # 1) Get runner names from MarketCatalogue
        cat_params = {
            "filter": {"marketIds": [market_id]},
            "maxResults": 1,
            "marketProjection": ["RUNNER_DESCRIPTION"],
        }
        cat_res = self._rpc("listMarketCatalogue", cat_params)
        runner_name_map: Dict[int, str] = {}
        if cat_res:
            for r in cat_res[0].get("runners", []):
                runner_name_map[r["selectionId"]] = r["runnerName"]

        # 2) Get prices from MarketBook
        book_params = {
            "marketIds": [market_id],
            "priceProjection": {
                "priceData": ["EX_BEST_OFFERS"],
                "virtualise": True,
            },
        }
        book_res = self._rpc("listMarketBook", book_params)
        if not book_res:
            return []

        runners = book_res[0].get("runners", [])
        priced: List[Dict[str, Any]] = []

        for r in runners:
            sel_id = r["selectionId"]
            ex = r.get("ex", {})
            backs = ex.get("availableToBack", [])
            lays = ex.get("availableToLay", [])
            if not backs or not lays:
                continue
            best_back = backs[0]["price"]
            best_lay = lays[0]["price"]
            name = runner_name_map.get(sel_id, str(sel_id))
            priced.append(
                {
                    "selection_id": sel_id,
                    "name": name,
                    "back": best_back,
                    "lay": best_lay,
                }
            )

        # Sort by back odds ascending (shortest price = favourite)
        priced.sort(key=lambda r: r["back"])
        top_two = priced[:2]
        print(f"[BETFAIR] Top two favourites for {market_id}: {top_two}")
        return top_two

    # -------------------------
    # Account funds
    # -------------------------

    def get_account_funds(self) -> Dict[str, Optional[float]]:
        """
        Fetch account funds from Betfair Account API.

        Returns dict:
        {
            'available_to_bet': float | None,
            'exposure': float | None,
            'retained_commission': float | None,
            'exposure_limit': float | None,
            'discount_rate': float | None,
            'points_balance': float | None,
        }
        """
        if self.use_dummy:
            print("[BETFAIR] Returning DUMMY account funds.")
            return {
                "available_to_bet": 1000.0,
                "exposure": 0.0,
                "retained_commission": 0.0,
                "exposure_limit": None,
                "discount_rate": None,
                "points_balance": None,
            }

        print("[BETFAIR] Fetching REAL account funds.")
        result = self._account_rpc("getAccountFunds", {})

        funds = {
            "available_to_bet": result.get("availableToBetBalance"),
            "exposure": result.get("exposure"),
            "retained_commission": result.get("retainedCommission"),
            "exposure_limit": result.get("exposureLimit"),
            "discount_rate": result.get("discountRate"),
            "points_balance": result.get("pointsBalance"),
        }
        print("[BETFAIR] Account funds:", funds)
        return funds
