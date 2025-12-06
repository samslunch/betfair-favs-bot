# webapp.py
#
# FastAPI web UI for the Betfair bot.
# - Secure login (session-based)
# - Dashboard with:
#     * Bank & staking controls
#     * Quick profiles (2%, 5%, 10%, 15%, 20%)
#     * Live Betfair balance
#     * Race selection (today's horse markets via BetfairClient)
#     * Bot control: Start / Stop / Race Won / Race Lost
#     * Simple P/L history panel
#
# Assumes:
#   - betfair_client.py defines BetfairClient
#   - strategy.py defines StrategyState and BotRunner
#
# Env vars:
#   SESSION_SECRET            -> session key (required in production)
#   ADMIN_USERNAME            -> login username (defaults: "adamhill")
#   ADMIN_PASSWORD            -> login password (defaults: "Adamhillonline1!")
#   BETFAIR_DUMMY             -> "true"/"false" to use dummy mode
#   BETFAIR_APP_KEY, BETFAIR_USERNAME, BETFAIR_PASSWORD for live mode

import os
import asyncio
from typing import Optional

from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from starlette.middleware.sessions import SessionMiddleware

from betfair_client import BetfairClient
from strategy import StrategyState, BotRunner

# --------------------------------------------------------
# App & middleware
# --------------------------------------------------------

app = FastAPI()

SESSION_SECRET = os.getenv("SESSION_SECRET", "dev-secret-change-me")
app.add_middleware(SessionMiddleware, secret_key=SESSION_SECRET)

ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "adamhill")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "Adamhillonline1!")

USE_DUMMY = os.getenv("BETFAIR_DUMMY", "false").lower() == "true"

# --------------------------------------------------------
# Global client, strategy state, bot runner
# --------------------------------------------------------

client = BetfairClient(use_dummy=USE_DUMMY)
state = StrategyState()
runner = BotRunner(client=client, state=state)


# --------------------------------------------------------
# Auth helpers
# --------------------------------------------------------

def is_logged_in(request: Request) -> bool:
    return request.session.get("user") == "admin"


def require_login(request: Request) -> Optional[RedirectResponse]:
    if not is_logged_in(request):
        return RedirectResponse("/login", status_code=303)
    return None


# --------------------------------------------------------
# HTML rendering helpers
# --------------------------------------------------------

def render_login_page(error: str = "") -> HTMLResponse:
    html = f"""
    <html>
    <head>
        <title>Betfair Bot Login</title>
        <meta name="viewport" content="width=device-width, initial-scale=1" />
        <style>
            body {{
                font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
                background: #0b1220;
                color: #e5e7eb;
                margin: 0;
                padding: 0;
            }}
            .container {{
                max-width: 400px;
                margin: 80px auto;
                padding: 24px;
                background: #020617;
                border-radius: 12px;
                box-shadow: 0 20px 25px -5px rgba(0,0,0,0.5);
                border: 1px solid #1f2937;
            }}
            h1 {{
                margin-top: 0;
                font-size: 1.6rem;
                text-align: center;
            }}
            label {{
                display: block;
                margin-bottom: 4px;
                font-size: 0.9rem;
                color: #9ca3af;
            }}
            input[type="text"], input[type="password"] {{
                width: 100%;
                padding: 10px;
                margin-bottom: 12px;
                border-radius: 8px;
                border: 1px solid #374151;
                background: #020617;
                color: #e5e7eb;
            }}
            button {{
                width: 100%;
                padding: 10px;
                border-radius: 999px;
                border: none;
                background: linear-gradient(135deg, #22c55e, #16a34a);
                color: white;
                font-weight: 600;
                cursor: pointer;
            }}
            button:hover {{
                opacity: 0.9;
            }}
            .error {{
                color: #f97316;
                margin-bottom: 10px;
                font-size: 0.9rem;
                text-align: center;
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <h1>Betfair Bot Login</h1>
            {"<div class='error'>" + error + "</div>" if error else ""}
            <form method="POST" action="/login">
                <label for="username">Username</label>
                <input type="text" name="username" id="username" />

                <label for="password">Password</label>
                <input type="password" name="password" id="password" />

                <button type="submit">Log In</button>
            </form>
        </div>
    </body>
    </html>
    """
    return HTMLResponse(html)


