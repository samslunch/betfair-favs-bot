# webapp.py
# FastAPI dashboard for the Betfair 2-fav dutching bot.
# SAFE VERSION – no import-time Betfair login, no .format() on CSS templates.

import os
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

SESSION_SECRET = os.getenv("SESSION_SECRET", "dev-secret-change-me")
app.add_middleware(SessionMiddleware, secret_key=SESSION_SECRET)

ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "adamhill")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "Adamhillonline1!")

# Default to dummy on servers unless explicitly set to false
USE_DUMMY = os.getenv("BETFAIR_DUMMY", "true").lower() == "true"

# ------------------------------------------------------------
# Global state (SAFE)
# ------------------------------------------------------------

client: Optional[BetfairClient] = None
runner: Optional[BotRunner] = None

state = StrategyState()


def get_client() -> BetfairClient:
    """Lazy-init the Betfair client and runner (prevents import-time crashes)."""
    global client, runner
    if client is None:
        client = BetfairClient(use_dummy=USE_DUMMY)
    if runner is None:
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
    html = f"""
<html>
<head>
  <title>Betfair Bot Login</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <style>
    body {{
      background:#020617;
      color:#e5e7eb;
      font-family:system-ui, -apple-system, Segoe UI, Roboto, sans-serif;
      margin:0;
      padding:0;
    }}
    .box {{
      max-width:380px;
      margin:90px auto;
      padding:22px;
      border:1px solid #1f2937;
      border-radius:16px;
      box-shadow: 0 20px 25px -5px rgba(0,0,0,0.5);
    }}
    input {{
      width:100%;
      padding:10px 12px;
      margin-top:8px;
      border-radius:10px;
      border:1px solid #374151;
      background:#020617;
      color:#fff;
      font-size:0.95rem;
    }}
    button {{
      width:100%;
      padding:10px 12px;
      margin-top:10px;
      border-radius:999px;
      border:none;
      cursor:pointer;
      background: linear-gradient(135deg, #22c55e, #16a34a);
      color:white;
      font-weight:700;
      font-size:0.95rem;
    }}
    .error {{
      color:#f97316;
      margin: 8px 0 0 0;
      font-size:0.9rem;
    }}
    a {{ color:#38bdf8; text-decoration:none; }}
  </style>
</head>
<body>
  <div class="box">
    <h2 style="margin:0 0 6px 0;">Betfair Bot Login</h2>
    <div style="color:#9ca3af;font-size:0.9rem;margin-bottom:10px;">
      Dummy mode: <b>{"ON" if USE_DUMMY else "OFF"}</b>
    </div>
    {f"<div class='error'>{error}</div>" if error else ""}
    <form method="post" action="/login">
      <input name="username" placeholder="Username" autocomplete="username">
      <input name="password" type="password" placeholder="Password" autocomplete="current-password">
      <button type="submit">Log in</button>
    </form>
  </div>
</body>
</html>
"""
    return HTMLResponse(html)


# ------------------------------------------------------------
# Dashboard
# ------------------------------------------------------------

