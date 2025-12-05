# webapp.py
#
# FastAPI dashboard that uses:
# - betfair_client.BetfairClient for race & price data (dummy or live)
# - strategy.ProgressionStrategy for staking / progression + bank/P&L
# Now with:
# - Simple login page (username/password)
# - Session cookie to protect all routes
# - Logout button
# - Reset bank + % profiles (2, 5, 10, 15, 20)
# - Live/dummy indicator for Betfair
# - Betfair "available to bet" balance display
# - Mobile-friendly layout (no horizontal scrolling)
# - Results / history panel for past races + P&L

import threading
import time
from typing import List

from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from starlette.middleware.sessions import SessionMiddleware

from betfair_client import BetfairClient
from strategy import StrategyState, ProgressionStrategy


# ======================
# Auth config
# ======================

ADMIN_USERNAME = "adamhill"
ADMIN_PASSWORD = "Adamhillonline1!"
SECRET_KEY = "super-secret-local-key-change-me-later"


# ======================
# Setup: client + strategy + background loop
# ======================

client = BetfairClient(use_dummy=False)
state = StrategyState()
strategy = ProgressionStrategy(state)


class BotRunner:
    """
    Simple wrapper that runs the strategy in a background loop.
    No real bets yet: just logs what it *would* do.
    """

    def __init__(self, strategy: ProgressionStrategy, client: BetfairClient):
        self.strategy = strategy
        self.client = client
        self.running = False

    def start_day(self):
        print("[BOT] Start day requested")
        self.strategy.start_day(self.client.get_market_name)
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
        pnl = max(state.last_total_stake, 0.0)
        self.strategy.on_market_won(pnl=pnl)
        self.running = False

    def on_race_lost_manual(self):
        if not state.current_market_id:
            print("[BOT] Race LOST pressed but no current market.")
            return

        pnl = -abs(state.last_total_stake)
        self.strategy.on_market_lost(pnl=pnl)

        if self.strategy.has_more_markets() and not state.day_done:
            state.current_index += 1
            self.strategy.update_current_market(self.client.get_market_name)
        else:
            print("[BOT] No more markets or day done.")
            self.running = False

    def loop(self):
        print("[BOT] Loop started (dummy; no real bets).")
        while True:
            if self.running and not state.day_done and state.current_market_id:
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
                        f"Losses so far: {state.losses_so_far:.2f} | "
                        f"Bank: {state.current_bank:.2f} | "
                        f"Today P/L: {state.todays_pl:.2f}"
                    )
                else:
                    print("[BOT] Cannot find 2 favourites for current market.")
            time.sleep(10)


bot = BotRunner(strategy, client)

thread = threading.Thread(target=bot.loop, daemon=True)
thread.start()


# ======================
# FastAPI app + session middleware
# ======================

app = FastAPI()
app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY)


# ======================
# Auth helpers & login page
# ======================

def is_authenticated(request: Request) -> bool:
    return bool(request.session.get("authenticated"))


