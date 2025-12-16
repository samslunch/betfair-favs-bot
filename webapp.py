# webapp.py
#
# FastAPI dashboard for the Betfair 2-fav dutching bot.
#
# Features:
#   - Login (session based)
#   - Settings: bank + stake % + quick profiles + seconds_before_off
#   - Min/Max odds
#   - Tick scheduler seconds (default 30s)
#   - Live Betfair balance (read-only)
#   - Race selection: UK/IE novice hurdle-ish WIN markets
#   - Bot control: Start / Stop
#   - Auto results ON (no manual outcome buttons)
#   - Option B loss recovery (recoup until win then STOP)
#   - Recent P/L history panel
#   - Debug route: /inspect_hurdles
#   - Live odds auto-refresh via /api/selected_live_odds (AJAX)
#   - Responsive mobile layout (no sideways scroll; tables scroll inside cards)
#   - Countdown timers per race
#   - UI Logs panel
#
import os
import datetime as dt
import logging
from collections import deque
from typing import Optional, Any, Dict, List

from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from starlette.middleware.sessions import SessionMiddleware

from betfair_client import BetfairClient
from strategy import StrategyState, BotRunner

app = FastAPI()

SESSION_SECRET = os.getenv("SESSION_SECRET", "dev-secret-change-me")
app.add_middleware(SessionMiddleware, secret_key=SESSION_SECRET)

ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "change-me")

BOT_MODE = os.getenv("BOT_MODE", "dummy").strip().lower()
if BOT_MODE not in ("dummy", "simulation", "live"):
    BOT_MODE = "dummy"

state = StrategyState()

_client: Optional[BetfairClient] = None
runner: Optional[BotRunner] = None

# -------------------------
# In-app log buffer (UI logs)
# -------------------------
LOG_BUFFER = deque(maxlen=1000)


class UILogHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
        except Exception:
            msg = record.getMessage()
        ts = dt.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
        LOG_BUFFER.append(f"{ts} | {record.levelname:<7} | {msg}")


def setup_ui_logging() -> None:
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    for h in list(root.handlers):
        if isinstance(h, UILogHandler):
            return
    h = UILogHandler()
    h.setFormatter(logging.Formatter("%(message)s"))
    root.addHandler(h)


setup_ui_logging()

# Capture print() too
import builtins  # noqa

if not getattr(builtins, "_ui_print_wrapped", False):
    _original_print = builtins.print

    def ui_print(*args, **kwargs):
        _original_print(*args, **kwargs)
        try:
            msg = " ".join(str(a) for a in args)
            ts = dt.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
            LOG_BUFFER.append(f"{ts} | PRINT   | {msg}")
        except Exception:
            pass

    builtins.print = ui_print
    builtins._ui_print_wrapped = True


def get_client() -> BetfairClient:
    global _client, runner
    if _client is None:
        _client = BetfairClient(mode=BOT_MODE)
    if runner is None:
        runner = BotRunner(client=_client, state=state)
    return _client


def is_logged_in(request: Request) -> bool:
    return request.session.get("user") == "admin"


def require_login(request: Request) -> Optional[RedirectResponse]:
    if not is_logged_in(request):
        return RedirectResponse("/login", status_code=303)
    return None


def render_login_page(error: str = "") -> HTMLResponse:
    html = f"""
    <html>
    <head>
      <title>Betfair Bot Login</title>
      <meta name="viewport" content="width=device-width, initial-scale=1" />
      <style>
        html, body {{ width: 100%; max-width: 100%; overflow-x: hidden; }}
        body {{
          font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
          background: #020617;
          color: #e5e7eb;
          margin: 0;
          padding: 0;
        }}
        .container {{
          max-width: 380px;
          margin: 70px auto;
          padding: 24px;
          background: #020617;
          border-radius: 16px;
          border: 1px solid #1f2937;
          box-shadow: 0 20px 25px -5px rgba(0,0,0,0.5);
        }}
        h1 {{ margin-top: 0; text-align: center; font-size: 1.5rem; }}
        label {{ display: block; font-size: 0.85rem; margin-bottom: 4px; color: #9ca3af; }}
        input[type="text"], input[type="password"] {{
          width: 100%;
          max-width: 100%;
          padding: 10px 12px;
          margin-bottom: 12px;
          border-radius: 10px;
          border: 1px solid #374151;
          background: #020617;
          color: #e5e7eb;
          font-size: 0.95rem;
          outline: none;
        }}
        button {{
          width: 100%;
          max-width: 100%;
          padding: 10px;
          border-radius: 999px;
          border: none;
          cursor: pointer;
          background: linear-gradient(135deg, #22c55e, #16a34a);
          color: white;
          font-weight: 700;
          font-size: 0.95rem;
        }}
        .error {{ color: #f97316; font-size: 0.9rem; margin-bottom: 10px; text-align: center; }}
      </style>
    </head>
    <body>
      <div class="container">
        <h1>Betfair Bot Login</h1>
        {("<div class='error'>" + error + "</div>") if error else ""}
        <form method="POST" action="/login">
          <label for="username">Username</label>
          <input type="text" name="username" id="username" autocomplete="username" />
          <label for="password">Password</label>
          <input type="password" name="password" id="password" autocomplete="current-password" />
          <button type="submit">Log In</button>
        </form>
      </div>
    </body>
    </html>
    """
    return HTMLResponse(html)


def _safe_float(x: Any) -> Optional[float]:
    try:
        return float(x)
    except Exception:
        return None


def _start_time_iso_z(client: BetfairClient, market_id: str) -> str:
    try:
        st = client.get_market_start_time(market_id)
        if not st:
            return ""
        if st.tzinfo is None:
            st = st.replace(tzinfo=dt.timezone.utc)
        else:
            st = st.astimezone(dt.timezone.utc)
        return st.isoformat().replace("+00:00", "Z")
    except Exception as e:
        print("[WEBAPP] start_time fetch error:", e)
        return ""


