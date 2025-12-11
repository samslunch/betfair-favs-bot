# webapp.py
#
# FastAPI dashboard for the Betfair 2-fav dutching bot.
#
# Features:
#   - Login (session based)
#   - Settings: bank, target, stake %, odds range, timing, quick profiles
#   - Live Betfair balance (read-only)
#   - Race selection: today's horse markets from BetfairClient
#   - Bot control: Start / Stop / Race WON / Race LOST
#   - Simple recent P/L history
#   - Debug routes:
#       /inspect_hurdles      -> today's horse markets
#       /inspect_event_types  -> listEventTypes for your account
#
# Depends on:
#   betfair_client.py  (BetfairClient)
#   strategy.py        (StrategyState, BotRunner)
#
# Run locally:
#   uvicorn webapp:app --host 0.0.0.0 --port 8000 --reload

import os
import datetime as dt
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

USE_DUMMY = True

# --------------------------------------------------------
# Global client, strategy state, runner
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
# HTML: Login page
# --------------------------------------------------------

def render_login_page(error: str = "") -> HTMLResponse:
    html = f"""
    <html>
    <head>
        <title>Betfair Bot Login</title>
        <meta name="viewport" content="width=device-width, initial-scale=1" />
        <style>
            * {{ box-sizing: border-box; }}
            body {{
                margin: 0;
                padding: 0;
                font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
                background: radial-gradient(circle at top, #1f2933, #020617 55%);
                color: #e5e7eb;
                min-height: 100vh;
                display: flex;
                align-items: center;
                justify-content: center;
            }}
            .shell {{
                width: 100%;
                padding: 16px;
            }}
            .card {{
                max-width: 380px;
                margin: 0 auto;
                padding: 22px 20px 18px 20px;
                background: rgba(15, 23, 42, 0.96);
                border-radius: 20px;
                border: 1px solid rgba(148, 163, 184, 0.25);
                box-shadow:
                    0 22px 45px rgba(0, 0, 0, 0.7),
                    0 0 0 1px rgba(15, 23, 42, 0.8);
                backdrop-filter: blur(12px);
            }}
            .logo-row {{
                display: flex;
                align-items: center;
                justify-content: center;
                gap: 10px;
                margin-bottom: 4px;
            }}
            .logo-pill {{
                width: 32px;
                height: 32px;
                border-radius: 999px;
                background: radial-gradient(circle at 30% 10%, #22c55e, #15803d);
                display: flex;
                align-items: center;
                justify-content: center;
                font-size: 0.9rem;
                font-weight: 700;
                color: white;
                box-shadow: 0 0 16px rgba(34, 197, 94, 0.7);
            }}
            h1 {{
                margin: 0;
                text-align: center;
                font-size: 1.3rem;
                letter-spacing: 0.03em;
            }}
            .subtitle {{
                margin-top: 4px;
                text-align: center;
                font-size: 0.8rem;
                color: #9ca3af;
            }}
            form {{
                margin-top: 16px;
            }}
            label {{
                display: block;
                font-size: 0.8rem;
                margin-bottom: 4px;
                color: #9ca3af;
            }}
            .field {{
                margin-bottom: 10px;
            }}
            input[type="text"], input[type="password"] {{
                width: 100%;
                padding: 8px 10px;
                border-radius: 10px;
                border: 1px solid #374151;
                background: #020617;
                color: #e5e7eb;
                font-size: 0.9rem;
                outline: none;
            }}
            input[type="text"]:focus, input[type="password"]:focus {{
                border-color: #22c55e;
                box-shadow: 0 0 0 1px rgba(34, 197, 94, 0.4);
            }}
            button {{
                width: 100%;
                padding: 9px;
                margin-top: 4px;
                border-radius: 999px;
                border: none;
                cursor: pointer;
                background: linear-gradient(135deg, #22c55e, #16a34a);
                color: white;
                font-weight: 600;
                font-size: 0.95rem;
                letter-spacing: 0.03em;
                text-transform: uppercase;
            }}
            button:hover {{
                filter: brightness(1.05);
            }}
            .error {{
                color: #f97316;
                font-size: 0.85rem;
                margin-bottom: 8px;
                text-align: center;
            }}
            .footnote {{
                margin-top: 12px;
                text-align: center;
                font-size: 0.75rem;
                color: #6b7280;
            }}
        </style>
    </head>
    <body>
        <div class="shell">
            <div class="card">
                <div class="logo-row">
                    <div class="logo-pill">BF</div>
                    <div style="text-align:left;">
                        <h1>Betfair Favs Bot</h1>
                        <div class="subtitle">2-favourite dutching controller</div>
                    </div>
                </div>
                {"<div class='error'>" + error + "</div>" if error else ""}
                <form method="POST" action="/login">
                    <div class="field">
                        <label for="username">Username</label>
                        <input type="text" name="username" id="username" autocomplete="username" />
                    </div>
                    <div class="field">
                        <label for="password">Password</label>
                        <input type="password" name="password" id="password" autocomplete="current-password" />
                    </div>
                    <button type="submit">Log In</button>
                </form>
                <div class="footnote">
                    VPS: UK • Mode: dashboard only (bets handled on Betfair)
                </div>
            </div>
        </div>
    </body>
    </html>
    """
    return HTMLResponse(html)