def render_login(message: str = "") -> HTMLResponse:
    html = f"""
    <html>
      <head>
        <title>Betfair Bot – Login</title>
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <style>
          :root {{
            --bg: #020617;
            --bg-elevated: rgba(15, 23, 42, 0.9);
            --border-subtle: rgba(148, 163, 184, 0.2);
            --accent: #22c55e;
            --accent-strong: #16a34a;
            --danger: #ef4444;
            --text-main: #e5e7eb;
            --text-muted: #9ca3af;
          }}
          * {{ box-sizing: border-box; }}
          body {{
            margin: 0;
            padding: 0;
            font-family: system-ui, -apple-system, BlinkMacSystemFont, "SF Pro Text",
                         "Segoe UI", sans-serif;
            color: var(--text-main);
            background: radial-gradient(circle at top, #0f172a 0, #020617 55%, #000 100%);
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            overflow-x: hidden;
          }}
          .shell {{
            width: 100%;
            max-width: 380px;
            padding: 16px;
          }}
          .card {{
            background: var(--bg-elevated);
            border-radius: 18px;
            border: 1px solid var(--border-subtle);
            box-shadow:
              0 24px 60px rgba(15, 23, 42, 0.7),
              0 0 0 1px rgba(15, 23, 42, 0.9);
            padding: 22px 22px 24px;
          }}
          h1 {{
            margin: 0 0 6px;
            font-size: 20px;
            letter-spacing: 0.04em;
            text-transform: uppercase;
          }}
          .subtitle {{
            margin: 0 0 16px;
            font-size: 12px;
            color: var(--text-muted);
          }}
          .field-label {{
            display: flex;
            flex-direction: column;
            gap: 4px;
            margin-bottom: 10px;
            font-size: 12px;
            color: var(--text-muted);
          }}
          .field-label span {{
            font-size: 11px;
            text-transform: uppercase;
            letter-spacing: 0.08em;
          }}
          .field-label input {{
            border-radius: 999px;
            border: 1px solid var(--border-subtle);
            background: rgba(15, 23, 42, 0.9);
            color: var(--text-main);
            padding: 7px 11px;
            font-size: 13px;
            width: 100%;
          }}
          .field-label input:focus {{
            outline: none;
            border-color: var(--accent);
            box-shadow: 0 0 0 1px rgba(34, 197, 94, 0.6);
          }}
          .btn {{
            border: 0;
            border-radius: 999px;
            padding: 8px 14px;
            font-size: 13px;
            cursor: pointer;
            font-weight: 500;
            letter-spacing: 0.03em;
            text-transform: uppercase;
            display: inline-flex;
            align-items: center;
            gap: 6px;
            transition: all 0.16s ease-out;
          }}
          .btn-primary {{
            background: var(--accent);
            color: #022c22;
            width: 100%;
            justify-content: center;
          }}
          .btn-primary:hover {{
            background: var(--accent-strong);
            transform: translateY(-1px);
            box-shadow: 0 10px 20px rgba(34, 197, 94, 0.35);
          }}
          .message {{
            margin-top: 8px;
            padding: 6px 10px;
            border-radius: 10px;
            background: rgba(248, 113, 113, 0.1);
            border: 1px solid rgba(248, 113, 113, 0.7);
            font-size: 12px;
            color: #fecaca;
          }}
          .hint {{
            margin-top: 12px;
            font-size: 11px;
            color: var(--text-muted);
            text-align: center;
          }}
        </style>
      </head>
      <body>
        <div class="shell">
          <div class="card">
            <h1>Betfair Bot</h1>
            <p class="subtitle">Secure login</p>
            <form method="post" action="/login">
              <label class="field-label">
                <span>Username</span>
                <input type="text" name="username" autocomplete="username" />
              </label>
              <label class="field-label">
                <span>Password</span>
                <input type="password" name="password" autocomplete="current-password" />
              </label>
              <button class="btn btn-primary" type="submit">Sign in</button>
            </form>
            {"<div class='message'>" + message + "</div>" if message else ""}
            <div class="hint">
              Use your configured dashboard credentials.
            </div>
          </div>
        </div>
      </body>
    </html>
    """
    return HTMLResponse(content=html)


@app.get("/login", response_class=HTMLResponse)
async def login_get(request: Request):
    if is_authenticated(request):
        return RedirectResponse("/", status_code=303)
    return render_login()


@app.post("/login", response_class=HTMLResponse)
async def login_post(request: Request, username: str = Form(...), password: str = Form(...)):
    if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
        request.session["authenticated"] = True
        print("[AUTH] Login successful.")
        return RedirectResponse("/", status_code=303)
    print("[AUTH] Login failed.")
    return render_login("Invalid username or password.")


@app.post("/logout")
async def logout(request: Request):
    request.session.clear()
    print("[AUTH] Logged out.")
    return RedirectResponse("/login", status_code=303)


# ======================
# Dashboard renderer
# ======================

