# betfair_client.py
#
# BetfairClient with dummy mode + real API-NG integration for:
# - get_todays_novice_hurdle_markets()
# - get_market_name()
# - get_top_two_favourites()
# - get_account_funds()

import os
import datetime as dt
from typing import List, Dict, Any, Optional

import requests


BETTING_ENDPOINT = "https://api.betfair.com/exchange/betting/json-rpc/v1"
ACCOUNT_ENDPOINT = "https://api.betfair.com/exchange/account/json-rpc/v1"
IDENTITY_ENDPOINT = "https://identitysso.betfair.com/api/login"


class BetfairClient:
    def __init__(self, use_dummy: bool = True):
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
            "Accept": "application/json",  # ask explicitly for JSON
        }
        data = {
            "username": self.username,
            "password": self.password,
        }

        print("[BETFAIR] Logging in via identitysso...")
        resp = requests.post(IDENTITY_ENDPOINT, headers=headers, data=data, timeout=10)
        print(f"[BETFAIR] Login HTTP status: {resp.status_code}")

        # Try JSON first, but fall back to raw text so we can see errors
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
    # Public interface used by webapp
    # -------------------------

    def get_todays_novice_hurdle_markets(self) -> List[Dict[str, Any]]:
        """
        Returns a list of dicts: { 'market_id': str, 'name': str }

        Looser matching:
        - Horse Racing (eventType 7)
        - GB / IE
        - WIN markets
        - marketName includes something hurdle-ish (hurdle / hurd / hdle)
        - and something novice-ish (nov / novice)
        """
        if self.use_dummy:
            print("[BETFAIR] Returning DUMMY novice hurdle markets.")
            return [
                {"market_id": "1.234567891", "name": "Dummy Novice Hurdle 13:30"},
                {"market_id": "1.234567892", "name": "Dummy Novice Hurdle 14:05"},
                {"market_id": "1.234567893", "name": "Dummy Novice Hurdle 15:15"},
            ]

        print("[BETFAIR] Fetching REAL 'novice-style' hurdle WIN markets for today from API.")

        # Build a "today" time range in UTC
        now_utc = dt.datetime.utcnow()
        start = now_utc.replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + dt.timedelta(days=1)

        params = {
            "filter": {
                "eventTypeIds": ["7"],  # Horse Racing
                "marketCountries": ["GB", "IE"],
                "marketTypeCodes": ["WIN"],
                "marketStartTime": {
                    "from": start.isoformat() + "Z",
                    "to": end.isoformat() + "Z",
                },
            },
            "maxResults": 200,
            "marketProjection": ["MARKET_START_TIME", "EVENT"],
        }

        result = self._rpc("listMarketCatalogue", params)
        markets: List[Dict[str, Any]] = []

        for m in result:
            raw_name = m.get("marketName", "") or ""
            name = raw_name.strip()
            ln = name.lower()

            is_hurdle = any(x in ln for x in ["hurdle", "hurd", "hdle"])
            is_noviceish = any(x in ln for x in ["nov", "novice"])

            # Debug logs to see borderline names
            if is_hurdle and not is_noviceish:
                print(f"[BETFAIR][DEBUG] Hurdle but not novice-ish: {name}")
            if is_noviceish and not is_hurdle:
                print(f"[BETFAIR][DEBUG] Novice-ish but not hurdle: {name}")

            if is_hurdle and is_noviceish:
                venue = (m.get("event") or {}).get("venue", "").strip()
                open_date = (m.get("event") or {}).get("openDate", "")
                nice_name = f"{venue} {name} ({open_date})".strip()
                markets.append(
                    {
                        "market_id": m["marketId"],
                        "name": nice_name,
                    }
                )

        print(f"[BETFAIR] Found {len(markets)} novice-style hurdle WIN markets today.")
        return markets

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
        event = m.get("event") or {}
        venue = event.get("venue", "").strip()
        market_name = m.get("marketName", "").strip()
        if venue:
            return f"{venue} {market_name}"
        return market_name or market_id

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
                runner_name_map[r["selectionId"]] = r.get("runnerName", str(r["selectionId"]))

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