# --------------------------------------------------------
# HTML: Dashboard
# --------------------------------------------------------

def render_dashboard(message: str = "") -> HTMLResponse:
    # Betfair account funds
    try:
        funds = client.get_account_funds()
        bf_balance = funds.get("available_to_bet")
    except Exception as e:
        print("[WEBAPP] Error fetching account funds:", e)
        bf_balance = None

    # Markets for today
    try:
        markets = client.get_todays_novice_hurdle_markets()
    except Exception as e:
        print("[WEBAPP] Error fetching markets:", e)
        markets = []

    # Recent history
    recent_history = []
    if hasattr(state, "history") and state.history:
        recent_history = list(state.history)[-10:][::-1]  # newest first

    running = getattr(state, "running", False)
    bank = getattr(state, "bank", 100.0)
    starting_bank = getattr(state, "starting_bank", bank)
    day_pl = bank - starting_bank

    selected_ids = set(getattr(state, "selected_markets", []))

    # 🔥 NOTE: this MUST be an f-string (f"""...""") so {bank:.2f}, {day_pl:.2f}, etc get filled in
    html = f"""
    <html>
    <head>
        <title>Betfair 2-Fav Dutching Bot</title>
        <meta name="viewport" content="width=device-width, initial-scale=1" />
        <style>
            * {{ box-sizing: border-box; }}
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
            a:hover {{ text-decoration: underline; }}
            .page {{
                max-width: 1200px;
                margin: 0 auto;
                padding: 14px;
            }}
            .top-bar {{
                display: flex;
                justify-content: space-between;
                align-items: center;
                gap: 8px;
                margin-bottom: 12px;
            }}
            @media (max-width: 700px) {{
                .top-bar {{
                    flex-direction: column;
                    align-items: flex-start;
                }}
            }}
            h1 {{
                margin: 0;
                font-size: 1.4rem;
            }}
            .sub {{
                font-size: 0.8rem;
                color: #9ca3af;
            }}
            .pill {{
                border-radius: 999px;
                padding: 3px 8px;
                font-size: 0.75rem;
                display: inline-flex;
                align-items: center;
                gap: 4px;
            }}
            .pill.green {{
                background: rgba(34,197,94,0.1);
                border: 1px solid rgba(34,197,94,0.3);
                color: #4ade80;
            }}
            .pill.red {{
                background: rgba(248,113,113,0.1);
                border: 1px solid rgba(248,113,113,0.3);
                color: #fca5a5;
            }}
            .grid {{
                display: grid;
                grid-template-columns: 1.1fr 1fr;
                gap: 14px;
            }}
            @media (max-width: 900px) {{
                .grid {{
                    grid-template-columns: 1fr;
                }}
            }}
            .card {{
                background: #020617;
                border-radius: 16px;
                border: 1px solid #1f2937;
                padding: 12px 14px;
                box-shadow: 0 20px 25px -5px rgba(0,0,0,0.4);
            }}
            .card h2 {{
                margin: 0 0 8px 0;
                font-size: 1rem;
            }}
            .card h3 {{
                margin: 8px 0 6px 0;
                font-size: 0.95rem;
            }}
            label {{
                display: block;
                font-size: 0.8rem;
                margin-bottom: 3px;
                color: #9ca3af;
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
                min-width: 130px;
            }}
            .btn {{
                border-radius: 999px;
                padding: 6px 12px;
                border: none;
                cursor: pointer;
                font-size: 0.8rem;
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
            .message {{
                font-size: 0.8rem;
                color: #f97316;
                margin-bottom: 6px;
            }}
            .green-text {{ color: #4ade80; }}
            .red-text {{ color: #fca5a5; }}
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
            }}
            .history-table tr:last-child td {{
                border-bottom: none;
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
                        <a href="/logout">Log out</a> |
                        <a href="/inspect_hurdles">Inspect Hurdles</a>
                    </div>
                </div>
                <div style="text-align:right;">
                    <div class="pill {'green' if running else 'red'}">
                        <span style="font-size:0.65rem;">●</span>
                        {"Running" if running else "Stopped"}
                    </div><br/>
                    <span class="sub">
                        Mode: {"DUMMY" if USE_DUMMY else "LIVE READ-ONLY (no bets placed)"}
                    </span>
                </div>
            </div>

            {"<div class='message'>" + message + "</div>" if message else ""}

            <div class="grid">
                <!-- LEFT: settings + races -->
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
                                <label for="target_profit">Target profit for day (£)</label>
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
                    <div class="sub" style="margin-bottom:6px;">
                        From Betfair (horse racing, relaxed filter – novice hurdles preferred).
                    </div>
    """

    if not markets:
        html += """
                    <p style="color:#f97316;font-size:0.8rem;">
                        No markets returned by Betfair. Check API / filters.
                    </p>
        """

    html += """
                    <form method="POST" action="/update_race_selection">
                        <div style="max-height:260px; overflow-y:auto; border-radius:8px;
                                    border:1px solid #1f2937; padding:8px;">
    """

    # Race checkboxes
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
                            <button type="submit" class="btn btn-secondary btn-small">
                                Save race selection
                            </button>
                        </div>
                    </form>
                </div>

                <!-- RIGHT: status, controls, history -->
                <div class="card">
                    <h2>Status & Controls</h2>
                    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">
                        <div>
                            <div class="sub">Current bank</div>
                            <div style="font-size:1.2rem;">£{bank:.2f}</div>
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
                        <button type="submit" class="btn btn-primary">▶ Start Bot</button>
                    </form>
                    <form method="POST" action="/stop" style="margin-top:6px;">
                        <button type="submit" class="btn btn-danger">■ Stop Bot</button>
                    </form>

                    <div style="margin-top:12px;">
                        <span class="sub">Manual race outcome (until auto-result is wired in):</span><br/>
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
                            <th>Stake</th>
                            <th>P/L</th>
                        </tr>
    """

    if recent_history:
        for idx, row in enumerate(recent_history, 1):
            race_name = row.get("race_name", "?")
            favs = row.get("favs", "Top 2 favourites")
            stake = row.get("total_stake", 0.0)
            pl = row.get("pl", 0.0)
            cls = "green-text" if pl >= 0 else "red-text"
            html += f"""
                        <tr>
                            <td>{idx}</td>
                            <td>{race_name}</td>
                            <td>{favs}</td>
                            <td>£{stake:.2f}</td>
                            <td class="{cls}">£{pl:.2f}</td>
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
# Routes: auth
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