def render_dashboard(message: str = ""):
    status = "RUNNING" if bot.running else "STOPPED"
    status_color = "#22c55e" if bot.running else "#ef4444"
    day_status = "DAY DONE" if state.day_done else "IN PROGRESS"
    day_color = "#0ea5e9" if not state.day_done else "#eab308"

    bank_start = state.starting_bank
    bank_now = state.current_bank
    pl_today = state.todays_pl
    races = state.races_played
    pl_color = "#22c55e" if pl_today >= 0 else "#ef4444"

    # Betfair balance
    bf_balance = None
    try:
        funds = client.get_account_funds()
        bf_balance = funds.get("available_to_bet")
    except Exception as e:
        print("[BETFAIR] get_account_funds error:", e)
        bf_balance = None
    bf_balance_display = f"£{bf_balance:.2f}" if bf_balance is not None else "N/A"

    novice_markets = client.get_todays_novice_hurdle_markets()
    selected_set = set(state.selected_market_ids)

    race_list_html = ""
    for m in novice_markets:
        checked = "checked" if m["market_id"] in selected_set else ""
        race_list_html += f"""
          <label class="race-item">
            <input type="checkbox" name="market_ids" value="{m['market_id']}" {checked}/>
            <div class="race-card">
              <div class="race-name">{m['name']}</div>
              <div class="race-tag">Novice Hurdle</div>
            </div>
          </label>
        """

    if state.current_market_id and state.current_market_name:
        current_info = (
            f"Race {state.current_index + 1}/{len(state.selected_market_ids)} · "
            f"{state.current_market_name}"
        )
    else:
        current_info = "No current race selected."

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
            f"Total stake this race: {total:.2f} · "
            f"Expected profit if either favourite wins: {profit:.2f} · "
            f"Losses so far: {state.losses_so_far:.2f}"
        )
    else:
        favs_with_stakes = favs

    for r in favs_with_stakes:
        stake_display = f"{r['stake']:.2f}" if "stake" in r else "-"
        ladder_rows += f"""
          <tr>
            <td class="runner-name">{r['name']}</td>
            <td class="runner-odds">{r['back']}</td>
            <td class="runner-odds">{r['lay']}</td>
            <td class="runner-stake">{stake_display}</td>
          </tr>
        """

    ladder_html = "<p class='muted'>No race selected yet. Pick races and start the day.</p>"
    if state.current_market_id and state.current_market_name:
        profit_line = f"<p class='ladder-note'>{dutch_text}</p>" if dutch_text else ""
        ladder_html = f"""
        <div class="section-header">
          <h2>Current race ladder</h2>
          <span class="chip chip-soft">{state.current_market_name}</span>
        </div>
        <div class="table-wrapper">
          <table class="ladder-table">
            <thead>
              <tr>
                <th>Runner</th>
                <th>Back</th>
                <th>Lay</th>
                <th>Stake (dutch)</th>
              </tr>
            </thead>
            <tbody>
              {ladder_rows}
            </tbody>
          </table>
        </div>
        {profit_line}
        """

    # History panel HTML (last 10 races)
    history_rows = ""
    recent_history = list(getattr(state, "history", []))[-10:][::-1]  # newest first

    for h in recent_history:
        pnl_color = "#22c55e" if h["pnl"] >= 0 else "#ef4444"
        history_rows += f"""
          <tr>
            <td class="hist-time">{h['timestamp']}</td>
            <td class="hist-race">{h.get('market_name') or h.get('market_id')}</td>
            <td class="hist-result">{h['result']}</td>
            <td class="hist-stake">£{h['stake']:.2f}</td>
            <td class="hist-pnl" style="color:{pnl_color};">
              £{h['pnl']:.2f}
            </td>
            <td class="hist-bank">£{h['bank_after']:.2f}</td>
          </tr>
        """

    if not history_rows:
        history_html = "<p class='muted'>No races recorded yet. Results will appear here.</p>"
    else:
        history_html = f"""
        <div class="table-wrapper">
          <table class="ladder-table history-table">
            <thead>
              <tr>
                <th>Time (UTC)</th>
                <th>Race</th>
                <th>Result</th>
                <th>Stake</th>
                <th>P/L</th>
                <th>Bank after</th>
              </tr>
            </thead>
            <tbody>
              {history_rows}
            </tbody>
          </table>
        </div>
        """

    mode_label = "live" if not client.use_dummy else "dummy"

    html = f"""
    <html>
      <head>
        <title>Betfair Favourites Bot – Web UI</title>
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <style>
          :root {{
            --bg: #020617;
            --bg-elevated: rgba(15, 23, 42, 0.9);
            --border-subtle: rgba(148, 163, 184, 0.2);
            --accent: #22c55e;
            --accent-soft: rgba(34, 197, 94, 0.12);
            --accent-strong: #16a34a;
            --danger: #ef4444;
            --text-main: #e5e7eb;
            --text-muted: #9ca3af;
            --chip-bg: rgba(148, 163, 184, 0.16);
          }}
          * {{ box-sizing: border-box; }}
          body {{
            margin: 0;
            padding: 0;
            font-family: system-ui, -apple-system, BlinkMacSystemFont, "SF Pro Text",
                         "Segoe UI", sans-serif;
            color: var(--text-main);
            background: radial-gradient(circle at top, #0f172a 0, #020617 55%, #000 100%);
            min-height: 100vh;
            display: flex;
            align-items: flex-start;
            justify-content: center;
            overflow-x: hidden;
          }}
          .shell {{
            width: 100%;
            max-width: 1040px;
            padding: 24px 12px 40px;
          }}
          @media (max-width: 768px) {{
            .shell {{
              padding: 16px 10px 28px;
            }}
          }}
          .card {{
            background: var(--bg-elevated);
            border-radius: 18px;
            border: 1px solid var(--border-subtle);
            box-shadow:
              0 24px 60px rgba(15, 23, 42, 0.7),
              0 0 0 1px rgba(15, 23, 42, 0.9);
            padding: 20px 16px 24px;
          }}
          @media (min-width: 900px) {{
            .card {{
              padding: 24px 24px 28px;
            }}
          }}
          h1 {{
            margin: 0 0 4px;
            font-size: 22px;
            letter-spacing: 0.03em;
            text-transform: uppercase;
          }}
          .subtitle {{
            margin: 0 0 16px;
            font-size: 13px;
            color: var(--text-muted);
          }}
          .top-row {{
            display: flex;
            flex-wrap: wrap;
            gap: 12px;
            align-items: flex-start;
            justify-content: space-between;
            margin-bottom: 14px;
          }}
          .status-block {{
            display: flex;
            flex-direction: column;
            gap: 6px;
            min-width: 0;
          }}
          .badges {{
            display: flex;
            flex-wrap: wrap;
            gap: 8px;
            align-items: center;
          }}
          .chip {{
            display: inline-flex;
            align-items: center;
            gap: 6px;
            padding: 4px 9px;
            border-radius: 999px;
            font-size: 11px;
            letter-spacing: 0.05em;
            text-transform: uppercase;
            border: 1px solid transparent;
            white-space: nowrap;
          }}
          .chip-status {{
            background: rgba(15, 23, 42, 0.9);
            border-color: {status_color};
            color: {status_color};
          }}
          .chip-day {{
            background: rgba(15, 23, 42, 0.9);
            border-color: {day_color};
            color: {day_color};
          }}
          .chip-soft {{
            background: var(--chip-bg);
            border-color: transparent;
            color: var(--text-main);
          }}
          .current-info {{
            font-size: 13px;
            color: var(--text-muted);
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
            max-width: 100%;
          }}
          .controls {{
            display: flex;
            flex-wrap: wrap;
            gap: 6px;
            justify-content: flex-end;
          }}
          .btn {{
            border: 0;
            border-radius: 999px;
            padding: 7px 11px;
            font-size: 12px;
            cursor: pointer;
            font-weight: 500;
            letter-spacing: 0.03em;
            text-transform: uppercase;
            display: inline-flex;
            align-items: center;
            gap: 6px;
            transition: all 0.16s ease-out;
            white-space: nowrap;
          }}
          .btn-primary {{
            background: var(--accent);
            color: #022c22;
          }}
          .btn-primary:hover {{
            background: var(--accent-strong);
            transform: translateY(-1px);
            box-shadow: 0 10px 20px rgba(34, 197, 94, 0.35);
          }}
          .btn-ghost {{
            background: transparent;
            color: var(--text-main);
            border: 1px solid var(--border-subtle);
          }}
          .btn-ghost:hover {{
            background: rgba(148, 163, 184, 0.12);
            transform: translateY(-1px);
          }}
          .btn-danger {{
            background: rgba(248, 113, 113, 0.18);
            color: #fecaca;
            border: 1px solid rgba(248, 113, 113, 0.7);
          }}
          .btn-danger:hover {{
            background: rgba(248, 113, 113, 0.3);
            transform: translateY(-1px);
          }}
          .grid {{
            display: grid;
            grid-template-columns: minmax(0, 1.10fr) minmax(0, 1.05fr);
            gap: 16px;
            margin-top: 18px;
          }}
          @media (max-width: 900px) {{
            .grid {{
              grid-template-columns: 1fr;
            }}
          }}
          .panel {{
            background: rgba(15, 23, 42, 0.7);
            border-radius: 16px;
            border: 1px solid var(--border-subtle);
            padding: 14px 12px 16px;
          }}
          @media (min-width: 900px) {{
            .panel {{
              padding: 16px 18px 18px;
            }}
          }}
          .panel h2 {{
            margin: 0 0 10px;
            font-size: 15px;
          }}
          .section-header {{
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 10px;
            margin-bottom: 8px;
          }}
          .section-header h2 {{
            margin: 0;
          }}
          .race-list {{
            display: flex;
            flex-direction: column;
            gap: 8px;
            max-height: 260px;
            overflow-y: auto;
            padding-right: 4px;
          }}
          .race-item {{
            display: block;
            cursor: pointer;
          }}
          .race-item input[type="checkbox"] {{
            display: none;
          }}
          .race-card {{
            display: flex;
            flex-direction: column;
            gap: 3px;
            padding: 8px 9px;
            border-radius: 10px;
            border: 1px solid var(--border-subtle);
            background: rgba(15, 23, 42, 0.9);
            transition: all 0.15s ease-out;
          }}
          .race-item input[type="checkbox"]:checked + .race-card {{
            border-color: var(--accent);
            box-shadow: 0 0 0 1px rgba(34, 197, 94, 0.7);
          }}
          .race-card:hover {{
            border-color: rgba(148, 163, 184, 0.9);
            transform: translateY(-1px);
          }}
          .race-name {{
            font-size: 13px;
          }}
          .race-tag {{
            font-size: 11px;
            color: var(--accent);
            text-transform: uppercase;
            letter-spacing: 0.09em;
          }}
          .race-actions {{
            margin-top: 8px;
            text-align: right;
          }}
          .table-wrapper {{
            border-radius: 12px;
            border: 1px solid var(--border-subtle);
            overflow: hidden;
            background: rgba(15, 23, 42, 0.9);
          }}
          .ladder-table {{
            width: 100%;
            border-collapse: collapse;
            font-size: 13px;
          }}
          .ladder-table thead {{
            background: rgba(15, 23, 42, 0.95);
          }}
          .ladder-table th,
          .ladder-table td {{
            padding: 6px 8px;
            text-align: left;
          }}
          .ladder-table th {{
            font-weight: 500;
            color: var(--text-muted);
            border-bottom: 1px solid var(--border-subtle);
          }}
          .ladder-table tbody tr:nth-child(even) {{
            background: rgba(15, 23, 42, 0.9);
          }}
          .ladder-table tbody tr:nth-child(odd) {{
            background: rgba(15, 23, 42, 0.8);
          }}
          .runner-name {{
            font-weight: 500;
          }}
          .runner-odds {{
            text-align: center;
            font-variant-numeric: tabular-nums;
          }}
          .runner-stake {{
            text-align: center;
            font-variant-numeric: tabular-nums;
            color: var(--accent);
          }}
          .ladder-note {{
            margin-top: 8px;
            font-size: 12px;
            color: var(--text-muted);
          }}
          .history-table .hist-result {{
            font-weight: 600;
            letter-spacing: 0.06em;
          }}
          .settings-form {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
            gap: 8px 10px;
            margin-top: 8px;
          }}
          .field-label {{
            display: flex;
            flex-direction: column;
            gap: 3px;
            font-size: 12px;
            color: var(--text-muted);
          }}
          .field-label span {{
            font-size: 11px;
            text-transform: uppercase;
            letter-spacing: 0.08em;
          }}
          .field-label input {{
            border-radius: 999px;
            border: 1px solid var(--border-subtle);
            background: rgba(15, 23, 42, 0.9);
            color: var(--text-main);
            padding: 6px 9px;
            font-size: 13px;
            width: 100%;
          }}
          .field-label input:focus {{
            outline: none;
            border-color: var(--accent);
            box-shadow: 0 0 0 1px rgba(34, 197, 94, 0.6);
          }}
          .settings-footer {{
            margin-top: 10px;
            display: flex;
            flex-direction: column;
            gap: 8px;
          }}
          .profile-row {{
            display: flex;
            flex-wrap: wrap;
            gap: 8px;
            align-items: center;
            justify-content: space-between;
          }}
          .profile-label {{
            font-size: 11px;
            text-transform: uppercase;
            letter-spacing: 0.09em;
            color: var(--text-muted);
          }}
          .profile-buttons {{
            display: flex;
            flex-wrap: wrap;
            gap: 6px;
          }}
          .profile-buttons .btn {{
            padding: 4px 9px;
            font-size: 11px;
          }}
          .muted {{
            color: var(--text-muted);
            font-size: 13px;
          }}
          .message {{
            margin-top: 8px;
            padding: 6px 10px;
            border-radius: 10px;
            background: rgba(34, 197, 94, 0.08);
            border: 1px solid rgba(34, 197, 94, 0.35);
            font-size: 12px;
            color: #bbf7d0;
          }}
          .bank-row {{
            margin-top: 10px;
            margin-bottom: 4px;
          }}
          .bank-card {{
            display: grid;
            grid-template-columns: repeat(4, minmax(0, 1fr));
            gap: 10px;
            border-radius: 14px;
            border: 1px solid var(--border-subtle);
            background: rgba(15, 23, 42, 0.9);
            padding: 9px 10px;
          }}
          @media (max-width: 700px) {{
            .bank-card {{
              grid-template-columns: repeat(2, minmax(0, 1fr));
            }}
          }}
          .bank-metric {{
            display: flex;
            flex-direction: column;
            gap: 2px;
          }}
          .bank-label {{
            font-size: 11px;
            text-transform: uppercase;
            letter-spacing: 0.08em;
            color: var(--text-muted);
          }}
          .bank-value {{
            font-size: 14px;
            font-variant-numeric: tabular-nums;
          }}
          .bank-actions {{
            margin-top: 6px;
            text-align: right;
          }}
          .footer-note {{
            margin-top: 18px;
            font-size: 11px;
            color: var(--text-muted);
          }}
        </style>
      </head>
      <body>
        <div class="shell">
          <div class="card">
            <h1>Betfair Favourites Bot</h1>
            <p class="subtitle">Novice hurdles · 2-favourite dutching · Test / dummy mode</p>

            <div class="top-row">
              <div class="status-block">
                <div class="badges">
                  <span class="chip chip-status">
                    Status: {status}
                  </span>
                  <span class="chip chip-day">
                    Day: {day_status}
                  </span>
                  <span class="chip chip-soft">
                    Exchange: Betfair ({mode_label})
                  </span>
                </div>
                <div class="current-info">
                  {current_info}
                </div>
              </div>

              <div class="controls">
                <form method="post" action="/start_day">
                  <button class="btn btn-primary" type="submit">Start Day</button>
                </form>
                <form method="post" action="/stop">
                  <button class="btn btn-ghost" type="submit">Stop</button>
                </form>
                <form method="post" action="/race_won">
                  <button class="btn btn-ghost" type="submit">Race WON</button>
                </form>
                <form method="post" action="/race_lost">
                  <button class="btn btn-danger" type="submit">Race LOST</button>
                </form>
                <form method="post" action="/logout">
                  <button class="btn btn-ghost" type="submit">Logout</button>
                </form>
              </div>
            </div>

            <div class="bank-row">
              <div class="bank-card">
                <div class="bank-metric">
                  <div class="bank-label">Start bank</div>
                  <div class="bank-value">£{bank_start:.2f}</div>
                </div>
                <div class="bank-metric">
                  <div class="bank-label">Current bank</div>
                  <div class="bank-value">£{bank_now:.2f}</div>
                </div>
                <div class="bank-metric">
                  <div class="bank-label">Today's P/L</div>
                  <div class="bank-value" style="color:{pl_color};">
                    £{pl_today:.2f}
                  </div>
                </div>
                <div class="bank-metric">
                  <div class="bank-label">Betfair balance</div>
                  <div class="bank-value">{bf_balance_display}</div>
                </div>
              </div>
              <div class="bank-actions">
                <form method="post" action="/reset_bank">
                  <button class="btn btn-ghost" type="submit">Reset bank</button>
                </form>
              </div>
            </div>

            {"<div class='message'>" + message + "</div>" if message else ""}

            <div class="grid">
              <div class="panel">
                <div class="section-header">
                  <h2>Today's novice hurdle markets</h2>
                  <span class="chip chip-soft">Exchange data source</span>
                </div>
                <form method="post" action="/update_race_selection">
                  <div class="race-list">
                    {race_list_html}
                  </div>
                  <div class="race-actions">
                    <button class="btn btn-ghost" type="submit">Save race list</button>
                  </div>
                </form>
              </div>

              <div class="panel">
                {ladder_html}
              </div>
            </div>

            <div class="panel" style="margin-top: 18px;">
              <div class="section-header">
                <h2>Settings</h2>
                <span class="chip chip-soft">Risk &amp; banking controls</span>
              </div>
              <form method="post" action="/settings">
                <div class="settings-form">
                  <label class="field-label">
                    <span>Starting bank (£)</span>
                    <input type="text" name="starting_bank" value="{state.current_bank}"/>
                  </label>
                  <label class="field-label">
                    <span>Min favourite odds</span>
                    <input type="text" name="min_fav_odds" value="{state.min_fav_odds}"/>
                  </label>
                  <label class="field-label">
                    <span>Max favourite odds</span>
                    <input type="text" name="max_fav_odds" value="{state.max_fav_odds}"/>
                  </label>
                  <label class="field-label">
                    <span>Target profit per winning race</span>
                    <input type="text" name="target_profit_per_win" value="{state.target_profit_per_win}"/>
                  </label>
                  <label class="field-label">
                    <span>Max daily loss</span>
                    <input type="text" name="max_daily_loss" value="{state.max_daily_loss}"/>
                  </label>
                </div>
                <div class="settings-footer">
                  <button class="btn btn-primary" type="submit">Save settings</button>
                </div>
              </form>

              <form method="post" action="/apply_profile">
                <div class="settings-footer">
                  <div class="profile-row">
                    <div class="profile-label">
                      Quick profiles (profit &amp; daily loss as % of current bank):
                    </div>
                    <div class="profile-buttons">
                      <button class="btn btn-ghost" type="submit" name="profile_pct" value="2">2%</button>
                      <button class="btn btn-ghost" type="submit" name="profile_pct" value="5">5%</button>
                      <button class="btn btn-ghost" type="submit" name="profile_pct" value="10">10%</button>
                      <button class="btn btn-ghost" type="submit" name="profile_pct" value="15">15%</button>
                      <button class="btn btn-ghost" type="submit" name="profile_pct" value="20">20%</button>
                    </div>
                  </div>
                </div>
              </form>
            </div>

            <div class="panel" style="margin-top: 18px;">
              <div class="section-header">
                <h2>Results / history</h2>
                <span class="chip chip-soft">Last 10 races</span>
              </div>
              {history_html}
            </div>

            <p class="footer-note">
              All data is dummy for staking logic only – no real bets are placed by this code.<br/>
              When you plug in the real Betfair API &amp; placeOrders, this UI will control the live bot.
            </p>
          </div>
        </div>
      </body>
    </html>
    """
    return HTMLResponse(content=html)


