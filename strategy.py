# betfair_client.py
#
# BetfairClient with:
#   - login via identitysso
#   - listMarketCatalogue (for market names + start times)
#   - listMarketBook (for favourites)
#   - getAccountFunds (balance)
#   - get_todays_novice_hurdle_markets() with super-flexible detection
#
# Environment variables required:
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
        use_dummy=True  -> bot runs in safe offline simulation mode
        use_dummy=False -> real Betfair API (requires app key + credentials)
        """
        self.use_dummy = use_dummy
        self.app_key = os.getenv("BETFAIR_APP_KEY", "")
        self.username = os.getenv("BETFAIR_USERNAME", "")
        self.password = os.getenv("BETFAIR_PASSWORD", "")
        self.session_token: Optional[str] = None

        print(f"[BETFAIR] Initialising client. use_dummy={self.use_dummy}")
        print(
            f"[BETFAIR] APP_KEY set: {bool(self.app_key)} | "
            f"USERNAME set: {bool(self.username)}"
        )

        if not self.use_dummy:
            self._login()

    # -------------------------------------------------------------------------
    # LOGIN
    # -------------------------------------------------------------------------

    def _login(self):
        """Login using Betfair's identitysso (interactive login)."""
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
        print(f"[BETFAIR] Login status code: {resp.status_code}")

        try:
            js = resp.json()
            print("[BETFAIR] Login JSON response:", js)
        except Exception:
            print("[BETFAIR] Login was NOT JSON. Body:")
            print(resp.text[:500])
            raise RuntimeError("Betfair login failed (non-JSON response).")

        if js.get("status") != "SUCCESS":
            raise RuntimeError(f"Betfair login failure: {js}")

        self.session_token = js["token"]
        print("[BETFAIR] Login OK, session token acquired.")

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
        """Low-level JSON-RPC wrapper for betting API."""
        payload = {
            "jsonrpc": "2.0",
            "method": f"SportsAPING/v1.0/{method}",
            "params": params,
            "id": 1,
        }
        resp = requests.post(
            BETTING_ENDPOINT, headers=self._headers(), json=payload, timeout=10
        )
        print(f"[BETFAIR] RPC {method} → {resp.status_code}")
        js = resp.json()
        if "error" in js:
            raise RuntimeError(f"Betfair API error: {js['error']}")
        return js["result"]

    def _account_rpc(self, method: str, params: Dict[str, Any]) -> Any:
        """Low-level JSON-RPC wrapper for account API."""
        payload = {
            "jsonrpc": "2.0",
            "method": f"AccountAPING/v1.0/{method}",
            "params": params,
            "id": 1,
        }
        resp = requests.post(
            ACCOUNT_ENDPOINT, headers=self._headers(), json=payload, timeout=10
        )
        print(f"[BETFAIR] ACCOUNT {method} → {resp.status_code}")
        js = resp.json()
        if "error" in js:
            raise RuntimeError(f"Betfair Account API error: {js['error']}")
        return js["result"]

    # -------------------------------------------------------------------------
    # MARKET SEARCH (SUPER FLEXIBLE NOVICE HURDLE)
    # -------------------------------------------------------------------------

    def get_todays_novice_hurdle_markets(self) -> List[Dict[str, Any]]:
        """
        SUPER FLEXIBLE NOVICE HURDLE DETECTION
        --------------------------------------
        1) Fetch ALL horse racing markets (no country/type filter).
        2) Filter by event date == today.
        3) Novice hurdle detection uses many patterns:
              novice, nov , nov., nov hrd
              hurdle, hurd, hrd
        4) If any novice hurdles exist → return those.
        5) Otherwise → return all horse races today.
        6) If still empty → return all markets.
        """

        if self.use_dummy:
            print("[BETFAIR] DUMMY novice hurdles (sim mode).")
            return [
                {"market_id": "1.111", "name": "Dummy Novice Hurdle 13:30"},
                {"market_id": "1.112", "name": "Dummy Novice Hurdle 14:05"},
                {"market_id": "1.113", "name": "Dummy Novice Hurdle 15:15"},
            ]

        print("[BETFAIR] Fetching REAL horse markets (relaxed).")

        today_utc = dt.datetime.utcnow().date()

        params = {
            "filter": {"eventTypeIds": ["7"]},  # ALL horse racing
            "maxResults": 200,
            "marketProjection": ["MARKET_START_TIME", "EVENT"],
        }

        try:
            result = self._rpc("listMarketCatalogue", params)
        except Exception as e:
            print("[BETFAIR] Error in listMarketCatalogue:", e)
            return []

        print(f"[BETFAIR] Received {len(result)} markets total.")

        # Log some examples (so we know what Betfair actually names things)
        print("[BETFAIR] Sample market names:")
        for i, m in enumerate(result[:20]):
            print("   ", i + 1, m.get("marketName", ""), "| event:", m.get("event", {}))

        all_any = []
        all_today = []
        novice_today = []

        for m in result:
            name = m.get("marketName", "").lower()
            event = m.get("event", {})
            venue = event.get("venue", "")
            open_date_str = event.get("openDate", "")

            nice = f"{venue} {m.get('marketName','')} ({open_date_str})".strip()
            entry = {
                "market_id": m["marketId"],
                "name": nice,
            }
            all_any.append(entry)

            # Try to parse the event date
            event_date = None
            try:
                s = open_date_str
                if s.endswith("Z"):
                    s = s.replace("Z", "+00:00")
                dt_val = dt.datetime.fromisoformat(s)
                event_date = dt_val.date()
            except Exception:
                pass

            if event_date == today_utc:
                all_today.append(entry)

                # SUPER FLEXIBLE novice hurdle detection
                is_hurdle = (
                    "hurdle" in name or "hurd" in name or "hrd" in name
                )
                is_novice = (
                    "novice" in name or "nov " in name or "nov." in name or "nov hrd" in name
                )
                if is_hurdle and is_novice:
                    novice_today.append(entry)

        print(
            f"[BETFAIR] Summary: {len(all_any)} total | "
            f"{len(all_today)} today | {len(novice_today)} novice hurdles"
        )

        if novice_today:
            print("[BETFAIR] Returning NOVICE HURDLE markets.")
            return novice_today

        if all_today:
            print("[BETFAIR] No novice hurdles – returning ALL TODAY'S races.")
            return all_today

        print("[BETFAIR] No today's races detected – returning ALL horse markets.")
        return all_any

    # -------------------------------------------------------------------------
    # MARKET DETAILS
    # -------------------------------------------------------------------------

    def get_market_name(self, market_id: str) -> str:
        if self.use_dummy:
            return f"Dummy Market {market_id}"
        params = {
            "filter": {"marketIds": [market_id]},
            "maxResults": 1,
            "marketProjection": ["MARKET_START_TIME", "EVENT"],
        }
        res = self._rpc("listMarketCatalogue", params)
        if not res:
            return market_id
        m = res[0]
        return f"{m['event']['venue']} {m['marketName']}"

    def get_market_start_time(self, market_id: str) -> dt.datetime:
        if self.use_dummy:
            return dt.datetime.utcnow() + dt.timedelta(minutes=10)

        params = {
            "filter": {"marketIds": [market_id]},
            "maxResults": 1,
            "marketProjection": ["MARKET_START_TIME"],
        }
        res = self._rpc("listMarketCatalogue", params)
        if not res:
            raise RuntimeError("Cannot fetch market start time")

        raw = res[0].get("marketStartTime")
        if raw.endswith("Z"):
            raw = raw.replace("Z", "+00:00")
        t = dt.datetime.fromisoformat(raw)
        return t.astimezone(dt.timezone.utc)

    # -------------------------------------------------------------------------
    # FAVOURITES
    # -------------------------------------------------------------------------

    def get_top_two_favourites(self, market_id: str) -> List[Dict[str, Any]]:
        if self.use_dummy:
            return [
                {"selection_id": 1, "name": "Dummy Fav", "back": 2.4, "lay": 2.46},
                {"selection_id": 2, "name": "Dummy 2nd", "back": 3.2, "lay": 3.3},
            ]

        # First get runner names
        cat_params = {
            "filter": {"marketIds": [market_id]},
            "maxResults": 1,
            "marketProjection": ["RUNNER_DESCRIPTION"],
        }
        cat = self._rpc("listMarketCatalogue", cat_params)
        name_map = {
            r["selectionId"]: r["runnerName"]
            for r in cat[0].get("runners", [])
        }

        # Then get prices
        book_params = {
            "marketIds": [market_id],
            "priceProjection": {
                "priceData": ["EX_BEST_OFFERS"],
                "virtualise": True,
            },
        }
        book = self._rpc("listMarketBook", book_params)
        runners = []
        for r in book[0].get("runners", []):
            ex = r.get("ex", {})
            backs = ex.get("availableToBack", [])
            lays = ex.get("availableToLay", [])
            if not backs or not lays:
                continue
            runners.append(
                {
                    "selection_id": r["selectionId"],
                    "name": name_map.get(r["selectionId"], str(r["selectionId"])),
                    "back": backs[0]["price"],
                    "lay": lays[0]["price"],
                }
            )
        runners.sort(key=lambda x: x["back"])
        return runners[:2]

    # -------------------------------------------------------------------------
    # ACCOUNT FUNDS
    # -------------------------------------------------------------------------

    def get_account_funds(self) -> Dict[str, Optional[float]]:
        if self.use_dummy:
            return {
                "available_to_bet": 1000.0,
                "exposure": 0.0,
                "retained_commission": 0.0,
                "exposure_limit": None,
                "discount_rate": None,
                "points_balance": None,
            }

        res = self._account_rpc("getAccountFunds", {})
        return {
            "available_to_bet": res.get("availableToBetBalance"),
            "exposure": res.get("exposure"),
            "retained_commission": res.get("retainedCommission"),
            "exposure_limit": res.get("exposureLimit"),
            "discount_rate": res.get("discountRate"),
            "points_balance": res.get("pointsBalance"),
        }