# --------------------------------------------------------
# Routes: main dashboard
# --------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    redirect = require_login(request)
    if redirect:
        return redirect
    return render_dashboard()


# --------------------------------------------------------
# Routes: settings & race selection
# --------------------------------------------------------

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
    state.current_index = 0  # reset sequence when user changes selection
    print("[WEBAPP] User selected markets:", selected)

    return render_dashboard("Race selection updated.")


# --------------------------------------------------------
# Routes: bot control
# --------------------------------------------------------

@app.post("/start")
async def start_bot(request: Request):
    redirect = require_login(request)
    if redirect:
        return redirect

    if not state.selected_markets:
        return render_dashboard("No races selected – tick at least one race and save.")

    try:
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

    try:
        runner.mark_race_won()
    except Exception as e:
        print("[WEBAPP] Error marking race as won:", e)
        return render_dashboard(f"Error marking race as WON: {e}")

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
        return render_dashboard(f"Error marking race as LOST: {e}")

    return render_dashboard("Race marked as LOST.")


# --------------------------------------------------------
# Debug route: inspect today's horse markets & novice hurdles
# --------------------------------------------------------

@app.get("/inspect_hurdles", response_class=HTMLResponse)
async def inspect_hurdles(request: Request):
    redirect = require_login(request)
    if redirect:
        return redirect

    today_utc = dt.datetime.utcnow().date()
    html_parts = []
    html_parts.append("<html><head><title>Inspect Hurdles</title></head><body>")
    html_parts.append(f"<h2>Horse markets for today (UTC date = {today_utc})</h2>")
    html_parts.append("<p>This debug view shows exactly how Betfair names today's horse races.</p>")
    html_parts.append("<p><a href='/'>Back to dashboard</a></p>")

    if client.use_dummy:
        html_parts.append("<p style='color:orange;'>Client is in DUMMY mode - switch to live to see real markets.</p>")
        html_parts.append("</body></html>")
        return HTMLResponse("".join(html_parts))

    params = {
        "filter": {"eventTypeIds": ["7"]},  # Horse Racing
        "maxResults": 200,
        "marketProjection": ["MARKET_START_TIME", "EVENT"],
    }

    try:
        result = client._rpc("listMarketCatalogue", params)
    except Exception as e:
        html_parts.append(f"<p style='color:red;'>Error calling listMarketCatalogue: {e}</p>")
        html_parts.append("</body></html>")
        return HTMLResponse("".join(html_parts))

    html_parts.append(f"<p>Betfair returned <strong>{len(result)}</strong> horse markets total.</p>")

    rows = []
    idx_today = 0

    for m in result:
        market_id = m.get("marketId")
        market_name = m.get("marketName", "")
        event = m.get("event", {}) or {}
        event_name = event.get("name", "")
        venue = event.get("venue", "")
        open_date_str = event.get("openDate", "")

        # Parse date -> filter to today (UTC)
        event_date = None
        if open_date_str:
            try:
                s = open_date_str
                if s.endswith("Z"):
                    s = s.replace("Z", "+00:00")
                dt_val = dt.datetime.fromisoformat(s)
                event_date = dt_val.date()
            except Exception:
                event_date = None

        if event_date != today_utc:
            continue

        idx_today += 1
        lower_name = market_name.lower()

        tags = []
        if any(x in lower_name for x in ["hurdle", "hurd", "hrd"]):
            tags.append("HURDLE")
        if any(x in lower_name for x in ["novice", "nov ", "nov.", "nov hrd", "nov hdl", "nov hcap"]):
            tags.append("NOVICE?")

        tag_str = " | ".join(tags) if tags else ""
        rows.append((market_id, event_name, venue, market_name, tag_str))

    if idx_today == 0:
        html_parts.append("<p style='color:orange;'>No horse markets with openDate == today (UTC) found.</p>")
        html_parts.append("</body></html>")
        return HTMLResponse("".join(html_parts))

    html_parts.append(f"<p>Showing <strong>{idx_today}</strong> horse markets whose event date is today (UTC).</p>")
    html_parts.append("""
        <table border="1" cellspacing="0" cellpadding="4" style="font-size:0.8rem;">
            <tr>
                <th>#</th>
                <th>Tags</th>
                <th>MarketId</th>
                <th>Event</th>
                <th>Venue</th>
                <th>Market Name</th>
            </tr>
    """)

    for idx, (market_id, event_name, venue, market_name, tag_str) in enumerate(rows, 1):
        tag_html = f"<span style='color:#f97316;'>{tag_str}</span>" if tag_str else ""
        html_parts.append(f"""
            <tr>
                <td>{idx}</td>
                <td>{tag_html}</td>
                <td>{market_id}</td>
                <td>{event_name}</td>
                <td>{venue}</td>
                <td>{market_name}</td>
            </tr>
        """)

    html_parts.append("</table></body></html>")
    return HTMLResponse("".join(html_parts))


