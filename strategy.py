# strategy.py
#
# Core state + staking / progression logic for the Betfair favourites bot.
# - StrategyState holds all session / day state.
# - ProgressionStrategy handles:
#     * starting the day
#     * stepping through selected markets
#     * computing dutched stakes for the 1st & 2nd favourite
#     * tracking wins / losses / bank / P&L
#     * enforcing max daily loss
#     * "one winner and done" rule

from dataclasses import dataclass, field
from typing import List, Optional, Callable, Tuple


@dataclass
class StrategyState:
    # Banking / P&L
    starting_bank: float = 100.0
    current_bank: float = 100.0
    todays_pl: float = 0.0
    races_played: int = 0
    losses_so_far: float = 0.0  # total absolute losses this day
    day_done: bool = False

    # Market / race selection
    selected_market_ids: List[str] = field(default_factory=list)
    current_market_id: Optional[str] = None
    current_market_name: Optional[str] = None
    current_index: int = 0  # index into selected_market_ids

    # Odds filters
    min_fav_odds: float = 1.5
    max_fav_odds: float = 5.0

    # Staking / risk
    target_profit_per_win: float = 5.0  # base profit target for a winning race
    max_daily_loss: float = 20.0        # stop for the day if losses_so_far >= this

    # Last race stakes (for logging / manual “won/lost” actions)
    last_total_stake: float = 0.0


