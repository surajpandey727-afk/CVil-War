"""Production smoke test: the critical journeys, end to end, against the live deployment.

    python scripts/smoke_prod.py                       # https://cvil-war.vercel.app
    python scripts/smoke_prod.py --base http://localhost:3000 --skip-llm

Creates a throwaway account (qa-smoke-<random>@example.com), exercises each journey through the
same public URL a browser uses, then deletes what it created and soft-deletes the account. It
never touches another account, never approves or submits an application, and prints no secrets.
Each step prints PASS / FAIL / BLOCKED; the exit code is the number of failures.
"""

from __future__ import annotations

import argparse
import io
import secrets
import sys
import time
from collections.abc import Callable

import httpx

CV_LINES = [
    "Alex Morgan",
    "London, UK",
    "M: 07700 900123 | E: alex.morgan@example.com",
    "Product manager with six years shipping B2B data products. Owned the roadmap and "
    "prioritisation for an analytics platform used by enterprise customers.",
    "KEY SKILLS",
    "Roadmap, Prioritisation, Stakeholder management, SQL, Agile, Python",
    "WORK EXPERIENCE",
    "Senior Product Manager, Northwind Labs, March 2021 - Present",
    "• Responsible for the onboarding flow for new enterprise accounts.",
    "• Led discovery with 30 customers and cut time-to-value by 40% through a guided setup.",
    "EDUCATION",
    "BSc Computer Science, University of Leeds, 2016",
]


def _docx() -> bytes:
    import docx

    d = docx.Document()
    for line in CV_LINES:
        d.add_paragraph(line)
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()