# --------------------------------------------------------
# Debug route: inspect available event types from Betfair
# --------------------------------------------------------

@app.get("/inspect_event_types", response_class=HTMLResponse)
async def inspect_event_types(request: Request):
    redirect = require_login(request)
    if redirect:
        return redirect

    html_parts = []
    html_parts.append("<html><head><title>Inspect Event Types</title></head><body>")
    html_parts.append("<h2>Betfair Event Types (what your account can see)</h2>")
    html_parts.append("<p><a href='/'>Back to dashboard</a></p>")

    if client.use_dummy:
        html_parts.append(
            "<p style='color:orange;'>Client is in DUMMY mode - switch to live mode to see real data.</p>"
        )
        html_parts.append("</body></html>")
        return HTMLResponse("".join(html_parts))

    params = {"filter": {}}

    try:
        result = client._rpc("listEventTypes", params)
    except Exception as e:
        html_parts.append(f"<p style='color:red;'>Error calling listEventTypes: {e}</p>")
        html_parts.append("</body></html>")
        return HTMLResponse("".join(html_parts))

    html_parts.append(f"<p>Betfair returned {len(result)} event types.</p>")
    html_parts.append("""
        <table border="1" cellspacing="0" cellpadding="4" style="font-size:0.8rem;">
            <tr>
                <th>#</th>
                <th>EventTypeId</th>
                <th>Name</th>
                <th>MarketCount</th>
            </tr>
    """)

    for idx, item in enumerate(result, 1):
        et = item.get("eventType", {}) or {}
        et_id = et.get("id", "?")
        et_name = et.get("name", "?")
        market_count = item.get("marketCount", 0)

        html_parts.append(f"""
            <tr>
                <td>{idx}</td>
                <td>{et_id}</td>
                <td>{et_name}</td>
                <td>{market_count}</td>
            </tr>
        """)

    html_parts.append("</table></body></html>")
    return HTMLResponse("".join(html_parts))


# --------------------------------------------------------
# Local dev entrypoint
# --------------------------------------------------------

if __name__ == "__main__":
    import uvicorn

    uvicorn.run("webapp:app", host="0.0.0.0", port=8000, reload=True)