def render_dashboard(message: str = "") -> HTMLResponse:
    client = get_client()

    # Betfair balance (read-only)
    bf_balance: Optional[float] = None
    bf_err: Optional[str] = None
    try:
        funds = client.get_account_funds()
        bf_balance = _safe_float(
    funds.get("availableToBetBalance")
    or funds.get("availableToBetBalanceUK")
    or funds.get("availableToBetBalanceGBP")
    or funds.get("available_to_bet")  # fallback for dummy/legacy
)

    except Exception as e:
        bf_err = str(e)
        print("[WEBAPP] Error fetching account funds:", e)

    # markets
    try:
        markets = client.get_todays_novice_hurdle_markets()
    except Exception as e:
        print("[WEBAPP] Error fetching markets:", e)
        markets = []

    selected = set(getattr(state, "selected_markets", []) or [])

    running = bool(getattr(state, "running", False))
    bank = float(getattr(state, "bank", 100.0) or 100.0)
    starting_bank = float(getattr(state, "starting_bank", bank) or bank)
    day_pl = bank - starting_bank

    history: List[Dict[str, Any]] = []
    if state.history:
        history = list(state.history)[-15:][::-1]

    # mode pill
    mode_label = BOT_MODE.upper()
    if BOT_MODE == "simulation":
        mode_desc = "SIMULATION (paper bank, real odds/results, NO bets)"
    elif BOT_MODE == "dummy":
        mode_desc = "DUMMY (fake data)"
    else:
        mode_desc = "LIVE (bet placement still guarded by ALLOW_LIVE_BETS)"

    html = f"""
    <html>
    <head>
      <title>Betfair 2-Fav Dutching Bot</title>
      <meta name="viewport" content="width=device-width, initial-scale=1" />
      <style>
        * {{ box-sizing: border-box; }}
        html, body {{ width: 100%; max-width: 100%; overflow-x: hidden; }}
        body {{
          margin: 0;
          font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
          background: #020617;
          color: #e5e7eb;
        }}
        a {{ color: #38bdf8; text-decoration: none; }}
        a:hover {{ text-decoration: underline; }}

        .page {{ width: 100%; max-width: 1200px; margin: 0 auto; padding: 14px; }}

        .top {{
          display: flex;
          flex-wrap: wrap;
          justify-content: space-between;
          align-items: flex-start;
          gap: 10px;
          margin-bottom: 12px;
        }}
        h1 {{ margin: 0; font-size: 1.4rem; }}
        .sub {{ font-size: 0.82rem; color: #9ca3af; }}

        .pill {{
          border-radius: 999px;
          padding: 4px 10px;
          font-size: 0.75rem;
          display: inline-flex;
          align-items: center;
          gap: 6px;
          white-space: nowrap;
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
        .pill.blue {{
          background: rgba(56,189,248,0.08);
          border: 1px solid rgba(56,189,248,0.25);
          color: #7dd3fc;
        }}

        .grid {{
          display: grid;
          grid-template-columns: 1.1fr 1fr;
          gap: 14px;
        }}
        @media (max-width: 900px) {{
          .grid {{ grid-template-columns: 1fr; }}
        }}

        .card {{
          background: #020617;
          border-radius: 16px;
          border: 1px solid #1f2937;
          padding: 12px 14px;
          box-shadow: 0 20px 25px -5px rgba(0,0,0,0.4);
          min-width: 0;
        }}

        label {{ display: block; font-size: 0.8rem; margin-bottom: 3px; color: #9ca3af; }}

        input[type="number"], input[type="text"] {{
          width: 100%;
          max-width: 100%;
          padding: 8px 10px;
          border-radius: 10px;
          border: 1px solid #374151;
          background: #020617;
          color: #e5e7eb;
          font-size: 0.9rem;
          outline: none;
        }}

        .row {{
          display: flex;
          flex-wrap: wrap;
          gap: 10px;
        }}
        .row > div {{
          flex: 1 1 160px;
          min-width: 0;
        }}

        .btn {{
          border-radius: 999px;
          padding: 8px 14px;
          border: none;
          cursor: pointer;
          font-size: 0.85rem;
          font-weight: 700;
          display: inline-flex;
          align-items: center;
          justify-content: center;
          gap: 8px;
          max-width: 100%;
        }}
        .btn.primary {{
          background: linear-gradient(135deg, #22c55e, #16a34a);
          color: white;
        }}
        .btn.secondary {{
          background: #0f172a;
          color: #e5e7eb;
          border: 1px solid #374151;
        }}
        .btn.danger {{
          background: #b91c1c;
          color: white;
        }}
        .btn.small {{
          padding: 6px 10px;
          font-size: 0.78rem;
        }}

        .message {{ color: #f97316; font-size: 0.85rem; margin-bottom: 10px; }}
        .green-text {{ color: #4ade80; }}
        .red-text {{ color: #fca5a5; }}

        .list {{
          max-height: 320px;
          overflow-y: auto;
          border-radius: 10px;
          border: 1px solid #1f2937;
          padding: 8px;
        }}
        .list label span, .list span, .list div, .list {{
          overflow-wrap: anywhere;
          word-break: break-word;
        }}

        .table-wrap {{
          width: 100%;
          overflow-x: auto;
          -webkit-overflow-scrolling: touch;
          border-radius: 10px;
          border: 1px solid #1f2937;
        }}
        table {{
          width: 100%;
          border-collapse: collapse;
          min-width: 760px;
          font-size: 0.85rem;
        }}
        th, td {{
          padding: 8px 10px;
          border-bottom: 1px solid #1f2937;
          vertical-align: top;
        }}
        th {{
          text-align: left;
          color: #9ca3af;
          font-weight: 700;
        }}
        tr:last-child td {{ border-bottom: none; }}

        .muted {{ color: #9ca3af; }}
        .mono {{ font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace; }}
      </style>
    </head>
    <body>
      <div class="page">

        <div class="top">
          <div>
            <h1>Betfair 2-Fav Dutching Bot</h1>
            <div class="sub">
              Logged in as <strong>{ADMIN_USERNAME}</strong> |
              <a href="/logout">Log out</a> |
              <a href="/inspect_hurdles">Inspect Markets</a>
            </div>
          </div>

          <div style="text-align:right;">
            <div class="pill {"green" if running else "red"}">
              <span style="font-size:0.7rem;">●</span>
              {"Running" if running else "Stopped"}
            </div>
            <div style="margin-top:6px; display:flex; justify-content:flex-end; gap:8px; flex-wrap:wrap;">
              <div class="pill blue">{mode_label}</div>
            </div>
            <div class="sub" style="margin-top:6px;">
              {mode_desc}
            </div>
          </div>
        </div>

        {f"<div class='message'><b>{message}</b></div>" if message else ""}

        <div class="grid">

          <!-- LEFT -->
          <div class="card">
            <h3 style="margin:0 0 10px 0;">Bank & Settings</h3>

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

              <div class="row" style="margin-top:10px;">
                <div>
                  <label>Stake %</label>
                  <input name="stake_percent" value="{getattr(state,'stake_percent',5.0)}">
                </div>
                <div>
                  <label>Seconds before off</label>
                  <input name="seconds_before_off" value="{getattr(state,'seconds_before_off',60)}">
                </div>
              </div>

              <div class="row" style="margin-top:10px;">
                <div>
                  <label>Min odds</label>
                  <input name="min_odds" value="{getattr(state,'min_odds',1.01)}">
                </div>
                <div>
                  <label>Max odds</label>
                  <input name="max_odds" value="{getattr(state,'max_odds',1000.0)}">
                </div>
              </div>

              <div class="row" style="margin-top:10px;">
                <div>
                  <label>Scheduler tick (seconds)</label>
                  <input name="tick_seconds" value="{getattr(state,'tick_seconds',30)}">
                </div>
                <div>
                  <label>Loss carry (auto)</label>
                  <input value="{getattr(state,'loss_carry',0.0):.2f}" disabled>
                </div>
              </div>

              <div style="margin-top:10px;">
                <div class="sub" style="margin-bottom:6px;">Quick stake profiles (% of bank)</div>
                <div style="display:flex; flex-wrap:wrap; gap:8px;">
                  <button class="btn secondary small" name="profile" value="2" type="submit">2%</button>
                  <button class="btn secondary small" name="profile" value="5" type="submit">5%</button>
                  <button class="btn secondary small" name="profile" value="10" type="submit">10%</button>
                  <button class="btn secondary small" name="profile" value="15" type="submit">15%</button>
                  <button class="btn secondary small" name="profile" value="20" type="submit">20%</button>
                </div>
              </div>

              <div style="margin-top:10px; display:flex; flex-wrap:wrap; gap:10px;">
                <button class="btn primary" type="submit">Save</button>
                <button class="btn secondary" name="reset_bank" value="1" type="submit">Reset</button>
              </div>
            </form>

            <hr style="border-color:#1f2937; margin:14px 0;">

            <h3 style="margin:0 0 8px 0;">Races</h3>
            <div class="sub" style="margin-bottom:8px;">
              Tick races and save selection. Countdown uses Betfair market start time.
            </div>

            <form method="post" action="/update_race_selection">
              <div class="list">
    """

    if not markets:
        html += """
                <div class="sub" style="color:#f97316;">No markets returned.</div>
        """
    else:
        for m in markets:
            mid = m.get("market_id") or ""
            name = m.get("name", mid)
            checked = "checked" if mid in selected else ""
            start_raw = _start_time_iso_z(client, mid) if mid else ""
            html += f"""
                <label style="display:flex; gap:10px; align-items:flex-start; margin:8px 0;">
                  <input type="checkbox" name="selected_markets" value="{mid}" {checked} style="margin-top:3px;">
                  <span style="font-size:0.92rem; line-height:1.25;">
                    {name}
                    <div class="sub mono" style="margin-top:4px;">
                      <span class="countdown" data-start="{start_raw}">—</span>
                      <span class="muted"> | {mid}</span>
                    </div>
                  </span>
                </label>
            """

    html += f"""
              </div>

              <div style="margin-top:10px;">
                <button class="btn secondary" type="submit">Save races</button>
              </div>
            </form>
          </div>

          <!-- RIGHT -->
          <div class="card">
            <h3 style="margin:0 0 10px 0;">Status & Controls</h3>

            <div class="row" style="margin-bottom:10px;">
              <div>
                <div class="sub">Current bank</div>
                <div style="font-size:1.2rem;">£{bank:.2f}</div>
              </div>
              <div>
                <div class="sub">Day P/L</div>
                <div class="{"green-text" if day_pl >= 0 else "red-text"}" style="font-size:1.1rem;">
                  £{day_pl:.2f}
                </div>
              </div>
              <div>
                <div class="sub">Betfair balance</div>
                <div style="font-size:1.05rem;">
                  {("£" + f"{bf_balance:.2f}") if bf_balance is not None else "—"}
                </div>
                {f"<div class='sub' style='color:#f97316;'>({bf_err})</div>" if bf_err else ""}
              </div>
            </div>

            <div class="row" style="margin-bottom:10px;">
              <div>
                <div class="sub">Current market</div>
                <div class="mono" style="font-size:0.9rem;">{getattr(state,'current_market_id',None) or "—"}</div>
              </div>
              <div>
                <div class="sub">Acted (de-dup)</div>
                <div style="font-size:0.95rem;">{len(getattr(state,'acted_market_ids',set()) or set())}</div>
              </div>
              <div>
                <div class="sub">Loss carry</div>
                <div style="font-size:0.95rem;">£{getattr(state,'loss_carry',0.0):.2f}</div>
              </div>
            </div>

            <div style="display:flex; flex-wrap:wrap; gap:10px;">
              <form method="post" action="/start">
                <button class="btn primary" type="submit">▶ Start</button>
              </form>
              <form method="post" action="/stop">
                <button class="btn danger" type="submit">■ Stop</button>
              </form>
            </div>

            <hr style="border-color:#1f2937; margin:14px 0;">

            <h3 style="margin:0 0 8px 0;">Live odds + projected winnings</h3>
            <div class="sub" style="margin-bottom:8px;">
              Auto-refresh every ~10s for selected races (top 2 favourites).
            </div>

            <div class="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Race</th>
                    <th>Countdown</th>
                    <th>Fav 1</th>
                    <th>Odds</th>
                    <th>Stake</th>
                    <th>Fav 2</th>
                    <th>Odds</th>
                    <th>Stake</th>
                    <th>Profit if wins</th>
                    <th>Status</th>
                  </tr>
                </thead>
                <tbody id="oddsBody">
                  <tr><td colspan="10" class="muted">Select races to populate this table.</td></tr>
                </tbody>
              </table>
            </div>

            <hr style="border-color:#1f2937; margin:14px 0;">

            <h3 style="margin:0 0 8px 0;">History</h3>
    """

    if history:
        html += """
            <div class="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>#</th>
                    <th>Race</th>
                    <th>Favourites</th>
                    <th>Total stake</th>
                    <th>P/L</th>
                    <th>Winner</th>
                  </tr>
                </thead>
                <tbody>
        """
        for i, h in enumerate(history, 1):
            race_name = h.get("race_name", "?")
            favs = h.get("favs", "")
            total_stake_h = float(h.get("total_stake", 0.0) or 0.0)
            pl = float(h.get("pl", 0.0) or 0.0)
            cls = "green-text" if pl >= 0 else "red-text"
            winner = h.get("winner_selection_id", None)
            html += f"""
                  <tr>
                    <td>{i}</td>
                    <td style="min-width:220px;">{race_name}</td>
                    <td>{favs}</td>
                    <td>£{total_stake_h:.2f}</td>
                    <td class="{cls}">£{pl:.2f}</td>
                    <td class="mono">{winner if winner is not None else "—"}</td>
                  </tr>
            """
        html += """
                </tbody>
              </table>
            </div>
        """
    else:
        html += """<div class="sub muted">No races yet.</div>"""

    # Logs panel
    html += """
            <hr style="border-color:#1f2937; margin:14px 0;">
            <h3 style="margin:0 0 8px 0;">Logs</h3>
            <div class="sub" style="margin-bottom:8px;">Live app logs (auto-refresh)</div>

            <div style="border:1px solid #1f2937;border-radius:10px; padding:10px; max-height:260px; overflow:auto;">
              <pre id="logBox" style="margin:0; white-space:pre-wrap; overflow-wrap:anywhere; font-size:0.78rem; line-height:1.2;"></pre>
            </div>

            <div style="display:flex;gap:10px;margin-top:10px;flex-wrap:wrap;">
              <button class="btn secondary small" type="button" onclick="fetchLogs(true)">Refresh</button>
              <button class="btn secondary small" type="button" onclick="clearLogBox()">Clear</button>
            </div>
    """

    html += """
          </div>
        </div>
      </div>

      <script>
        function parseISO(s) {
          if (!s) return null;
          const d = new Date(s);
          if (isNaN(d.getTime())) return null;
          return d;
        }

        function fmt(sec) {
          sec = Math.max(0, Math.floor(sec));
          const h = Math.floor(sec / 3600);
          const m = Math.floor((sec % 3600) / 60);
          const s = sec % 60;
          if (h > 0) return h + "h " + m + "m " + s + "s";
          if (m > 0) return m + "m " + s + "s";
          return s + "s";
        }

        function tickCountdowns() {
          const els = document.querySelectorAll(".countdown");
          const now = new Date();
          els.forEach(el => {
            const startRaw = el.getAttribute("data-start") || "";
            const start = parseISO(startRaw);
            if (!start) { el.textContent = "—"; return; }
            const diffSec = (start.getTime() - now.getTime()) / 1000;
            if (diffSec <= 0) { el.textContent = "OFF / started"; return; }
            el.textContent = "Off in " + fmt(diffSec);
          });
        }

        // ---- odds auto-refresh ----
        function td(text, cls="") {
          const el = document.createElement("td");
          if (cls) el.className = cls;
          el.textContent = text;
          return el;
        }

        async function fetchOdds() {
          try {
            const r = await fetch("/api/selected_live_odds", { cache: "no-store" });
            if (!r.ok) return;
            const j = await r.json();
            const rows = j.rows || [];
            const body = document.getElementById("oddsBody");
            if (!body) return;

            body.innerHTML = "";

            if (!rows.length) {
              const tr = document.createElement("tr");
              const cell = document.createElement("td");
              cell.colSpan = 10;
              cell.className = "muted";
              cell.textContent = "Select races to populate this table.";
              tr.appendChild(cell);
              body.appendChild(tr);
              return;
            }

            rows.forEach(row => {
              const tr = document.createElement("tr");

              if (row.error) {
                tr.appendChild(td(row.race || row.market_id || "?", ""));
                tr.appendChild(td("—", "mono"));
                tr.appendChild(td("—"));
                tr.appendChild(td("—"));
                tr.appendChild(td("—"));
                tr.appendChild(td("—"));
                tr.appendChild(td("—"));
                tr.appendChild(td("—"));
                tr.appendChild(td("—", "red-text"));
                tr.appendChild(td("Error: " + row.error, "red-text"));
                body.appendChild(tr);
                return;
              }

              const cdSpan = document.createElement("span");
              cdSpan.className = "countdown mono";
              cdSpan.setAttribute("data-start", row.start_raw || "");
              cdSpan.textContent = "—";

              const cdTd = document.createElement("td");
              cdTd.appendChild(cdSpan);

              tr.appendChild(td(row.race || "?", ""));
              tr.appendChild(cdTd);
              tr.appendChild(td(row.fav1_name || "—"));
              tr.appendChild(td((row.odds1 || 0).toFixed(2)));
              tr.appendChild(td("£" + (row.stake1 || 0).toFixed(2)));
              tr.appendChild(td(row.fav2_name || "—"));
              tr.appendChild(td((row.odds2 || 0).toFixed(2)));
              tr.appendChild(td("£" + (row.stake2 || 0).toFixed(2)));

              const profit = row.profit_if_win || 0;
              tr.appendChild(td("£" + profit.toFixed(2), profit >= 0 ? "green-text" : "red-text"));

              tr.appendChild(td(row.note || "OK", row.note && row.note !== "OK" ? "muted" : ""));
              body.appendChild(tr);
            });

            tickCountdowns();
          } catch (e) {}
        }

        // ---- UI logs ----
        async function fetchLogs(forceScroll=false) {
          try {
            const r = await fetch("/api/logs?n=300", { cache: "no-store" });
            if (!r.ok) return;
            const j = await r.json();
            const el = document.getElementById("logBox");
            if (!el) return;

            const nearBottom = (el.scrollTop + el.clientHeight) >= (el.scrollHeight - 40);
            el.textContent = (j.lines || []).join("\\n");

            if (forceScroll || nearBottom) {
              el.scrollTop = el.scrollHeight;
            }
          } catch (e) {}
        }

        function clearLogBox() {
          const el = document.getElementById("logBox");
          if (el) el.textContent = "";
        }

        tickCountdowns();
        setInterval(tickCountdowns, 1000);

        fetchOdds();
        setInterval(fetchOdds, 10000);

        fetchLogs(true);
        setInterval(fetchLogs, 2000);
      </script>
    </body>
    </html>
    """

    return HTMLResponse(html)