def render_dashboard(message: str = "") -> HTMLResponse:
    # Fetch Betfair funds (safe)
    try:
        funds = client.get_account_funds()
        bf_balance = funds.get("available_to_bet")
    except Exception as e:
        print("[WEBAPP] Error fetching account funds:", e)
        bf_balance = None

    # Fetch markets for today (relaxed)
    try:
        markets = client.get_todays_novice_hurdle_markets()
    except Exception as e:
        print("[WEBAPP] Error fetching markets:", e)
        markets = []

    # Recent history view
    recent_history = []
    if hasattr(state, "history") and state.history:
        # Assuming state.history is a list of dicts
        recent_history = list(state.history)[-10:][::-1]  # newest first

    # Whether bot is running
    running = getattr(state, "running", False)

    # HTML
    html = f"""
    <html>
    <head>
        <title>Betfair 2-Fav Dutching Bot</title>
        <meta name="viewport" content="width=device-width, initial-scale=1" />
        <style>
            * {{
                box-sizing: border-box;
            }}
            body {{
                margin: 0;
                font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
                background: #020617;
                color: #e5e7eb;
            }}
            a {{
                color: #38bdf8;
                text-decoration: none;
            }}
            a:hover {{
                text-decoration: underline;
            }}
            .page {{
                max-width: 1200px;
                margin: 0 auto;
                padding: 16px;
            }}
            .top-bar {{
                display: flex;
                justify-content: space-between;
                align-items: center;
                margin-bottom: 16px;
                gap: 8px;
            }}
            .top-bar h1 {{
                font-size: 1.4rem;
                margin: 0;
            }}
            .pill {{
                border-radius: 999px;
                padding: 4px 10px;
                font-size: 0.75rem;
                display: inline-flex;
                align-items: center;
                gap: 4px;
            }}
            .pill.green {{
                background: rgba(34,197,94,0.12);
                color: #4ade80;
                border: 1px solid rgba(34,197,94,0.3);
            }}
            .pill.red {{
                background: rgba(248,113,113,0.12);
                color: #fca5a5;
                border: 1px solid rgba(248,113,113,0.3);
            }}
            .pill.blue {{
                background: rgba(59,130,246,0.12);
                color: #93c5fd;
                border: 1px solid rgba(59,130,246,0.3);
            }}
            .grid {{
                display: grid;
                grid-template-columns: 1.1fr 1fr;
                gap: 16px;
            }}
            @media (max-width: 900px) {{
                .grid {{
                    grid-template-columns: 1fr;
                }}
            }}
            .card {{
                background: #020617;
                border-radius: 16px;
                padding: 14px 16px;
                border: 1px solid #1f2937;
                box-shadow: 0 20px 25px -5px rgba(0,0,0,0.4);
            }}
            .card h2 {{
                margin: 0 0 8px 0;
                font-size: 1rem;
            }}
            .card h3 {{
                margin: 6px 0 6px 0;
                font-size: 0.95rem;
                color: #e5e7eb;
            }}
            .sub {{
                font-size: 0.8rem;
                color: #9ca3af;
            }}
            label {{
                font-size: 0.8rem;
                color: #9ca3af;
                display: block;
                margin-bottom: 3px;
            }}
            input[type="number"], input[type="text"] {{
                width: 100%;
                padding: 6px 8px;
                border-radius: 8px;
                border: 1px solid #374151;
                background: #020617;
                color: #e5e7eb;
                font-size: 0.85rem;
            }}
            .row {{
                display: flex;
                flex-wrap: wrap;
                gap: 8px;
            }}
            .row > div {{
                flex: 1;
                min-width: 120px;
            }}
            .btn {{
                border-radius: 999px;
                padding: 6px 12px;
                border: none;
                cursor: pointer;
                font-size: 0.85rem;
                font-weight: 600;
                display: inline-flex;
                align-items: center;
                gap: 6px;
            }}
            .btn-primary {{
                background: linear-gradient(135deg, #22c55e, #16a34a);
                color: white;
            }}
            .btn-secondary {{
                background: #0f172a;
                color: #e5e7eb;
                border: 1px solid #374151;
            }}
            .btn-danger {{
                background: #b91c1c;
                color: white;
            }}
            .btn-small {{
                padding: 4px 10px;
                font-size: 0.75rem;
            }}
            .btn + .btn {{
                margin-left: 6px;
            }}
            .badge {{
                font-size: 0.75rem;
                padding: 2px 8px;
                border-radius: 999px;
                background: #0f172a;
                border: 1px solid #374151;
                color: #9ca3af;
            }}
            .message {{
                margin-bottom: 8px;
                font-size: 0.85rem;
                color: #f97316;
            }}
            .history-table {{
                width: 100%;
                border-collapse: collapse;
                font-size: 0.8rem;
            }}
            .history-table th, .history-table td {{
                padding: 4px 6px;
                border-bottom: 1px solid #1f2937;
            }}
            .history-table th {{
                text-align: left;
                color: #9ca3af;
                font-weight: 500;
            }}
            .history-table tr:last-child td {{
                border-bottom: none;
            }}
            .green-text {{
                color: #4ade80;
            }}
            .red-text {{
                color: #fca5a5;
            }}
        </style>
    </head>
    <body>
        <div class="page">
            <div class="top-bar">
                <div>
                    <h1>Betfair 2-Fav Dutching Bot</h1>
                    <div class="sub">
                        Logged in as <strong>{ADMIN_USERNAME}</strong> |
                        <a href="/logout">Log out</a>
                    </div>
                </div>
                <div style="text-align:right;">
                    <div class="pill {'green' if running else 'red'}">
                        <span style="font-size:0.65rem;">●</span>
                        {"Running" if running else "Stopped"}
                    </div><br/>
                    <span class="sub">
                        Mode: {"DUMMY" if USE_DUMMY else "LIVE READ-ONLY (no placeOrders yet)"}
                    </span>
                </div>
            </div>

            {"<div class='message'>" + message + "</div>" if message else ""}

            <div class="grid">
                <!-- LEFT COLUMN: SETTINGS + RACES -->
                <div class="card">
                    <h2>Bank, Staking & Races</h2>

                    <form method="POST" action="/update_settings">
                        <div class="row">
                            <div>
                                <label for="starting_bank">Starting bank (£)</label>
                                <input type="number" step="0.01" name="starting_bank" id="starting_bank"
                                    value="{getattr(state, 'starting_bank', 100.0)}" />
                            </div>
                            <div>
                                <label for="current_bank">Current bank (£)</label>
                                <input type="number" step="0.01" name="current_bank" id="current_bank"
                                    value="{getattr(state, 'bank', 100.0)}" />
                            </div>
                        </div>

                        <div class="row" style="margin-top:8px;">
                            <div>
                                <label for="target_profit">Target profit for the day (£)</label>
                                <input type="number" step="0.01" name="target_profit" id="target_profit"
                                    value="{getattr(state, 'target_profit', 5.0)}" />
                            </div>
                            <div>
                                <label for="stake_percent">Stake % of bank per race</label>
                                <input type="number" step="0.1" name="stake_percent" id="stake_percent"
                                    value="{getattr(state, 'stake_percent', 5.0)}" />
                            </div>
                        </div>

                        <div class="row" style="margin-top:8px;">
                            <div>
                                <label for="min_odds">Min odds (fav)</label>
                                <input type="number" step="0.01" name="min_odds" id="min_odds"
                                    value="{getattr(state, 'min_odds', 1.5)}" />
                            </div>
                            <div>
                                <label for="max_odds">Max odds (fav)</label>
                                <input type="number" step="0.01" name="max_odds" id="max_odds"
                                    value="{getattr(state, 'max_odds', 4.5)}" />
                            </div>
                        </div>

                        <div class="row" style="margin-top:8px;">
                            <div>
                                <label for="seconds_before_off">Place bets (seconds before off)</label>
                                <input type="number" step="1" name="seconds_before_off" id="seconds_before_off"
                                    value="{getattr(state, 'seconds_before_off', 60)}" />
                            </div>
                        </div>

                        <div style="margin-top:10px;">
                            <span class="sub">Quick stake profiles (% of bank):</span><br/>
                            <button class="btn btn-secondary btn-small" name="profile" value="2">2%</button>
                            <button class="btn btn-secondary btn-small" name="profile" value="5">5%</button>
                            <button class="btn btn-secondary btn-small" name="profile" value="10">10%</button>
                            <button class="btn btn-secondary btn-small" name="profile" value="15">15%</button>
                            <button class="btn btn-secondary btn-small" name="profile" value="20">20%</button>
                        </div>

                        <div style="margin-top:10px;">
                            <button type="submit" class="btn btn-primary">Save settings</button>
                            <button type="submit" name="reset_bank" value="1" class="btn btn-secondary">
                                Reset bank to starting
                            </button>
                        </div>
                    </form>

                    <hr style="border-color:#1f2937; margin:14px 0;" />

                    <h3>Available Races Today</h3>
                    <div class="sub" style="margin-bottom:8px;">
                        Pulled from Betfair (super-relaxed horse racing filter).
                    </div>
                    {"<p style='color:#f97316;font-size:0.8rem;'>No markets returned by Betfair.</p>" if not markets else ""}

                    <form method="POST" action="/update_race_selection">
                        <div style="max-height:250px; overflow-y:auto; border-radius:8px; border:1px solid #1f2937; padding:8px;">
    """

    # Race checkboxes
    selected_ids = set(getattr(state, "selected_markets", []))
    if markets:
        for m in markets:
            mid = m["market_id"]
            name = m["name"]
            checked = "checked" if mid in selected_ids else ""
            html += f"""
                <label style="display:flex;align-items:center;gap:6px;font-size:0.8rem;padding:2px 0;">
                    <input type="checkbox" name="selected_markets" value="{mid}" {checked} />
                    <span>{name}</span>
                </label>
            """

    html += """
                        </div>
                        <div style="margin-top:8px;">
                            <button type="submit" class="btn btn-secondary btn-small">Save race selection</button>
                        </div>
                    </form>
                </div>

                <!-- RIGHT COLUMN: STATUS + CONTROL + HISTORY -->
                <div class="card">
                    <h2>Status & Controls</h2>
    """

    # Bank & P/L status
    bank = getattr(state, "bank", 100.0)
    start_bank = getattr(state, "starting_bank", bank)
    day_pl = bank - start_bank

    html += f"""
                    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">
                        <div>
                            <div class="sub">Current bank</div>
                            <div style="font-size:1.3rem;">£{bank:.2f}</div>
                        </div>
                        <div>
                            <div class="sub">Day P/L</div>
                            <div class="{ 'green-text' if day_pl >= 0 else 'red-text' }">
                                £{day_pl:.2f}
                            </div>
                        </div>
                        <div>
                            <div class="sub">Betfair balance</div>
                            <div style="font-size:0.9rem;">
                                {"£" + f"{bf_balance:.2f}" if bf_balance is not None else "–"}
                            </div>
                        </div>
                    </div>

                    <form method="POST" action="/start">
                        <button type="submit" class="btn btn-primary">
                            ▶ Start Bot
                        </button>
                    </form>

                    <form method="POST" action="/stop" style="margin-top:6px;">
                        <button type="submit" class="btn btn-danger">
                            ■ Stop Bot
                        </button>
                    </form>

                    <div style="margin-top:12px;">
                        <span class="sub">Manual race outcome control (still required while no auto-result):</span><br/>
                        <form method="POST" action="/race_won" style="display:inline;">
                            <button type="submit" class="btn btn-secondary btn-small">Race WON</button>
                        </form>
                        <form method="POST" action="/race_lost" style="display:inline;">
                            <button type="submit" class="btn btn-secondary btn-small">Race LOST</button>
                        </form>
                    </div>

                    <hr style="border-color:#1f2937; margin:14px 0;" />

                    <h3>Recent Races & P/L</h3>
                    <table class="history-table">
                        <tr>
                            <th>#</th>
                            <th>Race</th>
                            <th>Favourites</th>
                            <th>Stakes</th>
                            <th>P/L</th>
                        </tr>
    """

    if recent_history:
        for idx, row in enumerate(recent_history, 1):
            race_name = row.get("race_name", "?")
            favs = row.get("favs", "")
            stake = row.get("total_stake", 0.0)
            pl = row.get("pl", 0.0)
            pl_class = "green-text" if pl >= 0 else "red-text"
            html += f"""
                        <tr>
                            <td>{idx}</td>
                            <td>{race_name}</td>
                            <td>{favs}</td>
                            <td>£{stake:.2f}</td>
                            <td class="{pl_class}">£{pl:.2f}</td>
                        </tr>
            """
    else:
        html += """
                        <tr>
                            <td colspan="5" class="sub">No races yet.</td>
                        </tr>
        """

    html += """
                    </table>
                </div>
            </div>
        </div>
    </body>
    </html>
    """

    return HTMLResponse(html)