def render_dashboard(message: str = "") -> HTMLResponse:
    client = get_client()

    # Funds
    try:
        funds = client.get_account_funds()
        bf_balance = funds.get("available_to_bet")
    except Exception:
        bf_balance = None

    # Markets
    try:
        markets = client.get_todays_novice_hurdle_markets()
    except Exception:
        markets = []

    bank = getattr(state, "bank", 100.0)
    starting_bank = getattr(state, "starting_bank", bank)
    day_pl = bank - starting_bank
    running = bool(getattr(state, "running", False))

    # Safe history access
    history = []
    if hasattr(state, "history") and state.history:
        history = list(state.history)[-10:][::-1]

    status = "RUNNING" if running else "STOPPED"
    pl_class = "green" if day_pl >= 0 else "red"
    bf = f"£{bf_balance:.2f}" if bf_balance is not None else "—"

    selected = set(getattr(state, "selected_markets", []))

    html = f"""
<html>
<head>
  <title>Betfair 2-Fav Dutching Bot</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <style>
    * {{ box-sizing:border-box; }}
    body {{
      margin:0;
      background:#020617;
      color:#e5e7eb;
      font-family:system-ui, -apple-system, Segoe UI, Roboto, sans-serif;
    }}
    a {{ color:#38bdf8; text-decoration:none; }}
    a:hover {{ text-decoration:underline; }}
    .page {{ max-width:1100px; margin:0 auto; padding:14px; }}
    .top {{
      display:flex; justify-content:space-between; gap:10px; align-items:flex-start;
      margin-bottom:12px;
    }}
    @media(max-width:800px) {{
      .top {{ flex-direction:column; }}
    }}
    .card {{
      background:#020617;
      border:1px solid #1f2937;
      border-radius:16px;
      padding:14px;
      box-shadow: 0 20px 25px -5px rgba(0,0,0,0.4);
    }}
    .grid {{
      display:grid; grid-template-columns:1fr 1fr; gap:14px;
    }}
    @media(max-width:900px) {{
      .grid {{ grid-template-columns:1fr; }}
    }}
    .sub {{ color:#9ca3af; font-size:0.85rem; }}
    .pill {{
      display:inline-flex; align-items:center; gap:6px;
      border-radius:999px; padding:4px 10px; font-size:0.8rem;
      border:1px solid #374151;
    }}
    .pill.green {{ color:#4ade80; border-color: rgba(34,197,94,0.35); background: rgba(34,197,94,0.08); }}
    .pill.red {{ color:#fca5a5; border-color: rgba(248,113,113,0.35); background: rgba(248,113,113,0.08); }}
    label {{ display:block; font-size:0.85rem; color:#9ca3af; margin:8px 0 4px; }}
    input {{
      width:100%; padding:8px 10px; border-radius:10px;
      border:1px solid #374151; background:#020617; color:#e5e7eb;
    }}
    .row {{ display:flex; gap:10px; flex-wrap:wrap; }}
    .row > div {{ flex:1; min-width:160px; }}
    .btn {{
      display:inline-flex; align-items:center; justify-content:center;
      padding:8px 14px; border-radius:999px; border:none; cursor:pointer;
      font-weight:700; font-size:0.9rem; margin-right:6px; margin-top:8px;
    }}
    .btn.primary {{ background:linear-gradient(135deg,#22c55e,#16a34a); color:#fff; }}
    .btn.secondary {{ background:#0f172a; color:#e5e7eb; border:1px solid #374151; }}
    .btn.danger {{ background:#b91c1c; color:#fff; }}
    .green {{ color:#4ade80; }}
    .red {{ color:#fca5a5; }}
    .list {{
      max-height:260px; overflow-y:auto; padding:10px; border-radius:10px;
      border:1px solid #1f2937;
    }}
    .hist {{
      font-size:0.9rem;
      border-top:1px solid #1f2937;
      margin-top:10px; padding-top:10px;
    }}
  </style>
</head>
<body>
  <div class="page">
    <div class="top">
      <div>
        <h2 style="margin:0 0 4px 0;">Betfair 2-Fav Dutching Bot</h2>
        <div class="sub">
          Logged in as <b>{ADMIN_USERNAME}</b> |
          <a href="/logout">Logout</a> |
          <a href="/inspect_hurdles">Inspect markets</a>
        </div>
      </div>
      <div style="text-align:right;">
        <div class="pill {'green' if running else 'red'}">
          <span style="font-size:0.7rem;">●</span> {status}
        </div>
        <div class="sub" style="margin-top:4px;">
          Mode: <b>{"DUMMY" if USE_DUMMY else "LIVE READ-ONLY"}</b>
        </div>
      </div>
    </div>

    {f"<div class='sub' style='color:#f97316;margin-bottom:10px;'><b>{message}</b></div>" if message else ""}

    <div class="grid">

      <div class="card">
        <h3 style="margin:0 0 8px 0;">Bank & Settings</h3>

        <form method="post" action="/update_settings">
          <div class="row">
            <div>
              <label>Starting bank (£)</label>
              <input name="starting_bank" value="{getattr(state,'starting_bank',100.0)}">
            </div>
            <div>
              <label>Current bank (£)</label>
              <input name="current_bank" value="{getattr(state,'bank',100.0)}">
            </div>
          </div>

          <div class="row">
            <div>
              <label>Stake %</label>
              <input name="stake_percent" value="{getattr(state,'stake_percent',5.0)}">
            </div>
          </div>

          <button class="btn primary" type="submit">Save</button>
          <button class="btn secondary" name="reset_bank" value="1" type="submit">Reset</button>
        </form>

        <hr style="border-color:#1f2937; margin:14px 0;">

        <h3 style="margin:0 0 8px 0;">Races Today</h3>
        <div class="sub" style="margin-bottom:8px;">
          Tick races and save selection.
        </div>

        <form method="post" action="/update_race_selection">
          <div class="list">
    """

    if not markets:
        html += """
            <div class="sub" style="color:#f97316;">No markets returned (dummy mode should show some).</div>
        """
    else:
        for m in markets:
            mid = m.get("market_id")
            name = m.get("name", mid)
            checked = "checked" if mid in selected else ""
            html += f"""
            <label style="display:flex;align-items:center;gap:8px;margin:6px 0;color:#e5e7eb;">
              <input type="checkbox" name="selected_markets" value="{mid}" {checked}>
              <span style="font-size:0.9rem;">{name}</span>
            </label>
            """

    html += f"""
          </div>
          <button class="btn secondary" type="submit">Save races</button>
        </form>
      </div>

      <div class="card">
        <h3 style="margin:0 0 8px 0;">Status & Controls</h3>

        <div class="row" style="margin-bottom:10px;">
          <div>
            <div class="sub">Current bank</div>
            <div style="font-size:1.2rem;">£{bank:.2f}</div>
          </div>
          <div>
            <div class="sub">Day P/L</div>
            <div class="{pl_class}" style="font-size:1.1rem;">£{day_pl:.2f}</div>
          </div>
          <div>
            <div class="sub">Betfair balance</div>
            <div style="font-size:1.05rem;">{bf}</div>
          </div>
        </div>

        <form method="post" action="/start">
          <button class="btn primary" type="submit">Start</button>
        </form>
        <form method="post" action="/stop">
          <button class="btn danger" type="submit">Stop</button>
        </form>

        <div class="hist">
          <div class="sub" style="margin-bottom:6px;">Recent history</div>
    """

    if not history:
        html += """<div class="sub">No races yet.</div>"""
    else:
        for h in history:
            race_name = h.get("race_name", "?")
            pl = float(h.get("pl", 0.0))
            cls = "green" if pl >= 0 else "red"
            html += f"""<div style="margin:4px 0;">{race_name} — <span class="{cls}">£{pl:.2f}</span></div>"""

    html += """
        </div>
      </div>

    </div>
  </div>
</body>
</html>
"""
    return HTMLResponse(html)


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

    state.starting_bank = float(starting_bank)
    if reset_bank:
        state.bank = float(starting_bank)
    else:
        state.bank = float(current_bank)

    state.stake_percent = float(stake_percent)
    return render_dashboard("Settings saved.")