# -------------------------
# Routes
# -------------------------

@app.get("/login")
async def login_get(request: Request):
    if is_logged_in(request):
        return RedirectResponse("/", status_code=303)
    return render_login_page()


@app.post("/login")
async def login_post(request: Request, username: str = Form(...), password: str = Form(...)):
    if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
        request.session["user"] = "admin"
        return RedirectResponse("/", status_code=303)
    return render_login_page("Invalid username or password.")


@app.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)


@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    redirect = require_login(request)
    if redirect:
        return redirect
    return render_dashboard()


@app.post("/update_settings")
async def update_settings(
    request: Request,
    starting_bank: str = Form(...),
    current_bank: str = Form(...),
    stake_percent: str = Form(...),
    seconds_before_off: str = Form("60"),
    min_odds: str = Form("1.01"),
    max_odds: str = Form("1000"),
    tick_seconds: str = Form("30"),
    profile: str = Form(None),
    reset_bank: str = Form(None),
):
    redirect = require_login(request)
    if redirect:
        return redirect

    def f(v: str, default: float) -> float:
        try:
            return float(v)
        except Exception:
            return default

    def i(v: str, default: int) -> int:
        try:
            return int(float(v))
        except Exception:
            return default

    sb = f(starting_bank, float(getattr(state, "starting_bank", 100.0) or 100.0))
    cb = f(current_bank, float(getattr(state, "bank", sb) or sb))
    sp = f(stake_percent, float(getattr(state, "stake_percent", 5.0) or 5.0))
    sbo = i(seconds_before_off, int(getattr(state, "seconds_before_off", 60) or 60))
    mn = f(min_odds, float(getattr(state, "min_odds", 1.01) or 1.01))
    mx = f(max_odds, float(getattr(state, "max_odds", 1000.0) or 1000.0))
    tk = i(tick_seconds, int(getattr(state, "tick_seconds", 30) or 30))

    if profile in ("2", "5", "10", "15", "20"):
        sp = float(profile)

    state.starting_bank = sb
    state.bank = sb if reset_bank else cb
    state.stake_percent = sp
    state.seconds_before_off = max(0, sbo)
    state.min_odds = max(1.01, mn)
    state.max_odds = max(state.min_odds, mx)
    state.tick_seconds = max(5, tk)

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
    global runner
    if runner is None:
        runner = BotRunner(client=_client, state=state)  # type: ignore
    runner.start()
    return render_dashboard("Bot started.")


