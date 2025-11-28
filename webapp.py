# webapp.py
#
# FastAPI dashboard that uses:
# - betdaq_client.BetdaqClient for race & price data (dummy for now)
# - strategy.ProgressionStrategy for staking / progression

import threading
import time
from typing import List

from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse

from betdaq_client import BetdaqClient
from strategy import StrategyState, ProgressionStrategy


# ======================
# Setup: client + strategy + background loop
# ======================

client = BetdaqClient(use_dummy=True)
state = StrategyState()
strategy = ProgressionStrategy(state)


class BotRunner:
    """
    Simple wrapper that runs the strategy in a background loop.
    No real bets yet: just logs what it *would* do.
    """

    def __init__(self, strategy: ProgressionStrategy, client: BetdaqClient):
        self.strategy = strategy
        self.client = client
        self.running = False

    def start_day(self):
        print("[BOT] Start day requested")
        # Use client's market lookup to name markets
        strategy.start_day(self.client.get_market_name)
        self.running = True

    def stop(self):
        print("[BOT] Stop requested")
        self.running = False

    def on_race_won_manual(self):
        """
        Manual hook for now. Later, you replace this with automatic P&L detection.
        """
        if not state.current_market_id:
            print("[BOT] Race WON pressed but no current market.")
            return
        # assume some positive pnl, just for demonstration
        strategy.on_market_won(pnl=state.last_total_stake)  # treat stake as "profit" in dummy mode
        self.running = False

    def on_race_lost_manual(self):
        if not state.current_market_id:
            print("[BOT] Race LOST pressed but no current market.")
            return
        strategy.on_market_lost(pnl=-state.last_total_stake)
        # Move to next market in sequence if there is one
        if strategy.has_more_markets() and not state.day_done:
            strategy.update_current_market(self.client.get_market_name)
        else:
            print("[BOT] No more markets or day done.")
            self.running = False

    def loop(self):
        print("[BOT] Loop started (dummy; no real bets).")
        while True:
            if self.running and not state.day_done and state.current_market_id:
                # Get top 2 favourites for current market
                favs = self.client.get_top_two_favourites(state.current_market_id)
                if len(favs) == 2:
                    o1 = favs[0]["back"]
                    o2 = favs[1]["back"]
                    s1, s2, total, profit = self.strategy.compute_dutch_for_current(o1, o2)
                    print(
                        f"[BOT] Market: {state.current_market_name} | "
                        f"Back odds: {o1}, {o2} | "
                        f"Total stake: {total:.2f} (s1={s1:.2f}, s2={s2:.2f}) | "
                        f"Profit if either wins: {profit:.2f} | "
                        f"Losses so far: {state.losses_so_far:.2f}"
                    )
                else:
                    print("[BOT] Cannot find 2 favourites for current market.")
            time.sleep(10)


bot = BotRunner(strategy, client)

# Start background loop
thread = threading.Thread(target=bot.loop, daemon=True)
thread.start()


# ======================
# FastAPI app + dashboard
# ======================

app = FastAPI()


