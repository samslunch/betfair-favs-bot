# strategy.py
#
# StrategyState + BotRunner for the Betfair 2-fav dutching bot.
#
# This version:
#   - Keeps track of bank, target, odds limits, selected markets, etc.
#   - Schedules each race: "seconds_before_off" before off time.
#   - Fetches top 2 favourites and calculates dutching stakes (equal profit).
#   - Does NOT place real bets (logging / UI only).
#   - Lets the UI call race_won / race_lost to update bank and history.

from __future__ import annotations

import asyncio
import datetime as dt
from dataclasses import dataclass, field
from typing import List, Optional, Deque, Dict, Any
from collections import deque


@dataclass
class StrategyState:
    # Bank & staking
    starting_bank: float = 100.0
    bank: float = 100.0
    target_profit: float = 5.0
    stake_percent: float = 5.0  # % of bank per race

    # Odds filters
    min_odds: float = 1.5
    max_odds: float = 4.5

    # Timing: when to place bets relative to off
    seconds_before_off: int = 60

    # Race sequence
    selected_markets: List[str] = field(default_factory=list)
    current_index: int = 0
    running: bool = False
    current_market_id: Optional[str] = None

    # For P/L and display
    history: Deque[Dict[str, Any]] = field(default_factory=lambda: deque(maxlen=100))
    last_total_stake: float = 0.0
    last_favourites: Optional[List[Dict[str, Any]]] = None


class BotRunner:
    """
    Simple async loop that:
      - walks through state.selected_markets in order
      - waits until (off - seconds_before_off)
      - fetches top 2 favourites & calculates dutching stakes
      - waits for manual "Race WON/LOST" buttons to be pressed in the UI
    """

    def __init__(self, client, state: StrategyState):
        self.client = client
        self.state = state
        self._task: Optional[asyncio.Task] = None

    # -------------------------
    # Public control methods
    # -------------------------

    def start(self) -> None:
        if self.state.running:
            print("[BOT] Already running.")
            return
        if not self.state.selected_markets:
            print("[BOT] Cannot start: no markets selected.")
            return

        self.state.running = True
        # Reset index if we've run out
        if self.state.current_index >= len(self.state.selected_markets):
            self.state.current_index = 0

        # Create a background task on the current event loop
        loop = asyncio.get_event_loop()
        self._task = loop.create_task(self._run_loop())
        print("[BOT] Loop started.")

    def stop(self) -> None:
        self.state.running = False
        if self._task and not self._task.done():
            self._task.cancel()
        print("[BOT] Stop requested")

    def mark_race_won(self) -> None:
        self._record_result(won=True)

    def mark_race_lost(self) -> None:
        self._record_result(won=False)

    # -------------------------
    # Internal main loop
    # -------------------------

    async def _run_loop(self) -> None:
        while self.state.running:
            if self.state.current_index >= len(self.state.selected_markets):
                print("[STRATEGY] No markets selected – day done.")
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
            now = dt.datetime.utcnow().replace(tzinfo=dt.timezone.utc)
            if start_time.tzinfo is None:
                start_time = start_time.replace(tzinfo=dt.timezone.utc)
            else:
                start_time = start_time.astimezone(dt.timezone.utc)

            # How long until we want to "act"?
            seconds_to_off = (start_time - now).total_seconds()
            seconds_to_action = seconds_to_off - self.state.seconds_before_off

            if seconds_to_action > 0:
                # Sleep in chunks so stop() can cut in
                sleep_for = min(seconds_to_action, 60)
                print(
                    f"[BOT] Waiting {sleep_for:.0f}s before checking prices for "
                    f"{market_name} ({market_id}). Off in {seconds_to_off:.0f}s."
                )
                try:
                    await asyncio.sleep(sleep_for)
                except asyncio.CancelledError:
                    print("[BOT] Loop cancelled while waiting.")
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
                print("[BOT] Fewer than 2 runners with usable prices, skipping market.")
                self._advance_market()
                continue

            # Apply odds filters to top 2
            favs_in_range = [
                f for f in favs
                if self.state.min_odds <= f["back"] <= self.state.max_odds
            ]
            if len(favs_in_range) < 2:
                print("[BOT] Top 2 favourites out of odds range, skipping.")
                self._advance_market()
                continue

            total_stake = self.state.bank * (self.state.stake_percent / 100.0)
            if total_stake <= 0:
                print("[BOT] Non-positive stake; stopping.")
                self.state.running = False
                break

            o1 = favs_in_range[0]["back"]
            o2 = favs_in_range[1]["back"]
            inv_sum = (1.0 / o1) + (1.0 / o2)
            stake1 = total_stake * (1.0 / o1) / inv_sum
            stake2 = total_stake - stake1

            self.state.last_total_stake = total_stake
            self.state.last_favourites = favs_in_range

            print(
                f"[BOT] READY: {market_name} ({market_id})\n"
                f"      Stake total £{total_stake:.2f}\n"
                f"      £{stake1:.2f} on {favs_in_range[0]['name']} @ {o1}\n"
                f"      £{stake2:.2f} on {favs_in_range[1]['name']} @ {o2}\n"
                f"      {self.state.seconds_before_off}s before off. (NO REAL BETS PLACED)"
            )

            # Now wait here until the UI marks this race as WON/LOST or bot is stopped
            try:
                while (
                    self.state.running
                    and self.state.current_market_id == market_id
                ):
                    await asyncio.sleep(1.0)
            except asyncio.CancelledError:
                print("[BOT] Loop cancelled while waiting for race result.")
                return

        print("[BOT] Loop finished.")

    # -------------------------
    # Helpers
    # -------------------------

    def _advance_market(self) -> None:
        self.state.current_index += 1
        self.state.current_market_id = None
        self.state.last_favourites = None
        self.state.last_total_stake = 0.0

    def _record_result(self, won: bool) -> None:
        market_id = self.state.current_market_id
        if not market_id or not self.state.last_favourites:
            print("[BOT] No active market to record result for.")
            return

        try:
            race_name = self.client.get_market_name(market_id)
        except Exception:
            race_name = market_id

        total_stake = self.state.last_total_stake
        favs = self.state.last_favourites

        if won:
            # Approx equal-profit dutch based on back odds
            o1 = favs[0]["back"]
            o2 = favs[1]["back"]
            inv_sum = (1.0 / o1) + (1.0 / o2)
            profit_each = total_stake / inv_sum - total_stake
            pl = profit_each
        else:
            pl = -total_stake

        self.state.bank += pl

        entry = {
            "race_name": race_name,
            "favs": f"{favs[0]['name']} / {favs[1]['name']}",
            "total_stake": total_stake,
            "pl": pl,
            "won": won,
        }
        self.state.history.append(entry)

        print(
            f"[BOT] RESULT: {race_name} => {'WON' if won else 'LOST'} | "
            f"P/L £{pl:.2f} | bank now £{self.state.bank:.2f}"
        )

        # Move on to the next race in sequence
        self._advance_market()