@app.post("/stop")
async def stop_bot(request: Request):
    redirect = require_login(request)
    if redirect:
        return redirect

    get_client()
    global runner
    if runner is None:
        return render_dashboard("Bot already stopped.")
    runner.stop()
    return render_dashboard("Bot stopped.")


@app.get("/inspect_hurdles")
async def inspect_hurdles(request: Request):
    redirect = require_login(request)
    if redirect:
        return redirect

    client = get_client()
    markets = client.get_todays_novice_hurdle_markets()

    items = "".join(
        f"<li>{m.get('name','?')} <span style='color:#9ca3af;'>({m.get('market_id','?')})</span></li>"
        for m in markets
    )

    html = f"""
    <html>
      <head>
        <meta name="viewport" content="width=device-width, initial-scale=1" />
        <title>Inspect Markets</title>
      </head>
      <body style="font-family:system-ui;background:#020617;color:#e5e7eb;padding:14px;max-width:100%;overflow-x:hidden;">
        <h2>Inspect Markets</h2>
        <p><a href="/" style="color:#38bdf8;">Back</a></p>
        <p>Mode: <b>{BOT_MODE.upper()}</b></p>
        <ul>{items}</ul>
      </body>
    </html>
    """
    return HTMLResponse(html)


@app.get("/api/selected_live_odds")
async def api_selected_live_odds(request: Request):
    redirect = require_login(request)
    if redirect:
        return JSONResponse({"detail": "Unauthorized"}, status_code=401)

    client = get_client()

    bank = float(getattr(state, "bank", 100.0) or 100.0)
    stake_percent = float(getattr(state, "stake_percent", 5.0) or 5.0)
    base_stake = max(0.0, bank * (stake_percent / 100.0))

    min_odds = float(getattr(state, "min_odds", 1.01) or 1.01)
    max_odds = float(getattr(state, "max_odds", 1000.0) or 1000.0)

    out = []
    for mid in getattr(state, "selected_markets", []) or []:
        try:
            favs = client.get_top_two_favourites(mid)
            race = client.get_market_name(mid)
            start_raw = _start_time_iso_z(client, mid)

            if len(favs) < 2:
                out.append({"market_id": mid, "race": race, "start_raw": start_raw, "error": "Less than 2 priced favourites"})
                continue

            o1 = float(favs[0]["back"])
            o2 = float(favs[1]["back"])

            if not (min_odds <= o1 <= max_odds and min_odds <= o2 <= max_odds):
                out.append({
                    "market_id": mid, "race": race, "start_raw": start_raw,
                    "fav1_name": favs[0]["name"], "fav2_name": favs[1]["name"],
                    "odds1": o1, "odds2": o2,
                    "stake1": 0.0, "stake2": 0.0, "profit_if_win": 0.0,
                    "note": "Odds out of range",
                })
                continue

            # For preview: show what the bot would do NEXT given current loss_carry
            loss_carry = float(getattr(state, "loss_carry", 0.0) or 0.0)

            inv_sum = (1.0 / o1) + (1.0 / o2)
            denom = (1.0 / inv_sum) - 1.0
            total_stake = base_stake

            if loss_carry > 0 and denom > 0:
                req = loss_carry / denom
                total_stake = max(base_stake, req)

            # dutch
            s1 = total_stake * (1.0 / o1) / inv_sum
            s2 = total_stake - s1
            profit_each = total_stake / inv_sum - total_stake

            out.append({
                "market_id": mid,
                "race": race,
                "start_raw": start_raw,
                "fav1_name": favs[0]["name"],
                "fav2_name": favs[1]["name"],
                "odds1": o1,
                "odds2": o2,
                "stake1": s1,
                "stake2": s2,
                "profit_if_win": profit_each,
                "note": "OK",
            })

        except Exception as e:
            out.append({"market_id": mid, "race": mid, "start_raw": "", "error": str(e)})

    return JSONResponse({"rows": out})