# ======================
# Routes (all protected)
# ======================

@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    if not is_authenticated(request):
        return RedirectResponse("/login", status_code=303)
    return render_dashboard()


@app.post("/start_day", response_class=HTMLResponse)
async def start_day(request: Request):
    if not is_authenticated(request):
        return RedirectResponse("/login", status_code=303)
    bot.start_day()
    return render_dashboard("Day started. Working through your selected races in order.")


@app.post("/stop", response_class=HTMLResponse)
async def stop_bot(request: Request):
    if not is_authenticated(request):
        return RedirectResponse("/login", status_code=303)
    bot.stop()
    return render_dashboard("Bot stopped.")


@app.post("/race_won", response_class=HTMLResponse)
async def race_won(request: Request):
    if not is_authenticated(request):
        return RedirectResponse("/login", status_code=303)
    bot.on_race_won_manual()
    return render_dashboard("Race marked as WON. Day stopped.")


@app.post("/race_lost", response_class=HTMLResponse)
async def race_lost(request: Request):
    if not is_authenticated(request):
        return RedirectResponse("/login", status_code=303)
    bot.on_race_lost_manual()
    return render_dashboard("Race marked as LOST. Moving on if possible.")


@app.post("/update_race_selection", response_class=HTMLResponse)
async def update_race_selection(
    request: Request,
    market_ids: List[str] = Form(default=[]),
):
    if not is_authenticated(request):
        return RedirectResponse("/login", status_code=303)

    state.selected_market_ids = market_ids
    state.current_index = 0
    strategy.update_current_market(client.get_market_name)
    return render_dashboard("Race list updated.")