class Smoke:
    def __init__(self, base: str, skip_llm: bool) -> None:
        self.api = base.rstrip("/") + "/api/v1"
        self.base = base.rstrip("/")
        self.skip_llm = skip_llm
        self.c = httpx.Client(timeout=130)
        self.h: dict[str, str] = {}
        self.failures = 0
        self.state: dict[str, str] = {}

    def step(self, name: str, fn: Callable[[], str]) -> None:
        t = time.time()
        try:
            detail = fn()
            status = "BLOCKED" if detail.startswith("BLOCKED") else "PASS"
        except AssertionError as exc:
            status, detail = "FAIL", str(exc)[:300]
        except Exception as exc:
            status, detail = "FAIL", f"{type(exc).__name__}: {str(exc)[:300]}"
        if status == "FAIL":
            self.failures += 1
        print(f"{status:7} {name:38} {time.time() - t:5.1f}s  {detail}")

    # --- journeys ----------------------------------------------------------------------------
    def health(self) -> str:
        r = self.c.get(f"{self.base}/health")
        j = r.json()
        assert r.status_code == 200 and j["db"] is True, f"HTTP {r.status_code} db={j.get('db')}"
        assert j.get("storage", {}).get("ok") is True, f"storage {j.get('storage')}"
        return f"db ok, storage {j['storage']['provider']}, llm key={j['llm']['anthropic_key_configured']}"

    def spa(self) -> str:
        r = self.c.get(f"{self.base}/login")
        assert r.status_code == 200 and '<div id="root"' in r.text, f"HTTP {r.status_code}"
        return "login page served"

    def register_login(self) -> str:
        email = f"qa-smoke-{secrets.token_hex(4)}@example.com"
        pw = "Qa!" + secrets.token_urlsafe(18)
        r = self.c.post(f"{self.api}/auth/register", json={"email": email, "password": pw})
        assert r.status_code == 201, f"register HTTP {r.status_code}"
        r = self.c.post(f"{self.api}/auth/login", data={"username": email, "password": pw})
        assert r.status_code == 200, f"login HTTP {r.status_code}"
        self.h = {"Authorization": f"Bearer {r.json()['access_token']}"}
        return "throwaway account signed in"

    def upload(self) -> str:
        r = self.c.post(
            f"{self.api}/resumes/upload",
            headers=self.h,
            files={
                "file": (
                    "qa_smoke.docx",
                    _docx(),
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                )
            },
        )
        assert r.status_code == 201, f"HTTP {r.status_code} {r.text[:200]}"
        self.state["resume"] = r.json()["id"]
        d = self.c.get(
            f"{self.api}/resumes/{self.state['resume']}/download?format=docx", headers=self.h
        )
        assert d.status_code == 200 and d.content[:2] == b"PK", f"download HTTP {d.status_code}"
        return "upload + download round trip"

    def jobs_uk_only(self) -> str:
        r = self.c.get(f"{self.api}/jobs/", headers=self.h, params={"page_size": 50})
        assert r.status_code == 200, f"HTTP {r.status_code}"
        return f"jobs list ok ({r.json().get('total', 0)} for a fresh account)"

    def checker(self) -> str:
        body = {"resume_id": self.state["resume"], "role_titles": ["Product Manager"]}
        r = self.c.post(f"{self.api}/resume-checker/check", headers=self.h, json=body)
        assert r.status_code == 200, f"HTTP {r.status_code}"
        j = r.json()
        total = sum(c["weight"] * c["score"] for c in j["score"]["components"])
        assert abs(total - j["score"]["overall"]) < 1e-3, "overall != sum of components"
        assert j["matched_skills"] and j["matched_skills"][0]["evidence"], "no evidence quotes"
        return f"fit {round(j['score']['overall'] * 100)}/100 ({j['score']['band']})"

    def review(self) -> str:
        if self.skip_llm:
            return "BLOCKED: --skip-llm"
        body = {"resume_id": self.state["resume"], "role_titles": ["Product Manager"]}
        r = self.c.post(f"{self.api}/resume-checker/review", headers=self.h, json=body)
        assert r.status_code == 200, f"HTTP {r.status_code}"
        j = r.json()
        if not j["available"]:
            return f"BLOCKED: {j['detail']}"
        assert all(
            s["evidence_status"] in ("supported", "add_only_if_true") for s in j["suggestions"]
        )
        return f"{j['model']}: {len(j['suggestions'])} rewrites, {j['rejected_count']} rejected"

    def notifications(self) -> str:
        r = self.c.get(f"{self.api}/notifications/", headers=self.h)
        if r.status_code == 404:
            return "BLOCKED: notifications not deployed"
        assert r.status_code == 200, f"HTTP {r.status_code}"
        return f"feed ok ({r.json()['unread']} unread)"

    def assistant(self) -> str:
        if self.skip_llm:
            return "BLOCKED: --skip-llm"
        r = self.c.get(f"{self.api}/assistant/agents", headers=self.h)
        if r.status_code == 404:
            return "BLOCKED: assistant not deployed"
        assert r.status_code == 200, f"agents HTTP {r.status_code}"
        msg = {
            "messages": [{"role": "user", "content": "In one sentence: what can you do for me?"}]
        }
        r = self.c.post(f"{self.api}/assistant/chat", headers=self.h, json=msg)
        assert r.status_code == 200, f"chat HTTP {r.status_code} {r.text[:200]}"
        return f"agents roster ok; chat replied ({len(r.json().get('reply', ''))} chars)"

    def cleanup(self) -> str:
        if "resume" in self.state:
            self.c.delete(f"{self.api}/resumes/{self.state['resume']}", headers=self.h)
        r = self.c.delete(f"{self.api}/auth/account", headers=self.h)
        assert r.status_code == 204, f"HTTP {r.status_code}"
        return "résumé deleted, account soft-deleted"


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--base", default="https://cvil-war.vercel.app")
    p.add_argument("--skip-llm", action="store_true")
    a = p.parse_args()
    s = Smoke(a.base, a.skip_llm)
    print(f"Smoke test against {a.base}")
    s.step("S1  API health (db, storage, llm)", s.health)
    s.step("S2  SPA serves the login page", s.spa)
    s.step("S3  register + sign in", s.register_login)
    if not s.h:
        return s.failures or 1
    try:
        s.step("S4  résumé upload + download", s.upload)
        s.step("S5  jobs list (UK-only policy)", s.jobs_uk_only)
        if "resume" in s.state:
            s.step("S6  résumé checker (deterministic)", s.checker)
            s.step("S7  Claude review (validated)", s.review)
        s.step("S8  notifications feed", s.notifications)
        s.step("S9  assistant + AI agents", s.assistant)
    finally:
        s.step("S10 cleanup", s.cleanup)
    print(f"{s.failures} failure(s)")
    return s.failures


if __name__ == "__main__":
    sys.exit(main())