@app.get("/api/logs")
async def api_logs(request: Request, n: int = 300):
    redirect = require_login(request)
    if redirect:
        return JSONResponse({"detail": "Unauthorized"}, status_code=401)

    try:
        n = int(n)
    except Exception:
        n = 300
    n = max(1, min(n, 1000))
    lines = list(LOG_BUFFER)[-n:]
    return JSONResponse({"lines": lines})
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "adamhill")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "Adamhillonline1!")

USE_DUMMY = os.getenv("BETFAIR_DUMMY", "true").lower() == "true"

state = StrategyState()

_client: Optional[BetfairClient] = None
runner: Optional[BotRunner] = None

# -------------------------
# In-app log buffer (UI logs)
# -------------------------
LOG_BUFFER = deque(maxlen=800)  # keep last 800 lines


class UILogHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
        except Exception:
            msg = record.getMessage()
        ts = dt.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
        LOG_BUFFER.append(f"{ts} | {record.levelname:<7} | {msg}")


def setup_ui_logging() -> None:
    root = logging.getLogger()
    root.setLevel(logging.INFO)

    for h in list(root.handlers):
        if isinstance(h, UILogHandler):
            return

    h = UILogHandler()
    h.setFormatter(logging.Formatter("%(message)s"))
    root.addHandler(h)


setup_ui_logging()

# Capture print() too (your code uses print a lot)
import builtins  # noqa: E402

if not getattr(builtins, "_ui_print_wrapped", False):
    _original_print = builtins.print

    def ui_print(*args, **kwargs):
        _original_print(*args, **kwargs)
        try:
            msg = " ".join(str(a) for a in args)
            ts = dt.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
            LOG_BUFFER.append(f"{ts} | PRINT   | {msg}")
        except Exception:
            pass

    builtins.print = ui_print
    builtins._ui_print_wrapped = True


def get_client() -> BetfairClient:
    global _client, runner
    if _client is None:
        _client = BetfairClient(use_dummy=USE_DUMMY)
    if runner is None:
        runner = BotRunner(client=_client, state=state)
    return _client


def is_logged_in(request: Request) -> bool:
    return request.session.get("user") == "admin"


def require_login(request: Request) -> Optional[RedirectResponse]:
    if not is_logged_in(request):
        return RedirectResponse("/login", status_code=303)
    return None


def render_login_page(error: str = "") -> HTMLResponse:
    html = f"""
    <html>
    <head>
      <title>Betfair Bot Login</title>
      <meta name="viewport" content="width=device-width, initial-scale=1" />
      <style>
        html, body {{ width: 100%; max-width: 100%; overflow-x: hidden; }}
        body {{
          font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
          background: #020617;
          color: #e5e7eb;
          margin: 0;
          padding: 0;
        }}
        .container {{
          max-width: 380px;
          margin: 70px auto;
          padding: 24px;
          background: #020617;
          border-radius: 16px;
          border: 1px solid #1f2937;
          box-shadow: 0 20px 25px -5px rgba(0,0,0,0.5);
        }}
        h1 {{ margin-top: 0; text-align: center; font-size: 1.5rem; }}
        label {{ display: block; font-size: 0.85rem; margin-bottom: 4px; color: #9ca3af; }}
        input[type="text"], input[type="password"] {{
          width: 100%;
          max-width: 100%;
          padding: 10px 12px;
          margin-bottom: 12px;
          border-radius: 10px;
          border: 1px solid #374151;
          background: #020617;
          color: #e5e7eb;
          font-size: 0.95rem;
          outline: none;
        }}
        button {{
          width: 100%;
          max-width: 100%;
          padding: 10px;
          border-radius: 999px;
          border: none;
          cursor: pointer;
          background: linear-gradient(135deg, #22c55e, #16a34a);
          color: white;
          font-weight: 700;
          font-size: 0.95rem;
        }}
        .error {{ color: #f97316; font-size: 0.9rem; margin-bottom: 10px; text-align: center; }}
      </style>
    </head>
    <body>
      <div class="container">
        <h1>Betfair Bot Login</h1>
        {("<div class='error'>" + error + "</div>") if error else ""}
        <form method="POST" action="/login">
          <label for="username">Username</label>
          <input type="text" name="username" id="username" autocomplete="username" />
          <label for="password">Password</label>
          <input type="password" name="password" id="password" autocomplete="current-password" />
          <button type="submit">Log In</button>
        </form>
      </div>
    </body>
    </html>
    """
    return HTMLResponse(html)


def _dutch_stakes(total_stake: float, o1: float, o2: float) -> Dict[str, float]:
    inv_sum = (1.0 / o1) + (1.0 / o2)
    if inv_sum <= 0:
        return {"stake1": 0.0, "stake2": 0.0, "profit_each": -total_stake}
    s1 = total_stake * (1.0 / o1) / inv_sum
    s2 = total_stake - s1
    profit_each = total_stake / inv_sum - total_stake
    return {"stake1": s1, "stake2": s2, "profit_each": profit_each}


def _safe_float(x: Any) -> Optional[float]:
    try:
        return float(x)
    except Exception:
        return None


def _start_time_iso_z(client: BetfairClient, market_id: str) -> str:
    try:
        st = client.get_market_start_time(market_id)
        if st is None:
            return ""
        if st.tzinfo is None:
            st = st.replace(tzinfo=dt.timezone.utc)
        else:
            st = st.astimezone(dt.timezone.utc)
        return st.isoformat().replace("+00:00", "Z")
    except Exception as e:
        print("[WEBAPP] Could not fetch start time for", market_id, ":", e)
        return ""