def render_dashboard(message: str = ""):
    status = "RUNNING" if bot.running else "STOPPED"
    color = "green" if bot.running else "red"
    day_status = "DAY DONE" if state.day_done else "IN PROGRESS"

    novice_markets = client.get_todays_novice_hurdle_markets()
    selected_set = set(state.selected_market_ids)

    # Race selection checkboxes
    race_list_html = ""
    for m in novice_markets:
        checked = "checked" if m["market_id"] in selected_set else ""
        race_list_html += f"""
          <li>
            <label>
              <input type="checkbox" name="market_ids" value="{m['market_id']}" {checked}/>
              {m['name']}
            </label>
          </li>
        """

    # Current market info
    if state.current_market_id and state.current_market_name:
        current_info = (
            f"Race {state.current_index + 1}/{len(state.selected_market_ids)}: "
            f"{state.current_market_name}"
        )
    else:
        current_info = "No current race selected."

    # Ladder: top 2 favourites + dutch stakes
    favs = []
    ladder_rows = ""
    dutch_text = ""

    if state.current_market_id and not state.day_done:
        favs = client.get_top_two_favourites(state.current_market_id)

    if len(favs) == 2 and not state.day_done:
        o1 = favs[0]["back"]
        o2 = favs[1]["back"]
        s1, s2, total, profit = strategy.compute_dutch_for_current(o1, o2)

        r1 = {**favs[0], "stake": round(s1, 2)}
        r2 = {**favs[1], "stake": round(s2, 2)}
        favs_with_stakes = [r1, r2]

        dutch_text = (
            f"Total stake this race: {total:.2f}. "
            f"Expected profit if either favourite wins: {profit:.2f}. "
            f"Losses so far: {state.losses_so_far:.2f}."
        )
    else:
        favs_with_stakes = favs

    for r in favs_with_stakes:
        stake_display = f"{r['stake']:.2f}" if "stake" in r else "-"
        ladder_rows += f"""
          <tr>
            <td>{r['name']}</td>
            <td style="text-align:center;">{r['back']}</td>
            <td style="text-align:center;">{r['lay']}</td>
            <td style="text-align:center;">{stake_display}</td>
          </tr>
        """

    ladder_html = "<p>No race selected yet. Pick races and start the day.</p>"
    if state.current_market_id and state.current_market_name:
        profit_line = f"<p>{dutch_text}</p>" if dutch_text else ""
        ladder_html = f"""
        <h2>Current race ladder: {state.current_market_name}</h2>
        <table border="1" cellpadding="6" cellspacing="0">
          <tr>
            <th>Runner</th>
            <th>Back</th>
            <th>Lay</th>
            <th>Stake (dutch)</th>
          </tr>
          {ladder_rows}
        </table>
        {profit_line}
        """

    html = f"""
    <html>
      <head>
        <title>Favourites Bot – Web UI</title>
        <style>
          body {{
            font-family: Arial, sans-serif;
            margin: 40px;
          }}
          .status {{
            font-size: 18px;
            margin-bottom: 10px;
          }}
          .status span {{
            color: {color};
            font-weight: bold;
          }}
          .message {{
            color: #007700;
            margin-bottom: 10px;
          }}
          button {{
            padding: 6px 12px;
            font-size: 14px;
          }}
          ul {{
            list-style-type: none;
            padding-left: 0;
          }}
          li {{
            margin-bottom: 6px;
          }}
          table {{
            margin-top: 10px;
            border-collapse: collapse;
          }}
          th, td {{
            padding: 4px 10px;
          }}
          .settings {{
            margin-top: 20px;
          }}
          input[type="text"], input[type="number"] {{
            padding: 3px;
            width: 120px;
          }}
        </style>
      </head>
      <body>
        <h1>Favourites Bot – Novice Hurdles (Dutching, Dummy)</h1>

        <div class="status">
          Bot status: <span>{status}</span> | Day status: <b>{day_status}</b><br/>
          {current_info}
        </div>

        {"<div class='message'>" + message + "</div>" if message else ""}

        <form method="post" action="/start_day" style="display:inline-block; margin-right:10px;">
          <button type="submit">Start Day</button>
        </form>
        <form method="post" action="/stop" style="display:inline-block; margin-right:10px;">
          <button type="submit">Stop</button>
        </form>
        <form method="post" action="/race_won" style="display:inline-block; margin-right:10px;">
          <button type="submit">Race WON (dummy)</button>
        </form>
        <form method="post" action="/race_lost" style="display:inline-block;">
          <button type="submit">Race LOST (dummy)</button>
        </form>

        <h2>Select today's Novice Hurdle races (in order)</h2>
        <form method="post" action="/update_race_selection">
          <ul>
            {race_list_html}
          </ul>
          <button type="submit">Save race list</button>
        </form>

        {ladder_html}

        <div class="settings">
          <h2>Settings</h2>
          <form method="post" action="/settings">
            <label>
              Min favourite odds:
              <input type="text" name="min_fav_odds" value="{state.min_fav_odds}"/>
            </label>
            <label>
              Max favourite odds:
              <input type="text" name="max_fav_odds" value="{state.max_fav_odds}"/>
            </label>
            <label>
              Target profit per winning race:
              <input type="text" name="target_profit_per_win" value="{state.target_profit_per_win}"/>
            </label>
            <label>
              Max daily loss:
              <input type="text" name="max_daily_loss" value="{state.max_daily_loss}"/>
            </label>
            <br/><br/>
            <button type="submit">Save Settings</button>
          </form>
        </div>

        <p style="margin-top:30px; color:#666;">
          ALL DATA IS DUMMY – no real bets are placed.<br/>
          When you plug in the real Betdaq API, BetdaqClient will:
          fetch live races & prices, place bets, and read P&L to drive the strategy automatically.
        </p>
      </body>
    </html>
    """
    return HTMLResponse(content=html)


@app.get("/", response_class=HTMLResponse)
async def dashboard():
    return render_dashboard()


@app.post("/start_day", response_class=HTMLResponse)
async def start_day(request: Request):
    bot.start_day()
    return render_dashboard("Day started. Working through your selected races in order.")


@app.post("/stop", response_class=HTMLResponse)
async def stop_bot(request: Request):
    bot.stop()
    return render_dashboard("Bot stopped.")


@app.post("/race_won", response_class=HTMLResponse)
async def race_won(request: Request):
    bot.on_race_won_manual()
    return render_dashboard("Race marked as WON (dummy). Day stopped.")


@app.post("/race_lost", response_class=HTMLResponse)
async def race_lost(request: Request):
    bot.on_race_lost_manual()
    return render_dashboard("Race marked as LOST (dummy). Moving on if possible.")


@app.post("/update_race_selection", response_class=HTMLResponse)
async def update_race_selection(market_ids: List[str] = Form(default=[])):
    state.selected_market_ids = market_ids
    state.current_index = 0
    strategy.update_current_market(client.get_market_name)
    return render_dashboard("Race list updated.")


@app.post("/settings", response_class=HTMLResponse)
async def update_settings(
    min_fav_odds: str = Form(...),
    max_fav_odds: str = Form(...),
    target_profit_per_win: str = Form(...),
    max_daily_loss: str = Form(...),
):
    try:
        state.min_fav_odds = float(min_fav_odds)
        state.max_fav_odds = max(state.min_fav_odds, float(max_fav_odds))
        state.target_profit_per_win = max(0.01, float(target_profit_per_win))
        state.max_daily_loss = max(0.01, float(max_daily_loss))
        msg = "Settings updated."
    except Exception as e:
        print("[SETTINGS ERROR]", e)
        msg = "Error updating settings. Please check your values."

    return render_dashboard(msg)
