# strategy.py
#
# Holds:
#  - StrategyState: all bot state (bank, selections, odds limits, etc.)
#  - ProgressionStrategy: staking logic, P&L handling, race progression

from dataclasses import dataclass, field
from typing import List, Optional, Callable, Dict, Any
from datetime import datetime


@dataclass
class StrategyState:
    # --- Bank & P/L ---
    starting_bank: float = 1000.0
    current_bank: float = 1000.0
    todays_pl: float = 0.0
    races_played: int = 0
    losses_so_far: float = 0.0
    day_done: bool = False

    # --- Race sequence ---
    selected_market_ids: List[str] = field(default_factory=list)
    current_market_id: Optional[str] = None
    current_market_name: Optional[str] = None
    current_index: int = 0  # index into selected_market_ids

    # --- Odds / risk settings ---
    min_fav_odds: float = 1.5
    max_fav_odds: float = 5.0
    target_profit_per_win: float = 10.0
    max_daily_loss: float = 100.0

    # --- Last race calc ---
    last_total_stake: float = 0.0

    # --- Timing for auto-bet window ---
    current_market_start: Optional[datetime] = None
    bet_placed_for_current: bool = False

    # --- Optional history log (not shown in UI yet, but kept for future) ---
    history: List[Dict[str, Any]] = field(default_factory=list)