def render_dashboard(message: str = "") -> HTMLResponse:
    client = get_client()

    bf_balance: Optional[float] = None
    try:
        funds = client.get_account_funds()
        bf_balance = _safe_float(funds.get("available_to_bet"))
    except Exception as e:
        print("[WEBAPP] Error fetching account funds:", e)

    try:
        markets = client.get_todays_novice_hurdle_markets()
    except Exception as e:
        print("[WEBAPP] Error fetching markets:", e)
        markets = []

    selected = set(getattr(state, "selected_markets", []) or [])

    running = bool(getattr(state, "running", False))
    bank = float(getattr(state, "bank", 100.0) or 100.0)
    starting_bank = float(getattr(state, "starting_bank", bank) or bank)
    day_pl = bank - starting_bank

    history: List[Dict[str, Any]] = []
    if hasattr(state, "history") and state.history:
        history = list(state.history)[-15:][::-1]

    stake_percent = float(getattr(state, "stake_percent", 5.0) or 5.0)
    total_stake = bank * (stake_percent / 100.0)

    html = f"""
    <html>
    <head>
      <title>Betfair 2-Fav Dutching Bot</title>
      <meta name="viewport" content="width=device-width, initial-scale=1" />
      <style>
        * {{ box-sizing: border-box; }}
        html, body {{ width: 100%; max-width: 100%; overflow-x: hidden; }}
        body {{
          margin: 0;
          font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
          background: #020617;
          color: #e5e7eb;
        }}
        a {{ color: #38bdf8; text-decoration: none; }}
        a:hover {{ text-decoration: underline; }}

        .page {{ width: 100%; max-width: 1200px; margin: 0 auto; padding: 14px; }}

        .top {{
          display: flex;
          flex-wrap: wrap;
          justify-content: space-between;
          align-items: flex-start;
          gap: 10px;
          margin-bottom: 12px;
        }}
        h1 {{ margin: 0; font-size: 1.4rem; }}
        .sub {{ font-size: 0.82rem; color: #9ca3af; }}

        .pill {{
          border-radius: 999px;
          padding: 4px 10px;
          font-size: 0.75rem;
          display: inline-flex;
          align-items: center;
          gap: 6px;
          white-space: nowrap;
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
          .grid {{ grid-template-columns: 1fr; }}
        }}

        .card {{
          background: #020617;
          border-radius: 16px;
          border: 1px solid #1f2937;
          padding: 12px 14px;
          box-shadow: 0 20px 25px -5px rgba(0,0,0,0.4);
          min-width: 0;
        }}

        label {{ display: block; font-size: 0.8rem; margin-bottom: 3px; color: #9ca3af; }}

        input[type="number"], input[type="text"] {{
          width: 100%;
          max-width: 100%;
          padding: 8px 10px;
          border-radius: 10px;
          border: 1px solid #374151;
          background: #020617;
          color: #e5e7eb;
          font-size: 0.9rem;
          outline: none;
        }}

        .row {{
          display: flex;
          flex-wrap: wrap;
          gap: 10px;
        }}
        .row > div {{
          flex: 1 1 160px;
          min-width: 0;
        }}

        .btn {{
          border-radius: 999px;
          padding: 8px 14px;
          border: none;
          cursor: pointer;
          font-size: 0.85rem;
          font-weight: 700;
          display: inline-flex;
          align-items: center;
          justify-content: center;
          gap: 8px;
          max-width: 100%;
        }}
        .btn.primary {{
          background: linear-gradient(135deg, #22c55e, #16a34a);
          color: white;
        }}
        .btn.secondary {{
          background: #0f172a;
          color: #e5e7eb;
          border: 1px solid #374151;
        }}
        .btn.danger {{
          background: #b91c1c;
          color: white;
        }}
        .btn.small {{
          padding: 6px 10px;
          font-size: 0.78rem;
        }}

        .message {{ color: #f97316; font-size: 0.85rem; margin-bottom: 10px; }}
        .green-text {{ color: #4ade80; }}
        .red-text {{ color: #fca5a5; }}

        .list {{
          max-height: 320px;
          overflow-y: auto;
          border-radius: 10px;
          border: 1px solid #1f2937;
          padding: 8px;
        }}
        .list label span, .list span, .list div, .list {{
          overflow-wrap: anywhere;
          word-break: break-word;
        }}

        .table-wrap {{
          width: 100%;
          overflow-x: auto;
          -webkit-overflow-scrolling: touch;
          border-radius: 10px;
          border: 1px solid #1f2937;
        }}
        table {{
          width: 100%;
          border-collapse: collapse;
          min-width: 640px;
          font-size: 0.85rem;
        }}
        th, td {{
          padding: 8px 10px;
          border-bottom: 1px solid #1f2937;
          vertical-align: top;
        }}
        th {{
          text-align: left;
          color: #9ca3af;
          font-weight: 700;
        }}
        tr:last-child td {{ border-bottom: none; }}

        .muted {{ color: #9ca3af; }}
        .mono {{ font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace; }}
      </style>
    </head>
    <body>
      <div class="page">

        <div class="top">
          <div>
            <h1>Betfair 2-Fav Dutching Bot</h1>
            <div class="sub">
              Logged in as <strong>{ADMIN_USERNAME}</strong> |
              <a href="/logout">Log out</a> |
              <a href="/inspect_hurdles">Inspect Markets</a>
            </div>
          </div>

          <div style="text-align:right;">
            <div class="pill {"green" if running else "red"}">
              <span style="font-size:0.7rem;">●</span>
              {"Running" if running else "Stopped"}
            </div>
            <div class="sub" style="margin-top:6px;">
              Mode: {"DUMMY" if USE_DUMMY else "LIVE READ-ONLY (no placeOrders)"}
            </div>
          </div>
        </div>

        {f"<div class='message'><b>{message}</b></div>" if message else ""}

        <div class="grid">

          <!-- LEFT -->
          <div class="card">
            <h3 style="margin:0 0 10px 0;">Bank & Settings</h3>

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

              <div class="row" style="margin-top:10px;">
                <div>
                  <label>Stake %</label>
                  <input name="stake_percent" value="{getattr(state,'stake_percent',5.0)}">
                </div>
                <div>
                  <label>Seconds before off (default 60)</label>
                  <input name="seconds_before_off" value="{getattr(state,'seconds_before_off',60)}">
                </div>
              </div>

              <div style="margin-top:10px;">
                <div class="sub" style="margin-bottom:6px;">Quick stake profiles (% of bank)</div>
                <div style="display:flex; flex-wrap:wrap; gap:8px;">
                  <button class="btn secondary small" name="profile" value="2" type="submit">2%</button>
                  <button class="btn secondary small" name="profile" value="5" type="submit">5%</button>
                  <button class="btn secondary small" name="profile" value="10" type="submit">10%</button>
                  <button class="btn secondary small" name="profile" value="15" type="submit">15%</button>
                  <button class="btn secondary small" name="profile" value="20" type="submit">20%</button>
                </div>
              </div>

              <div style="margin-top:10px; display:flex; flex-wrap:wrap; gap:10px;">
                <button class="btn primary" type="submit">Save</button>
                <button class="btn secondary" name="reset_bank" value="1" type="submit">Reset</button>
              </div>

              <div style="margin-top:10px;">
                <div class="sub">
                  Recovery target: <span class="mono">£{getattr(state,'recovery_target',0.0):.2f}</span> |
                  Stop after win: <span class="mono">{'YES' if getattr(state,'stop_after_win',True) else 'NO'}</span>
                </div>
              </div>
            </form>

            <hr style="border-color:#1f2937; margin:14px 0;">

            <h3 style="margin:0 0 8px 0;">Races</h3>
            <div class="sub" style="margin-bottom:8px;">
              Tick races and save selection. Countdown uses Betfair market start time.
            </div>

            <form method="post" action="/update_race_selection">
              <div class="list">
    """

    if not markets:
        html += """
                <div class="sub" style="color:#f97316;">
                  No markets returned.
                </div>
        """
    else:
        for m in markets:
            mid = m.get("market_id") or ""
            name = m.get("name", mid)
            checked = "checked" if mid in selected else ""
            start_raw = _start_time_iso_z(client, mid) if mid else ""
            html += f"""
                <label style="display:flex; gap:10px; align-items:flex-start; margin:8px 0;">
                  <input type="checkbox" name="selected_markets" value="{mid}" {checked} style="margin-top:3px;">
                  <span style="font-size:0.92rem; line-height:1.25;">
                    {name}
                    <div class="sub mono" style="margin-top:4px;">
                      <span class="countdown" data-start="{start_raw}">—</span>
                      <span class="muted"> | {mid}</span>
                    </div>
                  </span>
                </label>
            """

    html += f"""
              </div>

              <div style="margin-top:10px;">
                <button class="btn secondary" type="submit">Save races</button>
              </div>
            </form>
          </div>

          <!-- RIGHT -->
          <div class="card">
            <h3 style="margin:0 0 10px 0;">Status & Controls</h3>

            <div class="row" style="margin-bottom:10px;">
              <div>
                <div class="sub">Current bank</div>
                <div style="font-size:1.2rem;">£{bank:.2f}</div>
              </div>
              <div>
                <div class="sub">Day P/L</div>
                <div class="{"green-text" if day_pl >= 0 else "red-text"}" style="font-size:1.1rem;">
                  £{day_pl:.2f}
                </div>
              </div>
              <div>
                <div class="sub">Betfair balance</div>
                <div style="font-size:1.05rem;">
                  {("£" + f"{bf_balance:.2f}") if bf_balance is not None else "—"}
                </div>
              </div>
            </div>

            <div style="display:flex; flex-wrap:wrap; gap:10px;">
              <form method="post" action="/start">
                <button class="btn primary" type="submit">▶ Start</button>
              </form>
              <form method="post" action="/stop">
                <button class="btn danger" type="submit">■ Stop</button>
              </form>
            </div>

            <div style="margin-top:12px;">
              <div class="sub">
                Auto-results: <b>ON</b> (the bot will settle each race automatically after the off).
              </div>
            </div>

            <hr style="border-color:#1f2937; margin:14px 0;">

            <h3 style="margin:0 0 8px 0;">Live odds + projected winnings</h3>
            <div class="sub" style="margin-bottom:8px;">
              Auto-refreshes every ~7 seconds from <span class="mono">/api/selected_live_odds</span>.
            </div>

            <div class="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Race</th>
                    <th>Countdown</th>
                    <th>Fav 1</th>
                    <th>Odds</th>
                    <th>Stake</th>
                    <th>Fav 2</th>
                    <th>Odds</th>
                    <th>Stake</th>
                    <th>Profit if wins</th>
                  </tr>
                </thead>
                <tbody id="oddsBody">
                  <tr>
                    <td colspan="9" class="muted">Select one or more races to see live odds + winnings here.</td>
                  </tr>
                </tbody>
              </table>
            </div>

            <hr style="border-color:#1f2937; margin:14px 0;">

            <h3 style="margin:0 0 8px 0;">History</h3>
    """

    if history:
        html += """
            <div class="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>#</th>
                    <th>Race</th>
                    <th>Favourites</th>
                    <th>Total stake</th>
                    <th>P/L</th>
                  </tr>
                </thead>
                <tbody>
        """
        for i, h in enumerate(history, 1):
            race_name = h.get("race_name", "?")
            favs = h.get("favs", "")
            total_stake_h = float(h.get("total_stake", 0.0) or 0.0)
            pl = float(h.get("pl", 0.0) or 0.0)
            cls = "green-text" if pl >= 0 else "red-text"
            html += f"""
                  <tr>
                    <td>{i}</td>
                    <td style="min-width:220px;">{race_name}</td>
                    <td>{favs}</td>
                    <td>£{total_stake_h:.2f}</td>
                    <td class="{cls}">£{pl:.2f}</td>
                  </tr>
            """
        html += """
                </tbody>
              </table>
            </div>
        """
    else:
        html += """
            <div class="sub muted">No races yet.</div>
        """

    # Logs panel
    html += """
            <hr style="border-color:#1f2937; margin:14px 0;">

            <h3 style="margin:0 0 8px 0;">Logs</h3>
            <div class="sub" style="margin-bottom:8px;">Live app logs (auto-refresh)</div>

            <div style="border:1px solid #1f2937;border-radius:10px; padding:10px; max-height:260px; overflow:auto;">
              <pre id="logBox" style="margin:0; white-space:pre-wrap; overflow-wrap:anywhere; font-size:0.78rem; line-height:1.2;"></pre>
            </div>

            <div style="display:flex;gap:10px;margin-top:10px;flex-wrap:wrap;">
              <button class="btn secondary small" type="button" onclick="fetchLogs(true)">Refresh</button>
              <button class="btn secondary small" type="button" onclick="clearLogBox()">Clear</button>
            </div>
    """

    html += """
          </div>
        </div>
      </div>

      <script>
        function parseISO(s) {
          if (!s) return null;
          const d = new Date(s);
          if (isNaN(d.getTime())) return null;
          return d;
        }

        function fmt(sec) {
          sec = Math.max(0, Math.floor(sec));
          const h = Math.floor(sec / 3600);
          const m = Math.floor((sec % 3600) / 60);
          const s = sec % 60;
          if (h > 0) return String(h) + "h " + String(m) + "m " + String(s) + "s";
          if (m > 0) return String(m) + "m " + String(s) + "s";
          return String(s) + "s";
        }

        function tickCountdowns() {
          const els = document.querySelectorAll(".countdown");
          const now = new Date();
          els.forEach(el => {
            const startRaw = el.getAttribute("data-start") || "";
            const start = parseISO(startRaw);
            if (!start) { el.textContent = "—"; return; }
            const diffSec = (start.getTime() - now.getTime()) / 1000;
            if (diffSec <= 0) { el.textContent = "OFF / started"; return; }
            el.textContent = "Off in " + fmt(diffSec);
          });
        }

        // ---- Odds auto-refresh ----
        function escapeHtml(s) {
          return String(s)
            .replaceAll("&", "&amp;")
            .replaceAll("<", "&lt;")
            .replaceAll(">", "&gt;")
            .replaceAll('"', "&quot;")
            .replaceAll("'", "&#039;");
        }

        async function refreshOdds() {
          try {
            const r = await fetch("/api/selected_live_odds", { cache: "no-store" });
            if (!r.ok) return;
            const j = await r.json();
            const rows = (j.rows || []);
            const body = document.getElementById("oddsBody");
            if (!body) return;

            if (!rows.length) {
              body.innerHTML = "<tr><td colspan='9' class='muted'>Select one or more races to see live odds + winnings here.</td></tr>";
              return;
            }

            let html = "";
            for (const row of rows) {
              if (row.error) {
                html += "<tr><td colspan='9' class='muted'>Error for " + escapeHtml(row.market_id) + ": " + escapeHtml(row.error) + "</td></tr>";
                continue;
              }

              const race = row.race || row.market_id;
              const start_raw = row.start_raw || "";
              const fav1 = (row.fav1 && row.fav1.name) ? row.fav1.name : (row.fav1_name || "—");
              const fav2 = (row.fav2 && row.fav2.name) ? row.fav2.name : (row.fav2_name || "—");

              const odds1 = row.odds1;
              const odds2 = row.odds2;
              const s1 = row.stake1;
              const s2 = row.stake2;
              const profit = row.profit_if_win;

              const profitClass = (typeof profit === "number" && profit >= 0) ? "green-text" : "red-text";

              html += "<tr>"
                + "<td style='min-width:220px;'>" + escapeHtml(race) + "</td>"
                + "<td class='mono'><span class='countdown' data-start='" + escapeHtml(start_raw) + "'>—</span></td>"
                + "<td>" + escapeHtml(fav1) + "</td>"
                + "<td>" + (typeof odds1 === "number" ? odds1.toFixed(2) : "—") + "</td>"
                + "<td>£" + (typeof s1 === "number" ? s1.toFixed(2) : "—") + "</td>"
                + "<td>" + escapeHtml(fav2) + "</td>"
                + "<td>" + (typeof odds2 === "number" ? odds2.toFixed(2) : "—") + "</td>"
                + "<td>£" + (typeof s2 === "number" ? s2.toFixed(2) : "—") + "</td>"
                + "<td class='" + profitClass + "'>£" + (typeof profit === "number" ? profit.toFixed(2) : "—") + "</td>"
                + "</tr>";
            }

            body.innerHTML = html;
            tickCountdowns(); // update countdowns for newly inserted rows
          } catch (e) {}
        }

        // ---- UI logs ----
        async function fetchLogs(forceScroll=false) {
          try {
            const r = await fetch("/api/logs?n=250", { cache: "no-store" });
            if (!r.ok) return;
            const j = await r.json();
            const el = document.getElementById("logBox");
            if (!el) return;

            const nearBottom = (el.scrollTop + el.clientHeight) >= (el.scrollHeight - 40);
            el.textContent = (j.lines || []).join("\\n");
            if (forceScroll || nearBottom) el.scrollTop = el.scrollHeight;
          } catch (e) {}
        }

        function clearLogBox() {
          const el = document.getElementById("logBox");
          if (el) el.textContent = "";
        }

        tickCountdowns();
        setInterval(tickCountdowns, 1000);

        refreshOdds();
        setInterval(refreshOdds, 7000);

        fetchLogs(true);
        setInterval(fetchLogs, 2000);
      </script>
    </body>
    </html>
    """

    return HTMLResponse(html)


