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
# - Mobile-friendly layout
# - 1 minute before off: auto-timing (SIMULATED – logs only, no placeOrders)

import threading
import time
from typing import List
from datetime import datetime, timezone

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
    Background bot loop.
    Now:
      - Watches the current market's start time.
      - When 0 < seconds_to_off <= 60 and no bet placed yet,
        it computes the dutch stakes and LOGS what it would do.
      - Still NO REAL BETS are placed.
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
        if not state.current_market_id:
            print("[BOT] Race WON pressed but no current market.")
            return
        pnl = max(state.last_total_stake, 0.0)
        self.strategy.on_market_won(pnl=pnl)
        state.bet_placed_for_current = False
        state.current_market_start = None
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
        print("[BOT] Loop started (auto-timing simulated bets; no real orders).")
        while True:
            try:
                if self.running and not state.day_done and state.current_market_id:
                    # Ensure we know the market start time
                    if state.current_market_start is None:
                        try:
                            state.current_market_start = self.client.get_market_start_time(
                                state.current_market_id
                            )
                            print(
                                f"[BOT] Start time for {state.current_market_name}: "
                                f"{state.current_market_start}"
                            )
                        except Exception as e:
                            print("[BOT] Error getting market start time:", e)
                            time.sleep(10)
                            continue

                    now = datetime.now(timezone.utc)
                    secs_to_off = (state.current_market_start - now).total_seconds()

                    # 1 minute before off window
                    if 0 < secs_to_off <= 60 and not state.bet_placed_for_current:
                        favs = self.client.get_top_two_favourites(state.current_market_id)
                        if len(favs) == 2:
                            o1 = favs[0]["back"]
                            o2 = favs[1]["back"]
                            s1, s2, total, profit = self.strategy.compute_dutch_for_current(o1, o2)
                            if total > 0:
                                print(
                                    "[BOT] [SIMULATED] 1 minute before off.\n"
                                    f"  Market: {state.current_market_name}\n"
                                    f"  Favs: {favs[0]['name']} @ {o1}, {favs[1]['name']} @ {o2}\n"
                                    f"  Stakes: s1={s1:.2f}, s2={s2:.2f}, total={total:.2f}\n"
                                    f"  Expected profit if either wins: {profit:.2f}\n"
                                    "  (No real placeOrders sent yet.)"
                                )
                                state.bet_placed_for_current = True
                            else:
                                print("[BOT] Computed zero total stake, skipping simulated bet.")
                        else:
                            print("[BOT] Could not find 2 favourites to dutch for current market.")

                time.sleep(5)
            except Exception as e:
                print("[BOT] Error in loop:", e)
                time.sleep(5)


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
            --bg-elevated: rgba(15, 42, 73, 0.9);
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
# Dashboard renderer (same as before, trimmed here)
# ======================

# ⬇️ For brevity I’m not re-pasting the whole render_dashboard again,
# but you can keep the one you already have – it doesn’t need changing
# for the 1-minute timing logic. If you want the full combined file,
# I can dump the entire render_dashboard+CSS block again.

# IMPORTANT: keep the rest of your webapp.py (render_dashboard, routes)
# exactly as you have it; only BotRunner and imports needed timing changes.

# If you’d like I can re-send the *full* webapp.py you’re currently using
# with this timing logic merged in – just say and I’ll paste the whole file.