# --------------------------------------------------------
# Routes
# --------------------------------------------------------

@app.get("/login")
async def login_get(request: Request):
    if is_logged_in(request):
        return RedirectResponse("/", status_code=303)
    return render_login_page()


@app.post("/login")
async def login_post(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
):
    if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
        request.session["user"] = "admin"
        return RedirectResponse("/", status_code=303)
    else:
        return render_login_page("Invalid username or password.")


@app.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)


@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    redirect = require_login(request)
    if redirect:
        return redirect
    return render_dashboard()


# ---------------- SETTINGS + RACE SELECTION ----------------

@app.post("/update_settings")
async def update_settings(
    request: Request,
    starting_bank: float = Form(...),
    current_bank: float = Form(...),
    target_profit: float = Form(...),
    stake_percent: float = Form(...),
    min_odds: float = Form(...),
    max_odds: float = Form(...),
    seconds_before_off: int = Form(...),
    profile: str = Form(None),
    reset_bank: str = Form(None),
):
    redirect = require_login(request)
    if redirect:
        return redirect

    # Update base settings
    state.starting_bank = starting_bank

    if reset_bank:
        state.bank = starting_bank
    else:
        state.bank = current_bank

    state.target_profit = target_profit
    state.min_odds = min_odds
    state.max_odds = max_odds
    state.seconds_before_off = seconds_before_off

    # Quick profiles override stake_percent if chosen
    if profile in ("2", "5", "10", "15", "20"):
        state.stake_percent = float(profile)
    else:
        state.stake_percent = stake_percent

    return render_dashboard("Settings saved.")


