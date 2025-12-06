# strategy.py
#
# Holds:
#   - StrategyState: configuration + runtime state
#   - BotRunner: simple controller for start/stop + race_won/lost
#
# NOTE:
#   This version does NOT place real bets.
#   It just updates bank, tracks simple P/L, and advances through races.
#   BetfairClient is used only to get market names (for display/history).

from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional

from betfair_client import BetfairClient


@dataclass
class StrategyState:
    # Config
    starting_bank: float = 100.0
    bank: float = 100.0
    target_profit: float = 5.0  # £ profit to aim for each day
    stake_percent: float = 5.0  # % of bank to stake per race
    min_odds: float = 1.5
    max_odds: float = 4.5
    seconds_before_off: int = 60

    # Races
    selected_markets: List[str] = field(default_factory=list)
    current_index: int = 0  # index into selected_markets

    # Runtime
    running: bool = False
    cumulative_pl: float = 0.0  # total P/L for the day

    # History of past races (for UI)
    # Each entry: { 'race_name', 'favs', 'total_stake', 'pl' }
    history: List[Dict[str, Any]] = field(default_factory=list)


class BotRunner:
    """
    Very simple controller:
      - start() just sets .running = True
      - stop() sets .running = False
      - mark_race_won() / mark_race_lost() update bank & history and
        advance to next race.
    """

    def __init__(self, client: BetfairClient, state: StrategyState):
        self.client = client
        self.state = state

    # -------------------------
    # Public controls
    # -------------------------

    def start(self):
        print("[BOT] Start requested.")
        if not self.state.selected_markets:
            print("[BOT] Cannot start: no markets selected.")
            return
        self.state.running = True
        # We rely on manual Race WON / LOST buttons for now.
        print("[BOT] Bot marked as RUNNING (manual race outcome mode).")

    def stop(self):
        print("[BOT] Stop requested.")
        self.state.running = False
        print("[BOT] Bot marked as STOPPED.")

    def mark_race_won(self):
        """
        Called by /race_won endpoint.
        We:
          - Calculate stake as % of current bank
          - Apply a simple profit model
          - Append to history
          - Advance to next race
          - Stop if target profit reached
        """
        print("[BOT] Race WON signal received.")
        self._handle_race_result(won=True)

    def mark_race_lost(self):
        print("[BOT] Race LOST signal received.")
        self._handle_race_result(won=False)

    # -------------------------
    # Internal helpers
    # -------------------------

    def _current_market_id(self) -> Optional[str]:
        if not self.state.selected_markets:
            return None
        idx = self.state.current_index
        if idx < 0 or idx >= len(self.state.selected_markets):
            return None
        return self.state.selected_markets[idx]

    def _handle_race_result(self, won: bool):
        # If there are no selected markets, nothing to do
        market_id = self._current_market_id()
        if market_id is None:
            print("[BOT] No current market to update (no selection or index out of range).")
            return

        # Try to get a nice market name from Betfair
        try:
            race_name = self.client.get_market_name(market_id)
        except Exception as e:
            print("[BOT] Error fetching market name:", e)
            race_name = market_id

        # For now, we use a simple stake model:
        stake = max(0.0, self.state.bank * (self.state.stake_percent / 100.0))

        # Simple P/L model:
        #   - If WON: assume ~50% return on total stake (e.g. dutching around 2.0–3.0 range)
        #   - If LOST: full stake is lost.
        if won:
            profit = stake * 0.5
        else:
            profit = -stake

        print(
            f"[BOT] Race result processed: "
            f"{'WON' if won else 'LOST'} | stake={stake:.2f} | P/L={profit:.2f}"
        )

        # Update bank & cumulative P/L
        old_bank = self.state.bank
        self.state.bank += profit
        self.state.cumulative_pl += profit

        # Append to history for the UI
        entry = {
            "race_name": race_name,
            "favs": "Top 2 favourites",  # you can make this more detailed later
            "total_stake": stake,
            "pl": profit,
            "old_bank": old_bank,
            "new_bank": self.state.bank,
        }
        self.state.history.append(entry)

        # Check target profit
        day_pl = self.state.bank - self.state.starting_bank
        print(f"[BOT] Bank updated: {old_bank:.2f} -> {self.state.bank:.2f} | Day P/L={day_pl:.2f}")

        if day_pl >= self.state.target_profit:
            print("[BOT] Target profit reached; stopping for the day.")
            self.state.running = False

        # Advance to next race if any
        if self.state.current_index + 1 < len(self.state.selected_markets):
            self.state.current_index += 1
            print(f"[BOT] Moving to next race index: {self.state.current_index}")
        else:
            print("[BOT] No more races in selection. Stopping.")
            self.state.running = False
