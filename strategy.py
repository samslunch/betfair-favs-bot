# strategy.py
#
# StrategyState + BotRunner for 2-fav dutching bot.
#
# Now includes:
#   - Option B loss recovery (recoup losses until a win, then STOP)
#   - Auto-result settlement (no manual won/lost buttons required)
#   - Read-only mode by default (NO placeOrders) – logs "READY" only
#
# Requirements:
#   betfair_client.BetfairClient must provide:
#     - get_market_start_time(market_id) -> datetime
#     - get_market_name(market_id) -> str
#     - get_top_two_favourites(market_id) -> list of dicts containing:
#         {"name": str, "back": float, "selection_id": int}  (selection_id strongly recommended)
#     - get_market_result(market_id) -> dict like:
#         {"status": "OPEN"/"SUSPENDED"/"CLOSED", "winner_selection_id": int|None, "runner_status": {selId: "WINNER"/...}}
#
# Dummy mode:
#   - We simulate a result shortly after "READY" if BetfairClient.use_dummy is True.

from __future__ import annotations

import asyncio
import datetime as dt
from dataclasses import dataclass, field
from typing import Optional, Any, Dict, List


@dataclass
class StrategyState:
    # Bank settings
    starting_bank: float = 100.0
    bank: float = 100.0
    stake_percent: float = 5.0

    # Selection / sequencing
    selected_markets: List[str] = field(default_factory=list)
    current_index: int = 0
    current_market_id: Optional[str] = None

    # Timing
    seconds_before_off: int = 60

    # Odds filters
    min_odds: float = 1.01
    max_odds: float = 1000.0

    # Runtime state
    running: bool = False
    history: List[Dict[str, Any]] = field(default_factory=list)

    # Last bet preview
    last_total_stake: float = 0.0
    last_favourites: Optional[List[Dict[str, Any]]] = None
    last_bet_time_utc: Optional[str] = None

    # Option B: loss recovery
    recovery_target: float = 0.0         # amount we want to recover
    stop_after_win: bool = True          # Option B: stop after first win
    max_recovery_stake_percent: float = 30.0  # cap stake as % of current bank (safety)