@app.post("/settings", response_class=HTMLResponse)
async def update_settings(
    request: Request,
    starting_bank: str = Form(...),
    min_fav_odds: str = Form(...),
    max_fav_odds: str = Form(...),
    target_profit_per_win: str = Form(...),
    max_daily_loss: str = Form(...),
):
    if not is_authenticated(request):
        return RedirectResponse("/login", status_code=303)

    try:
        bank_val = float(starting_bank)
        state.current_bank = bank_val
        state.starting_bank = bank_val

        state.min_fav_odds = float(min_fav_odds)
        state.max_fav_odds = max(state.min_fav_odds, float(max_fav_odds))
        state.target_profit_per_win = max(0.01, float(target_profit_per_win))
        state.max_daily_loss = max(0.01, float(max_daily_loss))
        msg = "Settings updated."
    except Exception as e:
        print("[SETTINGS ERROR]", e)
        msg = "Error updating settings. Please check your values."

    return render_dashboard(msg)


@app.post("/reset_bank", response_class=HTMLResponse)
async def reset_bank(request: Request):
    if not is_authenticated(request):
        return RedirectResponse("/login", status_code=303)

    state.current_bank = state.starting_bank
    state.todays_pl = 0.0
    state.races_played = 0
    state.losses_so_far = 0.0
    state.day_done = False
    bot.stop()
    return render_dashboard("Bank reset to starting value for this session.")