class ProgressionStrategy:
    """
    Very simple progression:
      - On a winning race: reset accumulator & stop for the day.
      - On a losing race: add loss to losses_so_far.
      - Dutch 2 favourites so that, if either wins, the profit
        aims to cover (losses_so_far + target_profit_per_win).
      - Respect min/max odds and max_daily_loss.
    """

    def __init__(self, state: StrategyState):
        self.state = state

    # -----------------------
    # Day / race sequence
    # -----------------------

    def start_day(self, market_name_lookup: Callable[[str], str]):
        """
        Called when you hit 'Start Day' in the web UI.
        Resets P&L for the session (but not the starting bank snapshot).
        """
        s = self.state
        print("[STRATEGY] start_day() called.")
        s.todays_pl = 0.0
        s.races_played = 0
        s.losses_so_far = 0.0
        s.day_done = False
        s.last_total_stake = 0.0
        s.current_market_start = None
        s.bet_placed_for_current = False

        if s.selected_market_ids:
            s.current_index = 0
            self.update_current_market(market_name_lookup)
        else:
            s.current_market_id = None
            s.current_market_name = None

    def update_current_market(self, market_name_lookup: Callable[[str], str]):
        """
        Set the current market based on current_index into selected_market_ids.
        If index is out of range, mark day as done.
        """
        s = self.state
        s.current_market_start = None
        s.bet_placed_for_current = False

        if not s.selected_market_ids:
            s.current_market_id = None
            s.current_market_name = None
            s.day_done = True
            print("[STRATEGY] No markets selected – day done.")
            return

        if s.current_index < 0 or s.current_index >= len(s.selected_market_ids):
            s.current_market_id = None
            s.current_market_name = None
            s.day_done = True
            print("[STRATEGY] current_index out of range – day done.")
            return

        market_id = s.selected_market_ids[s.current_index]
        s.current_market_id = market_id
        try:
            s.current_market_name = market_name_lookup(market_id) or market_id
        except Exception as e:
            print("[STRATEGY] Error looking up market name:", e)
            s.current_market_name = market_id

        s.last_total_stake = 0.0
        print(f"[STRATEGY] Now on market {s.current_index + 1}/{len(s.selected_market_ids)}:"
              f" {s.current_market_name} ({s.current_market_id})")

    def has_more_markets(self) -> bool:
        s = self.state
        return (s.current_index + 1) < len(s.selected_market_ids) and not s.day_done

    # -----------------------
    # Dutching / staking
    # -----------------------

    def compute_dutch_for_current(self, odds1: float, odds2: float):
        """
        Compute stakes on two selections so that the profit if either wins
        aims to be:
            target_profit_per_win + losses_so_far

        Also:
         - enforce min/max favourite odds
         - cap stakes by current_bank
        Returns: (stake1, stake2, total_stake, profit_if_win)
        """

        s = self.state

        # Enforce odds limits
        if not (s.min_fav_odds <= odds1 <= s.max_fav_odds):
            print(f"[STRATEGY] odds1={odds1} out of range, returning zero stakes.")
            return 0.0, 0.0, 0.0, 0.0
        if not (s.min_fav_odds <= odds2 <= s.max_fav_odds):
            print(f"[STRATEGY] odds2={odds2} out of range, returning zero stakes.")
            return 0.0, 0.0, 0.0, 0.0

        # Desired profit this race (profit after covering prior losses)
        target_profit = s.target_profit_per_win + s.losses_so_far
        if target_profit <= 0:
            print("[STRATEGY] target_profit <= 0, returning zero stakes.")
            return 0.0, 0.0, 0.0, 0.0

        k1 = odds1 - 1.0
        k2 = odds2 - 1.0

        if k1 <= 0 or k2 <= 0:
            print("[STRATEGY] invalid odds, returning zero stakes.")
            return 0.0, 0.0, 0.0, 0.0

        inv1 = 1.0 / k1
        inv2 = 1.0 / k2
        inv_sum = inv1 + inv2

        if inv_sum >= 1.0:
            # You can't get positive profit with this combination of odds
            print("[STRATEGY] inv_sum >= 1; dutch not feasible for positive profit.")
            return 0.0, 0.0, 0.0, 0.0

        # See derivation in earlier message
        R = target_profit / (1.0 - inv_sum)
        stake1 = R * inv1
        stake2 = R * inv2
        total_stake = stake1 + stake2

        # Bank risk control: if total_stake > current_bank, scale down
        if total_stake > s.current_bank and s.current_bank > 0:
            scale = s.current_bank / total_stake
            stake1 *= scale
            stake2 *= scale
            total_stake *= scale
            target_profit *= scale  # actual achievable profit

        s.last_total_stake = total_stake

        return stake1, stake2, total_stake, target_profit

    # -----------------------
    # Handling race results
    # -----------------------

    def _record_history(self, pnl: float):
        s = self.state
        entry = {
            "timestamp": datetime.utcnow().isoformat(timespec="seconds") + "Z",
            "market_id": s.current_market_id,
            "market_name": s.current_market_name,
            "pnl": pnl,
            "bank_after": s.current_bank,
        }
        s.history.append(entry)

    def on_market_won(self, pnl: float):
        """
        Called when the current race is a winner (from /race_won for now).
        pnl is profit for that race (e.g. +10.0).
        """
        s = self.state
        print(f"[STRATEGY] on_market_won called with pnl={pnl:.2f}")

        s.current_bank += pnl
        s.todays_pl += pnl
        s.races_played += 1
        s.losses_so_far = 0.0
        s.last_total_stake = 0.0
        self._record_history(pnl)

        s.day_done = True
        print(f"[STRATEGY] Day done after win. Bank now {s.current_bank:.2f}, P/L {s.todays_pl:.2f}")

    def on_market_lost(self, pnl: float):
        """
        Called when the current race loses (from /race_lost for now).
        pnl should be negative (e.g. -10.0).
        """
        s = self.state
        print(f"[STRATEGY] on_market_lost called with pnl={pnl:.2f}")

        s.current_bank += pnl
        s.todays_pl += pnl
        s.races_played += 1

        loss = -pnl if pnl < 0 else 0.0
        s.losses_so_far += loss
        s.last_total_stake = 0.0
        self._record_history(pnl)

        if s.todays_pl <= -abs(s.max_daily_loss):
            s.day_done = True
            print(
                f"[STRATEGY] Max daily loss reached ({s.todays_pl:.2f} <= -{s.max_daily_loss:.2f}). "
                "Day done."
            )
        else:
            print(
                f"[STRATEGY] Loss recorded. losses_so_far={s.losses_so_far:.2f}, "
                f"bank={s.current_bank:.2f}, today's P/L={s.todays_pl:.2f}"
            )