@app.post("/update_race_selection")
async def update_race_selection(request: Request):
    redirect = require_login(request)
    if redirect:
        return redirect

    form = await request.form()
    selected = form.getlist("selected_markets")
    state.selected_markets = selected
    print("[WEBAPP] User selected markets:", selected)

    return render_dashboard("Race selection updated.")


# ---------------- BOT CONTROL ----------------

@app.post("/start")
async def start_bot(request: Request):
    redirect = require_login(request)
    if redirect:
        return redirect

    if not getattr(state, "selected_markets", []):
        return render_dashboard("No races selected – select at least one race before starting.")

    # Start the bot runner (non-blocking)
    try:
        # BotRunner is assumed to manage its own background task/thread.
        runner.start()
    except Exception as e:
        print("[WEBAPP] Error starting bot:", e)
        return render_dashboard(f"Error starting bot: {e}")

    return render_dashboard("Bot started.")


@app.post("/stop")
async def stop_bot(request: Request):
    redirect = require_login(request)
    if redirect:
        return redirect

    try:
        runner.stop()
    except Exception as e:
        print("[WEBAPP] Error stopping bot:", e)
        return render_dashboard(f"Error stopping bot: {e}")

    return render_dashboard("Bot stopped.")


@app.post("/race_won")
async def race_won(request: Request):
    redirect = require_login(request)
    if redirect:
        return redirect

    # Strategy/BotRunner should interpret this appropriately.
    try:
        runner.mark_race_won()
    except Exception as e:
        print("[WEBAPP] Error marking race as won:", e)
        return render_dashboard(f"Error marking race as won: {e}")

    return render_dashboard("Race marked as WON.")


@app.post("/race_lost")
async def race_lost(request: Request):
    redirect = require_login(request)
    if redirect:
        return redirect

    try:
        runner.mark_race_lost()
    except Exception as e:
        print("[WEBAPP] Error marking race as lost:", e)
        return render_dashboard(f"Error marking race as lost: {e}")

    return render_dashboard("Race marked as LOST.")


# --------------------------------------------------------
# Local dev entrypoint (optional)
# --------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("webapp:app", host="0.0.0.0", port=8000, reload=True)