class BotRunner:
    """
    Async loop:
      - walks through state.selected_markets
      - waits until (off - seconds_before_off)
      - fetches top 2 favourites, calculates dutch stakes
      - logs READY (no real bets placed)
      - AFTER the off: polls Betfair for settlement and auto-records WON/LOST
      - Option B: if lose, increase recovery_target; if win, STOP
    """

    def __init__(self, client, state: StrategyState):
        self.client = client
        self.state = state
        self._task: Optional[asyncio.Task] = None
        self._ready_at_monotonic: Optional[float] = None  # for dummy-mode simulation

    def start(self) -> None:
        if self.state.running:
            print("[BOT] Already running.")
            return
        if not self.state.selected_markets:
            print("[BOT] Cannot start: no markets selected.")
            return

        self.state.running = True
        if self.state.current_index >= len(self.state.selected_markets):
            self.state.current_index = 0

        loop = asyncio.get_event_loop()
        self._task = loop.create_task(self._run_loop())
        print("[BOT] Loop started.")

    def stop(self) -> None:
        self.state.running = False
        if self._task and not self._task.done():
            self._task.cancel()
        print("[BOT] Stop requested.")

    # -------------------------
    # Core helpers
    # -------------------------

    @staticmethod
    def _dutch_calc(total_stake: float, o1: float, o2: float) -> Dict[str, float]:
        inv_sum = (1.0 / o1) + (1.0 / o2)
        if inv_sum <= 0:
            return {"stake1": 0.0, "stake2": 0.0, "profit_each": -total_stake}

        stake1 = total_stake * (1.0 / o1) / inv_sum
        stake2 = total_stake - stake1
        profit_each = total_stake / inv_sum - total_stake  # net profit if either wins (approx)
        return {"stake1": stake1, "stake2": stake2, "profit_each": profit_each}

    def _advance_market(self) -> None:
        self.state.current_index += 1
        self.state.current_market_id = None
        self.state.last_favourites = None
        self.state.last_total_stake = 0.0
        self.state.last_bet_time_utc = None
        self._ready_at_monotonic = None

    def _compute_total_stake_for_recovery(self, o1: float, o2: float) -> float:
        """
        Option B stake sizing:
          - base stake = bank * stake_percent
          - if recovery_target > 0, try to size stake so that profit_each >= recovery_target
          - cap stake to bank * max_recovery_stake_percent
        """
        bank = float(self.state.bank or 0.0)
        if bank <= 0:
            return 0.0

        base = bank * (float(self.state.stake_percent or 0.0) / 100.0)

        inv_sum = (1.0 / o1) + (1.0 / o2)
        denom = (1.0 / inv_sum) - 1.0 if inv_sum > 0 else 0.0  # profit_each = stake * denom

        desired_profit = max(0.0, float(self.state.recovery_target or 0.0))
        required = 0.0
        if desired_profit > 0 and denom > 0:
            required = desired_profit / denom

        total = max(base, required)

        # Safety cap
        cap = bank * (float(self.state.max_recovery_stake_percent or 0.0) / 100.0)
        if cap > 0:
            total = min(total, cap)

        # Also never exceed bank
        total = min(total, bank)

        return float(total)

    async def _sleep_chunked(self, seconds: float, chunk: float = 60.0) -> bool:
        """
        Sleep in chunks so stop() can interrupt.
        Returns False if cancelled/should stop.
        """
        remaining = max(0.0, seconds)
        while remaining > 0 and self.state.running:
            s = min(chunk, remaining)
            try:
                await asyncio.sleep(s)
            except asyncio.CancelledError:
                return False
            remaining -= s
        return self.state.running

    async def _wait_for_settlement_and_record(self, market_id: str, market_name: str) -> None:
        """
        Poll Betfair until market is CLOSED and winner known, then record result.
        In dummy mode, simulate result a short time after READY.
        """
        # Small grace period after off
        await self._sleep_chunked(10.0, chunk=10.0)
        if not self.state.running or self.state.current_market_id != market_id:
            return

        favs = self.state.last_favourites or []
        total_stake = float(self.state.last_total_stake or 0.0)

        # Extract selection IDs best-effort
        sel_ids: List[int] = []
        for f in favs:
            sid = f.get("selection_id")
            if isinstance(sid, int):
                sel_ids.append(sid)

        # Dummy-mode simulation: settle after ~20 seconds from READY
        if getattr(self.client, "use_dummy", False):
            print("[BOT] Dummy mode: simulating settlement...")
            await self._sleep_chunked(20.0, chunk=5.0)
            if not self.state.running or self.state.current_market_id != market_id:
                return
            winner_is_fav = True  # deterministic: treat as win in dummy so you can see workflow
            self._record_auto_result(market_name, market_id, won=winner_is_fav)
            return

        # Live: poll Betfair
        for _ in range(360):  # up to ~1 hour if interval 10s
            if not self.state.running or self.state.current_market_id != market_id:
                return

            try:
                res = self.client.get_market_result(market_id)
                status = (res or {}).get("status") or ""
                status = str(status).upper()

                winner_selection_id = (res or {}).get("winner_selection_id")
                runner_status = (res or {}).get("runner_status") or {}

                if status == "CLOSED":
                    if isinstance(winner_selection_id, int):
                        won = winner_selection_id in sel_ids if sel_ids else False
                        self._record_auto_result(market_name, market_id, won=won)
                        return

                    # fallback: infer winner from runner statuses
                    winner = None
                    for sid_str, st in runner_status.items():
                        try:
                            sid_int = int(sid_str)
                        except Exception:
                            continue
                        if str(st).upper() == "WINNER":
                            winner = sid_int
                            break

                    if isinstance(winner, int):
                        won = winner in sel_ids if sel_ids else False
                        self._record_auto_result(market_name, market_id, won=won)
                        return

                    # CLOSED but no winner? wait a bit more
                    print("[BOT] Market closed but winner not available yet; retrying...")
            except Exception as e:
                print("[BOT] Error checking settlement:", e)

            await self._sleep_chunked(10.0, chunk=10.0)

        print("[BOT] Settlement timeout; skipping market.")
        self._advance_market()

    def _record_auto_result(self, market_name: str, market_id: str, won: bool) -> None:
        """
        Update bank, history, recovery target, and advance/stop.
        """
        total_stake = float(self.state.last_total_stake or 0.0)
        favs = self.state.last_favourites or []

        if won:
            o1 = float(favs[0]["back"])
            o2 = float(favs[1]["back"])
            profit_each = self._dutch_calc(total_stake, o1, o2)["profit_each"]
            pl = float(profit_each)
        else:
            pl = -float(total_stake)

        # Bank update
        self.state.bank = float(self.state.bank or 0.0) + pl

        # Recovery update (Option B)
        if won:
            # We attempted to size stake so profit >= recovery_target, so reset
            self.state.recovery_target = 0.0
        else:
            # You lose the stake
            self.state.recovery_target = float(self.state.recovery_target or 0.0) + float(total_stake)

        entry = {
            "ts_utc": dt.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
            "race_name": market_name,
            "market_id": market_id,
            "favs": (f"{favs[0].get('name','?')} / {favs[1].get('name','?')}") if len(favs) >= 2 else "",
            "total_stake": total_stake,
            "pl": pl,
            "won": won,
            "recovery_target_after": float(self.state.recovery_target or 0.0),
            "bank_after": float(self.state.bank or 0.0),
        }
        self.state.history.append(entry)

        print(
            f"[BOT] RESULT: {market_name} => {'WON' if won else 'LOST'} | "
            f"P/L £{pl:.2f} | bank £{self.state.bank:.2f} | "
            f"recovery_target £{self.state.recovery_target:.2f}"
        )

        # Option B stop-after-win
        if won and bool(self.state.stop_after_win):
            print("[BOT] Option B: win achieved. Stopping bot.")
            self.state.running = False
            self._advance_market()
            return

        # Continue to next market
        self._advance_market()

    # -------------------------
    # Main loop
    # -------------------------

    async def _run_loop(self) -> None:
        while self.state.running:
            if self.state.current_index >= len(self.state.selected_markets):
                print("[BOT] No more selected markets. Stopping.")
                self.state.running = False
                break

            market_id = self.state.selected_markets[self.state.current_index]
            self.state.current_market_id = market_id

            # Fetch market info
            try:
                start_time = self.client.get_market_start_time(market_id)
                market_name = self.client.get_market_name(market_id)
            except Exception as e:
                print("[BOT] Error fetching market info:", e)
                self._advance_market()
                continue

            # Work in UTC
            now = dt.datetime.now(dt.timezone.utc)
            if start_time.tzinfo is None:
                start_time = start_time.replace(tzinfo=dt.timezone.utc)
            else:
                start_time = start_time.astimezone(dt.timezone.utc)

            seconds_to_off = (start_time - now).total_seconds()
            seconds_to_action = seconds_to_off - float(self.state.seconds_before_off or 60)

            if seconds_to_action > 0:
                sleep_for = min(seconds_to_action, 60.0)
                print(
                    f"[BOT] Waiting {sleep_for:.0f}s before checking prices for "
                    f"{market_name} ({market_id}). Off in {seconds_to_off:.0f}s."
                )
                ok = await self._sleep_chunked(sleep_for, chunk=60.0)
                if not ok:
                    return
                continue

            # Time to "place bets" (log only)
            try:
                favs = self.client.get_top_two_favourites(market_id)
            except Exception as e:
                print("[BOT] Error getting favourites:", e)
                self._advance_market()
                continue

            if len(favs) < 2:
                print("[BOT] Fewer than 2 runners with usable prices; skipping.")
                self._advance_market()
                continue

            # Odds range filter
            favs_in_range = [f for f in favs if self.state.min_odds <= float(f["back"]) <= self.state.max_odds]
            if len(favs_in_range) < 2:
                print("[BOT] Top 2 favourites out of odds range; skipping.")
                self._advance_market()
                continue

            o1 = float(favs_in_range[0]["back"])
            o2 = float(favs_in_range[1]["back"])

            total_stake = self._compute_total_stake_for_recovery(o1, o2)
            if total_stake <= 0:
                print("[BOT] Non-positive stake; stopping.")
                self.state.running = False
                break

            calc = self._dutch_calc(total_stake, o1, o2)
            stake1 = calc["stake1"]
            stake2 = calc["stake2"]
            profit_each = calc["profit_each"]

            self.state.last_total_stake = float(total_stake)
            self.state.last_favourites = list(favs_in_range[:2])
            self.state.last_bet_time_utc = dt.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
            self._ready_at_monotonic = asyncio.get_event_loop().time()

            print(
                f"[BOT] READY (NO REAL BETS PLACED): {market_name} ({market_id})\n"
                f"      Recovery target £{self.state.recovery_target:.2f} | cap {self.state.max_recovery_stake_percent:.0f}% of bank\n"
                f"      Stake total £{total_stake:.2f} | Projected profit if win £{profit_each:.2f}\n"
                f"      £{stake1:.2f} on {favs_in_range[0]['name']} @ {o1}\n"
                f"      £{stake2:.2f} on {favs_in_range[1]['name']} @ {o2}\n"
                f"      {self.state.seconds_before_off}s before off."
            )

            # Now auto-wait for settlement and record
            await self._wait_for_settlement_and_record(market_id, market_name)

        print("[BOT] Loop finished.")


