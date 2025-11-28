# betdaq_client.py
#
# Data / API layer. Currently uses dummy data so everything works offline.
# Later you can plug real Betdaq API calls into the same interface.

from typing import List, Dict


class BetdaqClient:
    def __init__(self, use_dummy: bool = True):
        self.use_dummy = use_dummy
        # Dummy data – replace with real API calls later.
        self._dummy_races: List[Dict] = [
            {"market_id": "R1", "name": "Cheltenham 13:40 - Novices' Hurdle (Class 3)"},
            {"market_id": "R2", "name": "Newbury 14:50 - Novice Hurdle (Class 2)"},
            {"market_id": "R3", "name": "Ascot 16:05 - 2m Novices' Hurdle"},
            {"market_id": "R4", "name": "Cheltenham 17:10 - Handicap Hurdle"},
        ]

        self._dummy_runners: Dict[str, List[Dict]] = {
            "R1": [
                {"name": "Fast Fox", "back": 3.2, "lay": 3.3},
                {"name": "Storm Rider", "back": 4.5, "lay": 4.6},
                {"name": "Midnight Star", "back": 6.0, "lay": 6.2},
            ],
            "R2": [
                {"name": "Golden Lily", "back": 2.8, "lay": 2.9},
                {"name": "Blue Orchid", "back": 3.9, "lay": 4.0},
                {"name": "Silver Dream", "back": 7.5, "lay": 7.8},
            ],
            "R3": [
                {"name": "Rocket Man", "back": 2.1, "lay": 2.2},
                {"name": "Lightning Bolt", "back": 3.4, "lay": 3.5},
                {"name": "Dark Thunder", "back": 9.0, "lay": 9.4},
            ],
            "R4": [
                {"name": "Old Warrior", "back": 3.5, "lay": 3.6},
                {"name": "Soft Ground", "back": 4.2, "lay": 4.3},
                {"name": "Final Flight", "back": 6.8, "lay": 7.0},
            ],
        }

    # ---------------------------
    # Races / markets
    # ---------------------------

    def get_todays_novice_hurdle_markets(self) -> List[Dict]:
        """
        Return list of today's novice hurdle markets.
        Each item is {"market_id": str, "name": str}.
        """
        # In real Betdaq version:
        # - call API for today's horse racing markets
        # - filter where name contains "novice"/"novices" and "hurdle"
        markets = []
        for r in self._dummy_races:
            name_lower = r["name"].lower()
            if ("novice" in name_lower or "novices" in name_lower) and "hurdle" in name_lower:
                markets.append(r)
        return markets

    def get_market_name(self, market_id: str) -> str | None:
        for r in self._dummy_races:
            if r["market_id"] == market_id:
                return r["name"]
        return None

    # ---------------------------
    # Runners / favourites
    # ---------------------------

    def get_top_two_favourites(self, market_id: str) -> List[Dict]:
        """
        Return up to 2 favourites (lowest back price) for a market.
        Each runner dict: {"name": str, "back": float, "lay": float}
        """
        runners = self._dummy_runners.get(market_id, [])
        if not runners:
            return []
        sorted_runners = sorted(runners, key=lambda r: r["back"])
        return sorted_runners[:2]

    # ---------------------------
    # Bets / P&L – placeholders for future automation
    # ---------------------------

    def place_dutch_bets(self, market_id: str, runners_with_stakes: List[Dict]) -> None:
        """
        Placeholder: later this should place back bets on the given runners via Betdaq.
        runners_with_stakes example:
        [
            {"selection_id": 123, "name": "Fast Fox", "odds": 3.2, "stake": 5.45},
            {"selection_id": 456, "name": "Storm Rider", "odds": 4.5, "stake": 4.55},
        ]
        """
        print("[BETDAQ CLIENT] (dummy) Would place bets:", market_id, runners_with_stakes)

    def get_market_pnl(self, market_id: str) -> float:
        """
        Placeholder: later, query actual settled P&L for this market from Betdaq.
        For now, always return 0.0 so nothing automatic happens.
        """
        print("[BETDAQ CLIENT] (dummy) get_market_pnl called for", market_id)
        return 0.0