@app.get("/login")
async def login_get(request: Request):
    if is_logged_in(request):
        return RedirectResponse("/", status_code=303)
    return render_login_page()


@app.post("/login")
async def login_post(request: Request, username: str = Form(...), password: str = Form(...)):
    if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
        request.session["user"] = "admin"
        return RedirectResponse("/", status_code=303)
    return render_login_page("Invalid username or password.")


@app.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)


@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    redirect = require_login(request)
    if redirect:
        return redirect
    return render_dashboard()


@app.post("/update_settings")
async def update_settings(
    request: Request,
    starting_bank: str = Form(...),
    current_bank: str = Form(...),
    stake_percent: str = Form(...),
    seconds_before_off: str = Form("60"),
    profile: str = Form(None),
    reset_bank: str = Form(None),
):
    redirect = require_login(request)
    if redirect:
        return redirect

    try:
        sb = float(starting_bank)
    except Exception:
        sb = float(getattr(state, "starting_bank", 100.0) or 100.0)

    try:
        cb = float(current_bank)
    except Exception:
        cb = float(getattr(state, "bank", sb) or sb)

    try:
        sp = float(stake_percent)
    except Exception:
        sp = float(getattr(state, "stake_percent", 5.0) or 5.0)

    if profile in ("2", "5", "10", "15", "20"):
        sp = float(profile)

    try:
        sbo = int(float(seconds_before_off))
    except Exception:
        sbo = int(getattr(state, "seconds_before_off", 60) or 60)

    state.starting_bank = sb
    state.bank = sb if reset_bank else cb
    state.stake_percent = sp
    state.seconds_before_off = sbo

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
    assert runner is not None
    runner.start()
    return render_dashboard("Bot started.")


