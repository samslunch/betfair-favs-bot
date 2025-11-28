# strategy.py
#
# Pure betting logic: dutching, progression, stop-after-first-win.
# This module does NOT depend on FastAPI or a specific API client.

from dataclasses import dataclass, field
from typing import List, Optional, Tuple


# ---------------------------
# Dutching helpers
# ---------------------------

def calc_dutch_two(back1: float, back2: float, total_stake: float) -> Tuple[float, float, float]:
    """
    Calculate dutching stakes for two selections so the return is equal
    if either wins.

    Returns (stake1, stake2, profit_if_either_wins).
    """
    if total_stake <= 0 or back1 <= 1.0 or back2 <= 1.0:
        return 0.0, 0.0, 0.0

    inv1 = 1.0 / back1
    inv2 = 1.0 / back2
    denom = inv1 + inv2
    if denom == 0:
        return 0.0, 0.0, 0.0

    s1 = total_stake * inv1 / denom
    s2 = total_stake * inv2 / denom

    total = s1 + s2
    _return = s1 * back1  # same as s2 * back2 by construction
    profit = _return - total

    return s1, s2, profit


def profit_per_unit(back1: float, back2: float) -> float:
    """
    Profit if total stake = 1.0 when dutching two selections.
    """
    _, _, p = calc_dutch_two(back1, back2, 1.0)
    return p


def required_total_stake(back1: float, back2: float, losses_so_far: float, target_profit: float) -> float:
    """
    Given current losses and desired profit, compute total stake needed so that
    profit_if_either_wins ≈ losses_so_far + target_profit.
    """
    ppu = profit_per_unit(back1, back2)
    if ppu <= 0:
        return 0.0
    return (losses_so_far + target_profit) / ppu


# ---------------------------
# Strategy state & logic
# ---------------------------

@dataclass
class StrategyState:
    # race sequencing
    selected_market_ids: List[str] = field(default_factory=list)
    current_index: int = 0
    current_market_id: Optional[str] = None
    current_market_name: Optional[str] = None

    # staking + progression
    min_fav_odds: float = 1.5
    max_fav_odds: float = 5.0
    target_profit_per_win: float = 5.0
    losses_so_far: float = 0.0
    max_daily_loss: float = 50.0

    # status
    day_done: bool = False
    last_total_stake: float = 0.0


class ProgressionStrategy:
    """
    Holds the state & rules for:
    - race sequence
    - progression staking
    - stopping after first winning race
    """

    def __init__(self, state: StrategyState):
        self.state = state

    # --- race sequence helpers ---

    def update_current_market(self, market_lookup_fn) -> None:
        """
        market_lookup_fn: function that takes market_id and returns market name.
        """
        s = self.state

        if not s.selected_market_ids:
            s.current_market_id = None
            s.current_market_name = None
            return

        if s.current_index >= len(s.selected_market_ids):
            s.current_market_id = None
            s.current_market_name = None
            print("[STRATEGY] No more markets in sequence.")
            return

        mid = s.selected_market_ids[s.current_index]
        s.current_market_id = mid
        s.current_market_name = market_lookup_fn(mid)
        print(
            f"[STRATEGY] Now on market {s.current_index + 1}/{len(s.selected_market_ids)}: "
            f"{s.current_market_name}"
        )

    def start_day(self, market_lookup_fn) -> None:
        s = self.state
        print("[STRATEGY] Start day")
        s.losses_so_far = 0.0
        s.day_done = False
        s.current_index = 0
        self.update_current_market(market_lookup_fn)

    # --- staking / progression ---

    def compute_dutch_for_current(
        self, fav1_back: float, fav2_back: float
    ) -> Tuple[float, float, float, float]:
        """
        Compute dutch stakes & profit for the current market, given top 2 back odds.
        Returns (stake1, stake2, total_stake, profit_if_win).
        """
        s = self.state
        total = required_total_stake(
            fav1_back,
            fav2_back,
            s.losses_so_far,
            s.target_profit_per_win,
        )
        s.last_total_stake = total
        stake1, stake2, profit = calc_dutch_two(fav1_back, fav2_back, total)
        return stake1, stake2, total, profit

    def on_market_won(self, pnl: float) -> None:
        """
        Called when this market is confirmed a net win (pnl > 0).
        Reset progression and stop for the day.
        """
        s = self.state
        print(f"[STRATEGY] Market WON (pnl={pnl:.2f}). Stopping for the day.")
        s.losses_so_far = 0.0
        s.day_done = True

    def on_market_lost(self, pnl: float) -> None:
        """
        Called when this market is confirmed a net loss (pnl <= 0).
        Add stake/loss, move to next market (if any), enforce daily loss.
        """
        s = self.state
        print(f"[STRATEGY] Market LOST (pnl={pnl:.2f}).")

        # We assume pnl is net (winnings - stakes).
        # If pnl is negative, add absolute to losses_so_far.
        if pnl < 0:
            s.losses_so_far += (-pnl)

        print(f"[STRATEGY] Updated losses_so_far = {s.losses_so_far:.2f}")

        # Check daily limit
        if s.losses_so_far >= s.max_daily_loss:
            print("[STRATEGY] Max daily loss reached. Stopping for the day.")
            s.day_done = True
            return

        # Move to next market
        s.current_index += 1

    def has_more_markets(self) -> bool:
        s = self.state
        return s.current_index < len(s.selected_market_ids)