@app.post("/update_race_selection")
async def update_race_selection(request: Request):
    redirect = require_login(request)
    if redirect:
        return redirect

    form = await request.form()
    state.selected_markets = form.getlist("selected_markets")
    state.current_index = 0
    return render_dashboard("Races updated.")


@app.post("/start")
async def start_bot(request: Request):
    redirect = require_login(request)
    if redirect:
        return redirect

    if not getattr(state, "selected_markets", []):
        return render_dashboard("No races selected – tick at least one race and save.")

    get_client()
    runner.start()
    return render_dashboard("Bot started.")


@app.post("/stop")
async def stop_bot(request: Request):
    redirect = require_login(request)
    if redirect:
        return redirect

    get_client()
    runner.stop()
    return render_dashboard("Bot stopped.")


@app.get("/inspect_hurdles")
async def inspect_hurdles(request: Request):
    redirect = require_login(request)
    if redirect:
        return redirect

    client = get_client()
    markets = client.get_todays_novice_hurdle_markets()

    items = "".join(f"<li>{m.get('name','?')} ({m.get('market_id','?')})</li>" for m in markets)
    html = f"""
    <html><body style="font-family:system-ui;background:#020617;color:#e5e7eb;padding:14px;">
      <h2>Inspect Markets</h2>
      <p><a href="/" style="color:#38bdf8;">Back</a></p>
      <p>Dummy mode: <b>{"ON" if USE_DUMMY else "OFF"}</b></p>
      <ul>{items}</ul>
    </body></html>
    """
    return HTMLResponse(html)