class ProgressionStrategy:
    """
    Handles Dutching 2 favourites in each selected market, with:
    - target profit per win
    - accumulating loss recovery
    - max daily loss stop
    - one winner -> stop for the day
    """

    def __init__(self, state: StrategyState):
        self.state = state

    # -----------------------------------------------------
    # Helpers for market navigation
    # -----------------------------------------------------

    def _set_current_market(self, market_id: Optional[str], resolver: Callable[[str], str]):
        self.state.current_market_id = market_id
        if market_id is None:
            self.state.current_market_name = None
        else:
            try:
                self.state.current_market_name = resolver(market_id)
            except Exception as e:
                print(f"[STRATEGY] Error resolving market name for {market_id}: {e}")
                self.state.current_market_name = market_id

    def update_current_market(self, resolver: Callable[[str], str]):
        """
        Update current_market_id/name based on current_index and selected list.
        """
        if 0 <= self.state.current_index < len(self.state.selected_market_ids):
            mid = self.state.selected_market_ids[self.state.current_index]
            self._set_current_market(mid, resolver)
        else:
            self._set_current_market(None, resolver)

    def has_more_markets(self) -> bool:
        """
        Are there more markets after the current_index?
        """
        return self.state.current_index + 1 < len(self.state.selected_market_ids)

    # -----------------------------------------------------
    # Day lifecycle
    # -----------------------------------------------------

    def start_day(self, resolver: Callable[[str], str]):
        """
        Reset daily state & start at the first selected market.
        """
        print("[STRATEGY] Starting day.")
        self.state.todays_pl = 0.0
        self.state.races_played = 0
        self.state.losses_so_far = 0.0
        self.state.day_done = False
        self.state.last_total_stake = 0.0

        # Start at first selected market (if any)
        if self.state.selected_market_ids:
            self.state.current_index = 0
            self.update_current_market(resolver)
        else:
            self.state.current_index = 0
            self._set_current_market(None, resolver)

    # -----------------------------------------------------
    # Dutching calculation for 2 favourites
    # -----------------------------------------------------

    def compute_dutch_for_current(self, odds1: float, odds2: float) -> Tuple[float, float, float, float]:
        """
        Compute dutched stakes for 2 favourites to achieve:
        - profit target = target_profit_per_win + losses_so_far (recovery)
        if feasible with the given odds.

        Returns (stake1, stake2, total_stake, profit_if_either_wins).

        If no valid bet (e.g., odds out of range or maths invalid), returns zeros.
        """
        s = self.state

        # If day is already done or no current market, don't suggest stakes
        if s.day_done or s.current_market_id is None:
            return 0.0, 0.0, 0.0, 0.0

        # Enforce favourite odds bounds
        if not (s.min_fav_odds <= odds1 <= s.max_fav_odds and s.min_fav_odds <= odds2 <= s.max_fav_odds):
            print(
                f"[STRATEGY] Odds {odds1}, {odds2} outside configured range "
                f"[{s.min_fav_odds}, {s.max_fav_odds}] – no bet."
            )
            return 0.0, 0.0, 0.0, 0.0

        # Effective profit target includes loss recovery
        desired_profit = s.target_profit_per_win + s.losses_so_far
        if desired_profit <= 0:
            desired_profit = s.target_profit_per_win

        o1 = float(odds1)
        o2 = float(odds2)

        if o1 <= 1.01 or o2 <= 1.01:
            print("[STRATEGY] Odds too short to compute dutching safely.")
            return 0.0, 0.0, 0.0, 0.0

        # Solve the system for equal profit P (desired_profit):
        #   s1*(o1-1) - s2 = P
        #   s2*(o2-1) - s1 = P
        # -> s1 = P*o2 / det, s2 = P*o1 / det
        # where det = (o1-1)*(o2-1) - 1
        det = (o1 - 1.0) * (o2 - 1.0) - 1.0
        if det <= 0:
            print(
                f"[STRATEGY] det <= 0 in dutch calculation for odds {o1}, {o2}. "
                "Cannot achieve the desired equal-profit dutch – skipping."
            )
            return 0.0, 0.0, 0.0, 0.0

        stake1 = desired_profit * o2 / det
        stake2 = desired_profit * o1 / det

        if stake1 <= 0 or stake2 <= 0:
            print(
                f"[STRATEGY] Computed non-positive stakes s1={stake1}, s2={stake2}. "
                "Skipping dutch."
            )
            return 0.0, 0.0, 0.0, 0.0

        total_stake = stake1 + stake2

        # Basic bank safety: don't allow staking beyond current bank
        if total_stake > s.current_bank:
            print(
                f"[STRATEGY] Total stake {total_stake:.2f} exceeds current bank "
                f"{s.current_bank:.2f}. Skipping or you may want to lower your target."
            )
            return 0.0, 0.0, 0.0, 0.0

        # Profit if either wins should be ~desired_profit by construction
        profit_if_wins = desired_profit

        # Save last stake for logging / manual WON/LOST triggers
        s.last_total_stake = total_stake

        return stake1, stake2, total_stake, profit_if_wins

    # -----------------------------------------------------
    # Handling race outcomes (manual for now)
    # -----------------------------------------------------

    def on_market_won(self, pnl: float):
        """
        Called when the current race is marked as WON.
        pnl should be the actual profit from that race (net of stakes).
        For dummy mode, we take pnl ~ last_total_stake (as a stand-in).
        """
        s = self.state

        print(
            f"[STRATEGY] Market WON. pnl={pnl:.2f} | "
            f"before: bank={s.current_bank:.2f}, pl={s.todays_pl:.2f}"
        )

        s.todays_pl += pnl
        s.current_bank += pnl
        s.races_played += 1
        s.losses_so_far = 0.0
        s.last_total_stake = 0.0

        # "One winner and done" rule
        s.day_done = True
        print(
            f"[STRATEGY] After WIN: bank={s.current_bank:.2f}, "
            f"pl={s.todays_pl:.2f}. Day marked DONE."
        )

    def on_market_lost(self, pnl: float):
        """
        Called when the current race is marked as LOST.
        pnl should be negative (loss).
        For dummy mode, we treat pnl = -abs(last_total_stake).
        """
        s = self.state
        loss_amount = -pnl  # pnl is negative

        print(
            f"[STRATEGY] Market LOST. pnl={pnl:.2f} | "
            f"before: bank={s.current_bank:.2f}, pl={s.todays_pl:.2f}, "
            f"losses_so_far={s.losses_so_far:.2f}"
        )

        s.todays_pl += pnl
        s.current_bank += pnl
        s.races_played += 1
        s.losses_so_far += loss_amount
        s.last_total_stake = 0.0

        # Check max daily loss stop
        if s.losses_so_far >= s.max_daily_loss:
            s.day_done = True
            print(
                f"[STRATEGY] Max daily loss reached "
                f"({s.losses_so_far:.2f} >= {s.max_daily_loss:.2f}). Day marked DONE."
            )
        else:
            print(
                f"[STRATEGY] After LOSS: bank={s.current_bank:.2f}, "
                f"pl={s.todays_pl:.2f}, losses_so_far={s.losses_so_far:.2f}. "
                "Continuing to next market (if any)."
            )
