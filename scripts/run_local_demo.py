"""Run the ingest server on localhost for a live walkthrough.

    python scripts/run_local_demo.py            # terminal 1 -- the server
    python scripts/send_demo_event.py           # terminal 2 -- post a webhook

Then open http://localhost:8000/docs

WHY THIS IS NOT `run_ingest.py`
--------------------------------
`run_ingest.py` declares `transport="real"`, because it is the one entry point
that knows bytes arrived from Razorpay over a live tunnel. Pointing it at a
hand-built payload would write ledger rows labelled `real` that Razorpay never
sent -- manufactured evidence, and the exact INC-006 failure this repository
exists to prevent. So this server declares `transport="sim"` and says so on
the console, and `require_declared_split()` will refuse to pool these rows with
any real ones.

The demo secret below is a LOCAL DEMO CONSTANT, not a credential. It is not the
Razorpay webhook secret, it protects nothing, and it is committed on purpose so
the sender and the server agree without anyone editing `.env` before a demo.
"""

import contextlib
import sys
from pathlib import Path

import uvicorn
from fastapi.responses import HTMLResponse

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from recoup.ingest.app import create_app  # noqa: E402

DEMO_SECRET = "local-demo-secret-not-a-credential"  # noqa: S105 - see module docstring
DEMO_DB = REPO / "runs" / "demo" / "localhost.db"

PAGE = """<!doctype html>
<title>recoup — ingest (local demo)</title>
<style>
  :root {{ color-scheme: dark light; }}
  body {{ font: 15px/1.6 ui-monospace, SFMono-Regular, Menlo, monospace;
         max-width: 46rem; margin: 3rem auto; padding: 0 1.5rem; }}
  h1 {{ font-size: 1.3rem; margin-bottom: .2rem; }}
  .sub {{ opacity: .7; margin-top: 0; }}
  .tag {{ display: inline-block; border: 1px solid currentColor; border-radius: 3px;
          padding: 0 .4rem; font-size: .8rem; }}
  .sim {{ color: #d08c30; }}
  table {{ border-collapse: collapse; margin: 1.2rem 0; width: 100%; }}
  td, th {{ text-align: left; padding: .35rem .6rem .35rem 0; vertical-align: top; }}
  th {{ opacity: .6; font-weight: normal; width: 11rem; }}
  a {{ color: inherit; }}
  .note {{ opacity: .75; border-left: 2px solid currentColor; padding-left: .9rem;
           margin: 1.5rem 0; }}
  code {{ opacity: .85; }}
</style>
<h1>recoup — ingest</h1>
<p class="sub">post-halt subscription payment recovery · Razorpay AI Buildathon 2026</p>

<p><span class="tag sim">transport = sim</span></p>

<table>
  <tr><th>POST /webhook</th><td>signature-verified, ACKs 2xx fast, work happens after</td></tr>
  <tr><th>GET /health</th><td><a href="/health">/health</a></td></tr>
  <tr><th>GET /docs</th><td><a href="/docs">OpenAPI — try the endpoints here</a></td></tr>
  <tr><th>ledger rows</th><td>{rows}</td></tr>
  <tr><th>database</th><td><code>{db}</code></td></tr>
</table>

<p class="note">
  Rows written here are labelled <b>sim</b>, not <b>real</b>. The handler cannot
  tell a live Razorpay webhook from a replayed fixture — the bytes are identical
  by design — so the label comes from the entry point, and only
  <code>run_ingest.py</code> behind a live tunnel may declare <b>real</b>.
  <code>sim</code> and <code>real</code> are never pooled in a reported number.
</p>

<p class="note">
  Send three events — valid, redelivered, forged signature:<br>
  <code>python scripts/send_demo_event.py</code>
</p>
"""


def build():
    """Build the app. Deliberately NOT called at import time.

    The sender imports DEMO_SECRET and DEMO_DB from this module. If building
    happened at import, that import would delete the database out from under the
    running server -- so the side effect lives behind __main__ and importing
    this module does nothing.
    """
    DEMO_DB.parent.mkdir(parents=True, exist_ok=True)
    if DEMO_DB.exists():
        try:
            DEMO_DB.unlink()  # a fresh chain each demo, so seq 1 is genuinely seq 1
        except PermissionError:
            # Windows holds the file open for the running server. Bare, this
            # surfaces as a traceback on startup, which during a demo reads as
            # "the project is broken" rather than "you already have one running".
            raise SystemExit(
                "\n  A demo server is already running and holding:\n"
                f"    {DEMO_DB}\n\n"
                "  Stop it with Ctrl-C in its terminal, then start this again.\n"
            ) from None
    app = create_app(
        db_path=str(DEMO_DB),
        webhook_secret=DEMO_SECRET,
        run_id="localhost-demo",
        transport="sim",
    )
    _add_landing_page(app)
    return app


def _add_landing_page(app) -> None:
    """A `/` for the demo only. The shipped service deliberately has none.

    `recoup` is a webhook receiver, not a website: the routes that exist are the
    ones Razorpay posts to. Adding a root route to `ingest/app.py` would add
    surface to the real service purely so a browser tab looks tidier, so it goes
    on the demo wrapper instead and the shipped app is untouched.
    """

    @app.get("/", response_class=HTMLResponse)
    async def index() -> str:
        rows = 0
        with contextlib.suppress(Exception):
            rows = app.state.conn.execute("SELECT COUNT(*) FROM ledger").fetchone()[0]
        return PAGE.format(rows=rows, db=DEMO_DB)


if __name__ == "__main__":
    app = build()
    print("=" * 74)
    print("  recoup ingest -- LOCAL DEMO SERVER")
    print("=" * 74)
    print("  transport : sim   <- these rows are NOT labelled real, by design")
    print(f"  database  : {DEMO_DB}")
    print("  docs      : http://localhost:8000/docs")
    print("  health    : http://localhost:8000/health")
    print()
    print("  In another terminal:  python scripts/send_demo_event.py")
    print("=" * 74)
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="info")
