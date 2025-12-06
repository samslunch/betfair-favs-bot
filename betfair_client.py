# betfair_client.py
#
# Clean full version for Adam’s Betfair bot.
# Supports:
#   - Login via identitysso
#   - listMarketCatalogue
#   - getAccountFunds
#   - novice hurdle market search with fallback
#   - safe dummy mode for testing
#
# Requires env variables:
#   BETFAIR_APP_KEY
#   BETFAIR_USERNAME
#   BETFAIR_PASSWORD

import os
import json
import requests
import datetime as dt
from typing import List, Dict, Any, Optional


class BetfairClient:
    """
    Lightweight Betfair API client (non-streaming).
    Uses JSON-RPC for standard endpoints.
    """

    API_ENDPOINT = "https://api.betfair.com/exchange/betting/json-rpc/v1"
    LOGIN_ENDPOINT = "https://identitysso.betfair.com/api/login"
    ACCOUNT_ENDPOINT = "https://api.betfair.com/exchange/account/json-rpc/v1"

    def __init__(self, use_dummy: bool = False):
        self.use_dummy = use_dummy
        self.app_key = os.getenv("BETFAIR_APP_KEY")
        self.username = os.getenv("BETFAIR_USERNAME")
        self.password = os.getenv("BETFAIR_PASSWORD")
        self.session_token: Optional[str] = None

        print(f"[BETFAIR] Initialising client. use_dummy={self.use_dummy}")
        print(f"[BETFAIR] APP_KEY set: {bool(self.app_key)} | USERNAME set: {bool(self.username)}")

        if not self.use_dummy:
            if not self.app_key or not self.username or not self.password:
                raise RuntimeError(
                    "BETFAIR_APP_KEY / BETFAIR_USERNAME / BETFAIR_PASSWORD env vars not set"
                )
            self._login()

    # ---------------------------------------------------
    # LOGIN
    # ---------------------------------------------------
    def _login(self):
        """Logs in and retrieves SSO session token."""
        print("[BETFAIR] Logging in via identitysso...")

        headers = {
            "X-Application": self.app_key,
            "Content-Type": "application/x-www-form-urlencoded",
        }

        data = f"username={self.username}&password={self.password}"

        resp = requests.post(self.LOGIN_ENDPOINT, headers=headers, data=data)
        try:
            js = resp.json()
        except Exception:
            print("[BETFAIR] Failed to parse login response:", resp.text)
            raise

        if js.get("status") != "SUCCESS":
            raise RuntimeError(f"Betfair login failed: {js}")

        self.session_token = js.get("token")
        print("[BETFAIR] Login successful.")

    # ---------------------------------------------------
    # JSON-RPC helper
    # ---------------------------------------------------
    def _rpc(self, method: str, params: dict, account: bool = False):
        """Make a JSON-RPC call to betting or account API."""

        endpoint = self.ACCOUNT_ENDPOINT if account else self.API_ENDPOINT

        headers = {
            "X-Application": self.app_key,
            "X-Authentication": self.session_token,
            "Content-Type": "application/json",
        }

        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": f"SportsAPING/v1.0/{method}",
            "params": params,
        }

        resp = requests.post(endpoint, headers=headers, data=json.dumps(payload))

        if resp.status_code != 200:
            raise RuntimeError(f"Betfair HTTP {resp.status_code}: {resp.text}")

        js = resp.json()

        if "error" in js:
            raise RuntimeError(f"Betfair API error: {js['error']}")

        return js.get("result")

    # ---------------------------------------------------
    # ACCOUNT FUNDS
    # ---------------------------------------------------
    def get_account_funds(self) -> float:
        """Returns available wallet balance."""
        if self.use_dummy:
            return 999.99

        params = {}
        result = self._rpc("getAccountFunds", params, account=True)
        return result.get("availableToBetBalance", 0.0)

    # ---------------------------------------------------
    # MARKET SEARCH (NOVICE HURDLE + FALLBACK)
    # ---------------------------------------------------
    def get_todays_novice_hurdle_markets(self) -> List[Dict[str, Any]]:
        """
        Returns list of { market_id, name }.
        Prefer novice hurdles; if none exist, return ALL UK/IRE WIN races today.
        """

        if self.use_dummy:
            print("[BETFAIR] Returning DUMMY novice hurdle markets.")
            return [
                {"market_id": "1.111111111", "name": "Dummy Novice Hurdle 13:30"},
                {"market_id": "1.222222222", "name": "Dummy Novice Hurdle 14:05"},
                {"market_id": "1.333333333", "name": "Dummy Novice Hurdle 15:15"},
            ]

        print("[BETFAIR] Fetching REAL novice hurdle markets for today...")

        now_utc = dt.datetime.utcnow()
        end_of_day = now_utc.replace(hour=23, minute=59, second=59, microsecond=0)

        base_filter = {
            "eventTypeIds": ["7"],  # Horse Racing
            "marketCountries": ["GB", "IE"],
            "marketTypeCodes": ["WIN"],
            "marketStartTime": {
                "from": now_utc.isoformat() + "Z",
                "to": end_of_day.isoformat() + "Z",
            },
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

        all_today = []
        novice_only = []

        for m in result:
            name = m.get("marketName", "")
            event = m.get("event", {})
            venue = event.get("venue", "")
            open_date = event.get("openDate", "")

            nice_name = f"{venue} {name} ({open_date})".strip()

            entry = {
                "market_id": m["marketId"],
                "name": nice_name,
            }

            all_today.append(entry)

            # Novice Hurdles
            if "Novice" in name and ("Hurdle" in name or "Hrd" in name):
                novice_only.append(entry)

        print(
            f"[BETFAIR] Found {len(novice_only)} novice hurdles; "
            f"{len(all_today)} total WIN markets today."
        )

        if novice_only:
            return novice_only

        print("[BETFAIR] No novice hurdles — returning ALL WIN races.")
        return all_today

    # ---------------------------------------------------
    # GET RUNNER ODDS FOR MARKET
    # ---------------------------------------------------
    def get_runner_book(self, market_id: str) -> List[Dict[str, Any]]:
        """
        Returns simplified runner list:
            [{ 'selectionId': int, 'price': float, 'name': str }, ...]
        Sorted by price ascending (favourites first).
        """

        if self.use_dummy:
            print("[BETFAIR] Dummy odds used.")
            return [
                {"selectionId": 101, "name": "Dummy Fav 1", "price": 2.0},
                {"selectionId": 102, "name": "Dummy Fav 2", "price": 3.0},
            ]

        params = {
            "marketIds": [market_id],
            "priceProjection": {
                "priceData": ["EX_BEST_OFFERS"],
                "virtualise": True,
            }
        }

        try:
            result = self._rpc("listRunnerBook", params)
        except Exception as e:
            print("[BETFAIR] Error fetching runnerBook:", e)
            return []

        if not result:
            return []

        runners_out = []
        for r in result[0].get("runners", []):
            selection_id = r.get("selectionId")
            name = r.get("runnerName", f"Runner {selection_id}")
            prices = r.get("ex", {}).get("availableToBack", [])
            price = prices[0]["price"] if prices else None

            if price:
                runners_out.append(
                    {"selectionId": selection_id, "name": name, "price": price}
                )

        runners_out.sort(key=lambda x: x["price"])
        return runners_out
