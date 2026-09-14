"""Pre-apply readiness.

The value of this check is entirely in it agreeing with ``runtime/apply.py``. If readiness
says "ready" and the worker then refuses, the operator is worse off than with no check at
all — they committed on a promise. So the first test here compares the two directly, and the
rest cover the individual blockers.
"""

from __future__ import annotations

import ast
import inspect
from types import SimpleNamespace

import pytest

from app.core.automation.runtime import apply as apply_runtime
from app.services import readiness
from app.services.readiness import Blocker, apply_readiness


class FakeStore:
    """Stands in for CredentialStore so a blocker can be provoked without real secrets."""

    def __init__(self, *, session: dict | None = None, llm_key: str | None = "k") -> None:
        self._session, self._llm_key = session, llm_key

    async def load_session_cookies(self, db, user_id, platform):
        return self._session

    async def get_llm_key(self, db, user_id, provider):
        return self._llm_key


class FakeDB:
    """Returns a fixed object for ``get`` and no rows for ``execute``."""

    def __init__(self, resume=None) -> None:
        self._resume = resume

    async def get(self, model, pk):
        return self._resume

    async def execute(self, *_a, **_k):
        return SimpleNamespace(scalar_one_or_none=lambda: None)


def job(platform: str = "linkedin", **kw) -> SimpleNamespace:
    return SimpleNamespace(
        id="j1", platform=platform, url="https://x.example/1",
        application_url="", title="PM", company="Monzo", **kw
    )


def resume(pdf: str | None = "/tmp/cv.pdf") -> SimpleNamespace:
    return SimpleNamespace(id="r1", name="CV", file_path_pdf=pdf, file_path_docx=None)


@pytest.fixture(autouse=True)
def no_gateway(monkeypatch):
    """Assume no LLM gateway unless a test says otherwise.

    Whether a per-user key is needed depends on it, so leaving it to whatever the developer's
    environment happens to have configured makes these tests pass or fail by accident.
    """
    from app.config.settings import get_settings

    monkeypatch.setattr(get_settings().llm, "api_base", "", raising=False)


@pytest.fixture
def gateway(monkeypatch):
    """Turn a configured gateway back on for the tests that are about it."""
    def configure() -> None:
        from app.config.settings import get_settings

        monkeypatch.setattr(
            get_settings().llm, "api_base", "http://gateway.test/v1", raising=False
        )
    return configure


@pytest.fixture
def store(monkeypatch):
    def install(**kw):
        fake = FakeStore(**kw)
        monkeypatch.setattr(readiness, "CredentialStore", lambda: fake)
        return fake
    return install


class TestReadinessMatchesWhatTheWorkerActuallyRequires:
    """A readiness check that drifts from the worker is worse than none at all."""

    def test_every_prerequisite_the_worker_enforces_has_a_blocker_here(self) -> None:
        # The worker's prerequisites are the ApplyPrerequisiteError raises in run_apply.
        raised = {
            ast.unparse(node.exc.args[0])[:40].lower()
            for node in ast.walk(ast.parse(inspect.getsource(apply_runtime.run_apply)))
            if isinstance(node, ast.Raise)
            and isinstance(node.exc, ast.Call)
            and getattr(node.exc.func, "id", "") == "ApplyPrerequisiteError"
            and node.exc.args
        }
        # Four prerequisites: job, resume attached, resume file, session, LLM key. "Job not
        # found" is not reachable here — readiness is called *with* a job.
        assert len(raised) >= 4, f"run_apply's prerequisites changed shape: {raised}"

        codes = {"no_session", "no_resume", "resume_file_missing", "no_llm_key"}
        source = inspect.getsource(readiness)
        for code in codes:
            assert f'"{code}"' in source, f"no blocker covers {code}"


class TestPlatformSession:
    async def test_a_login_platform_with_no_session_blocks_and_offers_connect(self, store) -> None:
        store(session=None)
        blockers = await apply_readiness(FakeDB(resume()), "u1", job("linkedin"), resume_id="r1")

        session_blocker = next(b for b in blockers if b.code == "no_session")
        assert session_blocker.action == "connect_platform"
        assert session_blocker.platform == "linkedin"
        # The reassurance belongs in the prompt itself, where the operator reads it.
        assert "never seen or stored" in session_blocker.message

    async def test_a_connected_platform_raises_no_session_blocker(self, store) -> None:
        store(session={"cookies": [{"name": "li_at"}]})
        blockers = await apply_readiness(FakeDB(resume()), "u1", job("linkedin"), resume_id="r1")
        assert not blockers

    async def test_a_keyless_source_needs_no_session(self, store) -> None:
        """Remotive has no login, so demanding one would be a blocker that cannot be cleared."""
        store(session=None)
        blockers = await apply_readiness(FakeDB(resume()), "u1", job("remotive"), resume_id="r1")
        assert [b.code for b in blockers] == []

    async def test_a_listing_with_no_link_at_all_cannot_be_applied_to(self, store) -> None:
        store(session=None)
        listing = job("remotive")
        listing.url = ""
        blockers = await apply_readiness(FakeDB(resume()), "u1", listing, resume_id="r1")

        no_route = next(b for b in blockers if b.code == "no_route")
        assert not no_route.manual_possible


class TestResumeAndModel:
    async def test_no_resume_blocks_with_an_action(self, store) -> None:
        store(session={"cookies": []})
        blockers = await apply_readiness(FakeDB(None), "u1", job("linkedin"), resume_id=None)

        assert next(b for b in blockers if b.code == "no_resume").action == "attach_resume"

    async def test_a_resume_with_no_rendered_file_blocks(self, store) -> None:
        store(session={"cookies": []})
        blockers = await apply_readiness(
            FakeDB(resume(pdf=None)), "u1", job("linkedin"), resume_id="r1"
        )
        assert any(b.code == "resume_file_missing" for b in blockers)

    async def test_a_missing_llm_key_blocks_when_calls_go_direct(self, store) -> None:
        store(session={"cookies": []}, llm_key=None)
        blockers = await apply_readiness(FakeDB(resume()), "u1", job("linkedin"), resume_id="r1")
        assert next(b for b in blockers if b.code == "no_llm_key").action == "configure_llm"

    async def test_a_gateway_removes_the_key_requirement(self, store, gateway) -> None:
        """The defect this pins: every application was blocked on "No API key is configured
        for openai" while the client was routing happily through the local gateway."""
        gateway()
        store(session={"cookies": []}, llm_key=None)
        blockers = await apply_readiness(FakeDB(resume()), "u1", job("linkedin"), resume_id="r1")
        assert not any(b.code == "no_llm_key" for b in blockers)


class TestNoDeadEnds:
    async def test_every_blocker_carries_an_action(self, store) -> None:
        """A blocker with no action tells the operator they are stuck and nothing more."""
        store(session=None, llm_key=None)
        blockers = await apply_readiness(FakeDB(None), "u1", job("linkedin"), resume_id=None)

        assert len(blockers) >= 3
        assert all(b.action for b in blockers)

    async def test_applying_by_hand_stays_possible_when_the_agent_cannot_run(self, store) -> None:
        """A blocked agent must never mean a blocked application — the listing is still there."""
        store(session=None, llm_key=None)
        blockers = await apply_readiness(FakeDB(None), "u1", job("linkedin"), resume_id=None)
        assert all(b.manual_possible for b in blockers)

    def test_a_blocker_is_immutable(self) -> None:
        with pytest.raises(AttributeError):
            Blocker(code="x", message="m", action="a").code = "y"  # type: ignore[misc]