@app.post("/apply_profile", response_class=HTMLResponse)
async def apply_profile(
    request: Request,
    profile_pct: str = Form(...),
):
    if not is_authenticated(request):
        return RedirectResponse("/login", status_code=303)

    try:
        pct = float(profile_pct)
        factor = pct / 100.0
        base = max(state.current_bank, 0.0)

        state.target_profit_per_win = round(base * factor, 2)
        state.max_daily_loss = round(base * factor * 4, 2)

        msg = (
            f"{pct:.0f}% profile applied: "
            f"target profit £{state.target_profit_per_win:.2f}, "
            f"max daily loss £{state.max_daily_loss:.2f}."
        )
    except Exception as e:
        print("[PROFILE ERROR]", e)
        msg = "Error applying profile. Please try again."

    return render_dashboard(msg)


# Optional: redirect GETs on action endpoints back to dashboard (prevents Method Not Allowed JSON)

@app.get("/start_day")
async def start_day_get():
    return RedirectResponse("/", status_code=303)


@app.get("/stop")
async def stop_get():
    return RedirectResponse("/", status_code=303)


@app.get("/race_won")
async def race_won_get():
    return RedirectResponse("/", status_code=303)


@app.get("/race_lost")
async def race_lost_get():
    return RedirectResponse("/", status_code=303)


@app.get("/update_race_selection")
async def update_race_selection_get():
    return RedirectResponse("/", status_code=303)


@app.get("/settings")
async def settings_get():
    return RedirectResponse("/", status_code=303)


@app.get("/reset_bank")
async def reset_bank_get():
    return RedirectResponse("/", status_code=303)


@app.get("/apply_profile")
async def apply_profile_get():
    return RedirectResponse("/", status_code=303)
