#!/usr/bin/env python
"""Whole-system verification harness.

Runs every check the project has — lint, types, unit, integration, end-to-end, production
build, and live probes against the running stack and the real job sources — and reports one
table saying what actually works.

Three properties matter, each because the alternative has already misled us in this project:

**Stages are isolated.** A failing stage never aborts the run. Discovering that the frontend
builds *and* that three adapters are down in one pass is worth far more than stopping at the
first red line, and a crash-on-first-failure harness quietly hides everything downstream.

**A green build is not a green system.** `npm run build` passed while job search returned zero
results for every query, and 748 unit tests passed while an assessment due in three hours
ranked below an interview a day away. So the live stages here exercise the real HTTP API and
the real upstream boards, not mocks.

**Failures are attributed, not just counted.** Each stage records the first genuinely
diagnostic line of its output, so the summary points at a cause rather than announcing that
something, somewhere, is broken.

Usage::

    python scripts/verify.py              # everything
    python scripts/verify.py --quick      # skip network + live stages
    python scripts/verify.py --loop 3     # repeat, to expose flakiness
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend"

#: Resolved lazily so the harness runs from any checkout without editing.
PYTHON = Path("C:/Users/SurajPandey/.venvs/autoapply/Scripts/python.exe")
if not PYTHON.exists():
    PYTHON = Path(sys.executable)

API = "http://127.0.0.1:8000"
WEB = "http://localhost:3000"

GREEN, RED, YELLOW, DIM, RESET = "\033[32m", "\033[31m", "\033[33m", "\033[2m", "\033[0m"


@dataclass
class Result:
    name: str
    ok: bool
    detail: str = ""
    seconds: float = 0.0
    #: False for stages whose failure is environmental rather than a defect (no server
    #: running, no network). They are reported but do not fail the run.
    critical: bool = True
    skipped: bool = False


@dataclass
class Report:
    results: list[Result] = field(default_factory=list)

    def add(self, r: Result) -> Result:
        icon = (
            f"{YELLOW}SKIP{RESET}" if r.skipped else f"{GREEN}PASS{RESET}" if r.ok else f"{RED}FAIL{RESET}"
        )
        print(f"  [{icon}] {r.name:38} {r.seconds:6.1f}s  {r.detail[:70]}")
        self.results.append(r)
        return r

    @property
    def failures(self) -> list[Result]:
        return [r for r in self.results if not r.ok and not r.skipped and r.critical]


def run(cmd: list[str] | str, cwd: Path, timeout: int = 1800) -> tuple[int, str]:
    """Run a command, returning (exit code, combined output). Never raises."""
    try:
        proc = subprocess.run(
            cmd,
            cwd=cwd,
            shell=isinstance(cmd, str),
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding="utf-8",
            errors="replace",
        )
        return proc.returncode, (proc.stdout or "") + (proc.stderr or "")
    except subprocess.TimeoutExpired:
        return 124, f"timed out after {timeout}s"
    except FileNotFoundError as exc:
        return 127, str(exc)


def first_diagnostic(output: str) -> str:
    """Pull the most explanatory line out of a tool's output.

    Test runners bury the cause under progress bars and stack frames; a summary that just
    says "pytest failed" sends you back to re-run it by hand, which is the toil this exists
    to remove.
    """
    patterns = (
        r"^FAILED .*", r"^E\s+\w+Error.*", r"^\s*✕.*", r"^error[: ].*",
        r"^.*\berror TS\d+.*", r"^\s*→ .*", r"^[A-Z]{1,5}\d{3,4} .*",
    )
    for line in output.splitlines():
        for pattern in patterns:
            if re.match(pattern, line.strip(), re.IGNORECASE):
                return line.strip()
    tail = [ln for ln in output.strip().splitlines() if ln.strip()]
    return tail[-1][:120] if tail else "no output"


def http_json(url: str, token: str | None = None, timeout: int = 60) -> tuple[int, object]:
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as exc:
        return exc.code, {}
    except Exception as exc:
        return 0, {"error": str(exc)}


# ---------------------------------------------------------------------------------------
# Stages
# ---------------------------------------------------------------------------------------


def stage_backend(report: Report) -> None:
    print(f"\n{DIM}BACKEND{RESET}")

    t = time.time()
    code, out = run([str(PYTHON), "-m", "ruff", "check", "app/"], BACKEND, 300)
    report.add(Result("ruff check app/", code == 0, "" if code == 0 else first_diagnostic(out), time.time() - t))

    t = time.time()
    code, out = run(
        [str(PYTHON), "-m", "pytest", "tests/", "-q", "--no-header", "-p", "no:cacheprovider"],
        BACKEND,
        1800,
    )
    counts = re.search(r"(\d+) passed", out)
    failed = re.search(r"(\d+) failed", out)
    detail = f"{counts.group(1) if counts else '?'} passed"
    if failed:
        detail += f", {failed.group(1)} FAILED — {first_diagnostic(out)}"
    report.add(Result("pytest (unit+integration+e2e)", code == 0, detail, time.time() - t))


def stage_frontend(report: Report) -> None:
    print(f"\n{DIM}FRONTEND{RESET}")

    for name, cmd, timeout in (
        ("tsc --noEmit (types)", "npx tsc --noEmit", 900),
        ("eslint (0 warnings)", "npm run lint", 900),
        ("vite build (production)", "npm run build", 900),
    ):
        t = time.time()
        code, out = run(cmd, FRONTEND, timeout)
        report.add(Result(name, code == 0, "" if code == 0 else first_diagnostic(out), time.time() - t))

    t = time.time()
    code, out = run("npx vitest run --reporter=basic", FRONTEND, 1800)
    passed = re.search(r"(\d+) passed", out)
    failed = re.search(r"(\d+) failed", out)
    detail = f"{passed.group(1) if passed else '?'} passed"
    if failed:
        detail += f", {failed.group(1)} FAILED — {first_diagnostic(out)}"
    report.add(Result("vitest (component+page)", code == 0, detail, time.time() - t))


def stage_migrations(report: Report) -> None:
    print(f"\n{DIM}DATABASE{RESET}")
    t = time.time()
    code, out = run([str(PYTHON), "-m", "alembic", "current"], BACKEND, 300)
    head = re.search(r"([0-9a-f]{6,}|\d{4})\s*\(head\)", out)
    report.add(
        Result(
            "alembic at head",
            code == 0 and "(head)" in out,
            head.group(1) if head else first_diagnostic(out),
            time.time() - t,
        )
    )


def stage_live_api(report: Report, token: str | None) -> None:
    """Probe the running stack. A green build says nothing about a running system."""
    print(f"\n{DIM}LIVE API{RESET}")

    t = time.time()
    status, body = http_json(f"{API}/health", timeout=10)
    up = status == 200
    if not up:
        report.add(Result("backend reachable", False, "not running — start uvicorn", time.time() - t, critical=False, skipped=True))
        return
    db_ok = bool(isinstance(body, dict) and body.get("db"))
    report.add(Result("GET /health (db connected)", db_ok, json.dumps(body)[:60], time.time() - t))

    if not token:
        report.add(Result("authenticated endpoints", False, "no token minted", 0.0, critical=False, skipped=True))
        return

    checks: list[tuple[str, str, callable]] = [
        ("GET /sources", f"{API}/api/v1/sources/", lambda b: len(b.get("live_keys", [])) > 0),
        ("GET /jobs", f"{API}/api/v1/jobs/?page=1&page_size=1", lambda b: "total" in b),
        ("GET /command-centre/summary", f"{API}/api/v1/command-centre/summary", lambda b: "needs_attention" in b),
        ("GET /command-centre/queue", f"{API}/api/v1/command-centre/queue", lambda b: "items" in b),
        ("GET /analytics/dashboard", f"{API}/api/v1/analytics/dashboard", lambda b: isinstance(b, dict)),
        ("GET /settings", f"{API}/api/v1/settings/", lambda b: isinstance(b, dict)),
        # The automation policy catalogue. Checked live because it is what the automation
        # screen renders itself from — an empty catalogue would present a system with no
        # rules, which is indistinguishable on screen from one that permits everything.
        (
            "GET /settings/automation-policy",
            f"{API}/api/v1/settings/automation-policy",
            lambda b: bool(b.get("groups")) and bool(b["groups"][0].get("rules")),
        ),
    ]
    for name, url, predicate in checks:
        t = time.time()
        status, body = http_json(url, token)
        ok = status == 200 and isinstance(body, dict) and predicate(body)
        detail = f"HTTP {status}"
        if ok and "live_keys" in body:
            detail = f"{len(body['live_keys'])} live sources"
        elif ok and "total" in body:
            detail = f"total={body['total']}"
        elif ok and "needs_attention" in body:
            detail = f"needs_attention={body['needs_attention']}"
        report.add(Result(name, ok, detail, time.time() - t))


def stage_live_sources(report: Report) -> None:
    """Probe the upstream boards themselves — the layer most likely to change under us."""
    print(f"\n{DIM}UPSTREAM JOB SOURCES (network){RESET}")
    # Written to a file rather than passed with -c: statements separated by ';' cannot be
    # followed by a compound `async def` block, so the one-liner form was a SyntaxError.
    probe = '''
import asyncio, json, logging
logging.disable(logging.CRITICAL)
from app.core.automation.platforms import platform_registry
from app.core.job_discovery.sources import IMPLEMENTED_KEYS


async def main():
    out = {}
    for key in sorted(IMPLEMENTED_KEYS):
        try:
            found = await platform_registry.create(key).search(
                query="engineer", location="", filters={"limit": 25}
            )
            out[key] = len(found)
        except Exception:
            out[key] = -1
    print("RESULT" + json.dumps(out))


asyncio.run(main())
'''
    probe_path = BACKEND / ".verify_probe.py"
    probe_path.write_text(probe, encoding="utf-8")
    t = time.time()
    try:
        code, out = run([str(PYTHON), str(probe_path)], BACKEND, 900)
    finally:
        probe_path.unlink(missing_ok=True)
    match = re.search(r"RESULT(\{.*\})", out)
    if not match:
        report.add(Result("job source probe", False, first_diagnostic(out), time.time() - t, critical=False))
        return
    counts: dict[str, int] = json.loads(match.group(1))
    live = {k: v for k, v in counts.items() if v > 0}
    dead = {k: v for k, v in counts.items() if v <= 0}
    report.add(
        Result(
            "adapters returning results",
            len(live) >= 4,  # below this, discovery is effectively down
            f"{len(live)}/{len(counts)} live, {sum(live.values())} jobs"
            + (f" · silent: {', '.join(sorted(dead))}" if dead else ""),
            time.time() - t,
            critical=False,
        )
    )


def mint_token() -> str | None:
    """Mint a short-lived token with the app's own key, so live stages need no password."""
    code, out = run(
        [
            str(PYTHON),
            "-c",
            "import sys;sys.path.insert(0,'.');"
            "from app.core.security import create_access_token;"
            "print('TOKEN'+create_access_token(sub='09cc2dc8a93d4c8897d9def90bc290c8',expires_minutes=30))",
        ],
        BACKEND,
        120,
    )
    match = re.search(r"TOKEN(\S+)", out)
    return match.group(1) if match else None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--quick", action="store_true", help="skip live + network stages")
    parser.add_argument("--loop", type=int, default=1, help="repeat N times to expose flakiness")
    args = parser.parse_args()

    overall = 0
    for iteration in range(1, args.loop + 1):
        started = time.time()
        if args.loop > 1:
            print(f"\n{'=' * 82}\nPASS {iteration}/{args.loop}\n{'=' * 82}")
        else:
            print(f"\n{'=' * 82}\nCVil-War — whole-system verification\n{'=' * 82}")

        report = Report()
        stage_backend(report)
        stage_frontend(report)
        stage_migrations(report)
        if not args.quick:
            stage_live_api(report, mint_token())
            stage_live_sources(report)

        print(f"\n{'=' * 82}")
        passed = sum(1 for r in report.results if r.ok and not r.skipped)
        skipped = sum(1 for r in report.results if r.skipped)
        failures = report.failures
        verdict = f"{GREEN}SYSTEM VERIFIED{RESET}" if not failures else f"{RED}{len(failures)} STAGE(S) FAILING{RESET}"
        print(f"{verdict}  —  {passed} passed, {len(failures)} failed, {skipped} skipped "
              f"in {time.time() - started:.0f}s")
        for r in failures:
            # ASCII marker on purpose: this console is cp1252, and a U+2717 here crashed the
            # harness *while reporting a failure* — the one moment it has to work.
            print(f"  {RED}x{RESET} {r.name}: {r.detail}")
        print("=" * 82)
        overall |= 1 if failures else 0

    return overall


if __name__ == "__main__":
    raise SystemExit(main())
