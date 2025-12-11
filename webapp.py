# webapp.py
# FastAPI dashboard for Betfair 2-fav dutching bot
# SAFE VERSION – no import-time Betfair login, no syntax errors

import os
import datetime as dt
from typing import Optional

from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from starlette.middleware.sessions import SessionMiddleware

from betfair_client import BetfairClient
from strategy import StrategyState, BotRunner

# ------------------------------------------------------------
# App setup
# ------------------------------------------------------------

app = FastAPI()

SESSION_SECRET = os.getenv("SESSION_SECRET", "dev-secret")
app.add_middleware(SessionMiddleware, secret_key=SESSION_SECRET)

ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "adamhill")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "Adamhillonline1!")

USE_DUMMY = os.getenv("BETFAIR_DUMMY", "true").lower() == "true"

# ------------------------------------------------------------
# Global state (SAFE)
# ------------------------------------------------------------

client: Optional[BetfairClient] = None
state = StrategyState()
runner: Optional[BotRunner] = None


def get_client() -> BetfairClient:
    global client, runner
    if client is None:
        client = BetfairClient(use_dummy=USE_DUMMY)
        runner = BotRunner(client=client, state=state)
    return client


# ------------------------------------------------------------
# Auth helpers
# ------------------------------------------------------------

def is_logged_in(request: Request) -> bool:
    return request.session.get("user") == "admin"


def require_login(request: Request):
    if not is_logged_in(request):
        return RedirectResponse("/login", status_code=303)
    return None


# ------------------------------------------------------------
# Login page
# ------------------------------------------------------------

def render_login_page(error: str = "") -> HTMLResponse:
    return HTMLResponse(f"""
<html>
<head>
<title>Betfair Bot Login</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
body {{
    background:#020617;
    color:#e5e7eb;
    font-family:system-ui;
}}
.box {{
    max-width:360px;
    margin:100px auto;
    padding:24px;
    border:1px solid #1f2937;
    border-radius:14px;
}}
input,button {{
    width:100%;
    padding:10px;
    margin-top:8px;
    border-radius:8px;
    border:1px solid #374151;
    background:#020617;
    color:white;
}}
button {{
    background:#22c55e;
    font-weight:600;
}}
.error {{ color:#f97316; }}
</style>
</head>
<body>
<div class="box">
<h2>Login</h2>
{f"<div class='error'>{error}</div>" if error else ""}
<form method="post">
<input name="username" placeholder="Username">
<input name="password" type="password" placeholder="Password">
<button>Login</button>
</form>
</div>
</body>
</html>
""")


# ------------------------------------------------------------
# Dashboard
# ------------------------------------------------------------