@app.post("/stop")
async def stop_bot(request: Request):
    redirect = require_login(request)
    if redirect:
        return redirect

    get_client()
    assert runner is not None
    runner.stop()
    return render_dashboard("Bot stopped.")


@app.get("/inspect_hurdles")
async def inspect_hurdles(request: Request):
    redirect = require_login(request)
    if redirect:
        return redirect

    client = get_client()
    markets = client.get_todays_novice_hurdle_markets()

    items = "".join(
        f"<li>{m.get('name','?')} "
        f"<span style='color:#9ca3af;'>({m.get('market_id','?')})</span></li>"
        for m in markets
    )

    html = f"""
    <html>
      <head>
        <meta name="viewport" content="width=device-width, initial-scale=1" />
        <title>Inspect Markets</title>
      </head>
      <body style="font-family:system-ui;background:#020617;color:#e5e7eb;padding:14px;max-width:100%;overflow-x:hidden;">
        <h2>Inspect Markets</h2>
        <p><a href="/" style="color:#38bdf8;">Back</a></p>
        <p>Dummy mode: <b>{"ON" if USE_DUMMY else "OFF"}</b></p>
        <ul>{items}</ul>
      </body>
    </html>
    """
    return HTMLResponse(html)


@app.get("/api/selected_live_odds")
async def api_selected_live_odds(request: Request):
    redirect = require_login(request)
    if redirect:
        return JSONResponse({"detail": "Unauthorized"}, status_code=401)

    client = get_client()

    bank = float(getattr(state, "bank", 100.0) or 100.0)
    stake_percent = float(getattr(state, "stake_percent", 5.0) or 5.0)
    total_stake = bank * (stake_percent / 100.0)

    rows = []
    for mid in getattr(state, "selected_markets", []) or []:
        try:
            favs = client.get_top_two_favourites(mid)
            if len(favs) < 2:
                continue

            o1 = float(favs[0]["back"])
            o2 = float(favs[1]["back"])
            calc = _dutch_stakes(total_stake, o1, o2)

            rows.append(
                {
                    "market_id": mid,
                    "race": client.get_market_name(mid),
                    "start_raw": _start_time_iso_z(client, mid),
                    "fav1": {"name": favs[0].get("name", "—"), "selection_id": favs[0].get("selection_id")},
                    "fav2": {"name": favs[1].get("name", "—"), "selection_id": favs[1].get("selection_id")},
                    "odds1": o1,
                    "odds2": o2,
                    "total_stake": total_stake,
                    "stake1": calc["stake1"],
                    "stake2": calc["stake2"],
                    "profit_if_win": calc["profit_each"],
                }
            )
        except Exception as e:
            rows.append({"market_id": mid, "error": str(e)})

    return JSONResponse({"rows": rows})


@app.get("/api/logs")
async def api_logs(request: Request, n: int = 250):
    redirect = require_login(request)
    if redirect:
        return JSONResponse({"detail": "Unauthorized"}, status_code=401)

    try:
        n = int(n)
    except Exception:
        n = 250
    n = max(1, min(n, 800))

    lines = list(LOG_BUFFER)[-n:]
    return JSONResponse({"lines": lines})