def render_dashboard(message: str = "") -> HTMLResponse:
    client = get_client()

    try:
        funds = client.get_account_funds()
        bf_balance = funds.get("available_to_bet")
    except Exception:
        bf_balance = None

    try:
        markets = client.get_todays_novice_hurdle_markets()
    except Exception:
        markets = []

    bank = state.bank
    starting = state.starting_bank
    day_pl = bank - starting
    running = state.running

    history = list(state.history)[-10:][::-1] if state.history else []

    html = f"""
<html>
<head>
<title>Betfair Bot</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
body {{
    margin:0;
    background:#020617;
    color:#e5e7eb;
    font-family:system-ui;
}}
.page {{ padding:14px; max-width:1100px; margin:auto; }}
.card {{
    background:#020617;
    border:1px solid #1f2937;
    border-radius:14px;
    padding:14px;
    margin-bottom:14px;
}}
.grid {{
    display:grid;
    grid-template-columns:1fr 1fr;
    gap:14px;
}}
@media(max-width:800px) {{
    .grid {{ grid-template-columns:1fr; }}
}}
.btn {{
    padding:6px 12px;
    border-radius:999px;
    border:none;
    cursor:pointer;
    font-weight:600;
}}
.green {{ color:#4ade80; }}
.red {{ color:#fca5a5; }}
</style>
</head>
<body>
<div class="page">

<h2>Betfair 2-Fav Dutching Bot</h2>
<p>
Logged in as {ADMIN_USERNAME} |
<a href="/logout">Logout</a> |
<a href="/inspect_hurdles">Inspect Markets</a>
</p>

{f"<p style='color:#f97316'>{message}</p>" if message else ""}

<div class="grid">

<div class="card">
<h3>Bank & Settings</h3>

<form method="post" action="/update_settings">
Starting bank (£):
<input name="starting_bank" value="{state.starting_bank}">
<br><br>
Current bank (£):
<input name="current_bank" value="{state.bank}">
<br><br>
Stake %:
<input name="stake_percent" value="{state.stake_percent}">
<br><br>
<button class="btn">Save</button>
<button class="btn" name="reset_bank" value="1">Reset</button>
</form>

<hr>

<h4>Races Today</h4>
<form method="post" action="/update_race_selection">
"""

    for m in markets:
        checked = "checked" if m["market_id"] in state.selected_markets else ""
        html += f"""
<label>
<input type="checkbox" name="selected_markets" value="{m['market_id']}" {checked}>
{m['name']}
</label><br>
"""

    html += """
<br>
<button class="btn">Save races</button>
</form>
</div>

<div class="card">
<h3>Status</h3>

<p>Bot: <strong>{status}</strong></p>
<p>Bank: £{bank:.2f}</p>
<p>P/L today: <span class="{pl_class}">£{day_pl:.2f}</span></p>
<p>Betfair balance: {bf}</p>

<form method="post" action="/start"><button class="btn">Start</button></form>
<form method="post" action="/stop"><button class="btn">Stop</button></form>

<hr>

<h4>History</h4>
"""

    for h in history:
        html += f"<div>{h['race_name']} — £{h['pl']:.2f}</div>"

    html += """
</div>
</div>
</div>
</body>
</html>
"""

    return HTMLResponse(
        html.format(
            status="RUNNING" if running else "STOPPED",
            pl_class="green" if day_pl >= 0 else "red",
            bf=f"£{bf_balance:.2f}" if bf_balance is not None else "—",
        )
    )


# ------------------------------------------------------------
# Routes
# ------------------------------------------------------------

@app.get("/login")
async def login_get(request: Request):
    if is_logged_in(request):
        return RedirectResponse("/", 303)
    return render_login_page()


@app.post("/login")
async def login_post(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
):
    if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
        request.session["user"] = "admin"
        return RedirectResponse("/", 303)
    return render_login_page("Invalid login")


@app.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", 303)


@app.get("/")
async def home(request: Request):
    redirect = require_login(request)
    if redirect:
        return redirect
    return render_dashboard()


@app.post("/update_settings")
async def update_settings(
    request: Request,
    starting_bank: float = Form(...),
    current_bank: float = Form(...),
    stake_percent: float = Form(...),
    reset_bank: str = Form(None),
):
    redirect = require_login(request)
    if redirect:
        return redirect

    state.starting_bank = starting_bank
    state.bank = starting_bank if reset_bank else current_bank
    state.stake_percent = stake_percent

    return render_dashboard("Settings saved")


@app.post("/update_race_selection")
async def update_race_selection(request: Request):
    redirect = require_login(request)
    if redirect:
        return redirect

    form = await request.form()
    state.selected_markets = form.getlist("selected_markets")
    state.current_index = 0
    return render_dashboard("Races updated")


@app.post("/start")
async def start_bot(request: Request):
    redirect = require_login(request)
    if redirect:
        return redirect

    get_client()
    runner.start()
    return render_dashboard("Bot started")


@app.post("/stop")
async def stop_bot(request: Request):
    redirect = require_login(request)
    if redirect:
        return redirect

    runner.stop()
    return render_dashboard("Bot stopped")


@app.get("/inspect_hurdles")
async def inspect_hurdles(request: Request):
    redirect = require_login(request)
    if redirect:
        return redirect

    client = get_client()
    markets = client.get_todays_novice_hurdle_markets()

    html = "<h2>Markets</h2><ul>"
    for m in markets:
        html += f"<li>{m['name']}</li>"
    html += "</ul><a href='/'>Back</a>"

    return HTMLResponse(html)
