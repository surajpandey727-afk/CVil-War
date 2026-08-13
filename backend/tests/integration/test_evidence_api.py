"""The application evidence bundle.

The product says ``Applied``. These tests pin the follow-up: applied where, to which job,
using which CV, through which account, at what time, with what result, and what the agent
actually did — and, just as importantly, that anything never recorded says so rather than
rendering a convincing blank.
"""

from __future__ import annotations

import itertools
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from app.models.application import Application
from app.models.application_event import ApplicationEvent
from app.models.enums import (
    ApplicationEventType,
    ApplicationStatus,
    ConfirmationState,
    SessionState,
    SubmissionMethod,
)
from app.models.harness import RunTrajectory
from app.models.job import Job
from app.models.platform_session import PlatformSession
from app.models.resume import Resume
from app.services.evidence import mask_account
from tests.conftest import TEST_USER_ID

API = "/api/v1/applications"
_SEQ = itertools.count(1)


def _job(db, **overrides):  # type: ignore[no-untyped-def]
    data = {
        "id": uuid4().hex,
        "user_id": TEST_USER_ID,
        "platform": "reed",
        "platform_job_id": f"j{next(_SEQ)}",
        "title": "Senior Product Manager",
        "company": "Zartis",
        "location": "London, UK",
        "url": "https://www.reed.co.uk/jobs/senior-product-manager/56654149",
        "description": "",
        "salary_range": "£75,000 - £95,000",
        "status": "new",
    }
    job = Job(**{**data, **overrides})
    db.add(job)
    return job


def _resume(db, **overrides):  # type: ignore[no-untyped-def]
    data = {
        "id": uuid4().hex,
        "user_id": TEST_USER_ID,
        "name": "AI Product Manager CV",
        "type": "tailored",
        "template_id": "modern",
        "ats_score": 0.88,
        "file_path_pdf": f"users/{TEST_USER_ID}/resumes/cv.pdf",
    }
    resume = Resume(**{**data, **overrides})
    db.add(resume)
    return resume


def _application(db, job, resume=None, **overrides):  # type: ignore[no-untyped-def]
    data = {
        "id": uuid4().hex,
        "user_id": TEST_USER_ID,
        "job_id": job.id,
        "resume_id": resume.id if resume else None,
        "apply_mode": "review",
        "status": ApplicationStatus.APPLIED,
        "portal": "reed",
        "applied_at": datetime.now(UTC).replace(tzinfo=None),
    }
    app = Application(**{**data, **overrides})
    db.add(app)
    return app


class TestAccountMasking:
    """Never a credential, and never a full address either."""

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("suraj.pandey@example.com", "sur***@example.com"),
            ("ab@example.com", "a***@example.com"),
            ("not-an-email-at-all", "not***"),
            ("ab", "***"),
            (None, None),
            ("", None),
        ],
    )
    def test_identifiers_are_reduced_to_something_safe(self, raw, expected) -> None:  # type: ignore[no-untyped-def]
        assert mask_account(raw) == expected

    def test_an_unrecognised_format_is_not_passed_through_whole(self) -> None:
        """An unfamiliar shape is not a licence to display all of it."""
        assert mask_account("session-token-abcdef123456") == "ses***"


class TestJobSection:
    async def test_the_posting_and_its_real_url_are_returned(
        self, db_session, current_user, client
    ):
        job = _job(db_session)
        await db_session.commit()
        app = _application(db_session, job)
        await db_session.commit()

        body = (await client.get(f"{API}/{app.id}/evidence")).json()

        assert body["job"]["recorded"] is True
        assert body["job"]["title"] == "Senior Product Manager"
        assert body["job"]["company"] == "Zartis"
        assert body["job"]["location"] == "London, UK"
        assert body["job"]["salary"] == "£75,000 - £95,000"
        assert body["job"]["source"] == "reed"
        assert body["job"]["job_url"].startswith("https://www.reed.co.uk/jobs/")

    async def test_a_missing_job_url_is_reported_as_absent_not_constructed(
        self, db_session, current_user, client
    ):
        """A fabricated URL is worse than none: it looks actionable and goes nowhere."""
        job = _job(db_session, url="")
        await db_session.commit()
        app = _application(db_session, job)
        await db_session.commit()

        body = (await client.get(f"{API}/{app.id}/evidence")).json()
        assert body["job"]["job_url"] is None

    async def test_the_application_url_is_only_reported_when_it_actually_differs(
        self, db_session, current_user, client
    ):
        """Repeating the job URL under a second heading implies a separate application page
        that does not exist."""
        job = _job(db_session)
        await db_session.commit()
        same = _application(db_session, job, application_url=job.url)
        await db_session.commit()
        assert (await client.get(f"{API}/{same.id}/evidence")).json()["job"][
            "application_url"
        ] is None

    async def test_a_genuinely_separate_application_url_is_reported(
        self, db_session, current_user, client
    ):
        job = _job(db_session)
        await db_session.commit()
        app = _application(
            db_session, job, application_url="https://apply.zartis.com/form/9910"
        )
        await db_session.commit()

        body = (await client.get(f"{API}/{app.id}/evidence")).json()
        assert body["job"]["application_url"] == "https://apply.zartis.com/form/9910"


class TestSubmissionSection:
    async def test_a_confirmed_submission_says_so_with_its_reference(
        self, db_session, current_user, client
    ):
        job = _job(db_session)
        await db_session.commit()
        app = _application(
            db_session, job,
            submission_method=SubmissionMethod.AUTOMATED,
            confirmation_state=ConfirmationState.CONFIRMED,
            external_reference="REED-88213",
            confirmation_detail="Application submitted — reference REED-88213",
        )
        await db_session.commit()

        body = (await client.get(f"{API}/{app.id}/evidence")).json()["submission"]

        assert body["status"] == "applied"
        assert body["method"] == "automated"
        assert body["confirmation_state"] == "confirmed"
        assert body["external_reference"] == "REED-88213"
        assert body["actor"] == "agent"

    async def test_a_simulated_run_is_not_presented_as_a_real_submission(
        self, db_session, current_user, client
    ):
        """With live apply disabled nothing is sent anywhere. Reporting that identically to a
        confirmed submission is exactly the "Applied because automation started" problem."""
        job = _job(db_session)
        await db_session.commit()
        app = _application(
            db_session, job,
            submission_method=SubmissionMethod.SIMULATED,
            confirmation_state=ConfirmationState.SIMULATED,
        )
        await db_session.commit()

        body = (await client.get(f"{API}/{app.id}/evidence")).json()["submission"]
        assert body["confirmation_state"] == "simulated"
        assert body["method"] == "simulated"

    async def test_a_run_with_no_confirmation_is_unconfirmed_not_confirmed(
        self, db_session, current_user, client
    ):
        job = _job(db_session)
        await db_session.commit()
        app = _application(
            db_session, job,
            submission_method=SubmissionMethod.AUTOMATED,
            confirmation_state=ConfirmationState.UNCONFIRMED,
        )
        await db_session.commit()

        body = (await client.get(f"{API}/{app.id}/evidence")).json()["submission"]
        assert body["confirmation_state"] == "unconfirmed"
        assert body["external_reference"] is None

    async def test_an_application_predating_run_recording_reports_no_method(
        self, db_session, current_user, client
    ):
        """Historical rows genuinely do not know. "Not recorded" is the honest answer and the
        UI renders it as such — inventing "automated" would be a claim nobody can check."""
        job = _job(db_session)
        await db_session.commit()
        app = _application(
            db_session, job,
            submission_method=SubmissionMethod.NONE,
            confirmation_state=ConfirmationState.UNCONFIRMED,
        )
        await db_session.commit()

        body = (await client.get(f"{API}/{app.id}/evidence")).json()["submission"]
        assert body["method"] is None


class TestDocuments:
    async def test_the_exact_cv_attached_is_reported(
        self, db_session, current_user, client
    ):
        resume = _resume(db_session)
        job = _job(db_session)
        await db_session.commit()
        app = _application(db_session, job, resume)
        await db_session.commit()

        body = (await client.get(f"{API}/{app.id}/evidence")).json()["resume"]

        assert body["recorded"] is True
        assert body["name"] == "AI Product Manager CV"
        assert body["kind"] == "tailored"
        assert body["ats_score"] == 0.88
        assert body["has_pdf"] is True

    async def test_an_application_with_no_cv_says_not_recorded(
        self, db_session, current_user, client
    ):
        job = _job(db_session)
        await db_session.commit()
        app = _application(db_session, job)
        await db_session.commit()

        assert (await client.get(f"{API}/{app.id}/evidence")).json()["resume"][
            "recorded"
        ] is False

    async def test_an_archived_cv_is_still_reported_and_flagged(
        self, db_session, current_user, client
    ):
        resume = _resume(db_session, archived_at=datetime.now(UTC).replace(tzinfo=None))
        job = _job(db_session)
        await db_session.commit()
        app = _application(db_session, job, resume)
        await db_session.commit()

        body = (await client.get(f"{API}/{app.id}/evidence")).json()["resume"]
        assert body["name"] == "AI Product Manager CV"
        assert body["archived"] is True

    async def test_no_cover_letter_is_stated_rather_than_left_blank(
        self, db_session, current_user, client
    ):
        job = _job(db_session)
        await db_session.commit()
        app = _application(db_session, job)
        await db_session.commit()

        body = (await client.get(f"{API}/{app.id}/evidence")).json()["cover_letter"]
        assert body["recorded"] is True
        assert body["used"] is False

    async def test_a_cover_letter_that_was_used_is_named(
        self, db_session, current_user, client
    ):
        job = _job(db_session)
        await db_session.commit()
        app = _application(
            db_session, job,
            cover_letter_path=f"users/{TEST_USER_ID}/letters/zartis-cl-v2.pdf",
        )
        await db_session.commit()

        body = (await client.get(f"{API}/{app.id}/evidence")).json()["cover_letter"]
        assert body["used"] is True
        assert body["name"] == "zartis-cl-v2.pdf"
        assert body["origin"] == "generated"


class TestAccountSection:
    async def test_the_connected_account_is_reported_masked(
        self, db_session, current_user, client
    ):
        db_session.add(
            PlatformSession(
                user_id=TEST_USER_ID,
                platform="reed",
                state=SessionState.SESSION_ACTIVE,
                account_label="sur***@example.com",
                last_used_at=datetime.now(UTC).replace(tzinfo=None),
            )
        )
        job = _job(db_session)
        await db_session.commit()
        app = _application(db_session, job)
        await db_session.commit()

        body = (await client.get(f"{API}/{app.id}/evidence")).json()["account"]

        assert body["platform"] == "reed"
        assert body["account"] == "sur***@example.com"
        assert body["connected"] is True

    async def test_no_credential_ever_appears_in_the_payload(
        self, db_session, current_user, client
    ):
        """A blanket check on the serialised response, not just on the fields we remembered
        to look at — a future field carrying a secret has to fail this."""
        db_session.add(
            PlatformSession(
                user_id=TEST_USER_ID, platform="reed", state=SessionState.SESSION_ACTIVE,
                account_label="sur***@example.com", fingerprint_hash="abc123deadbeef",
            )
        )
        job = _job(db_session)
        await db_session.commit()
        app = _application(db_session, job)
        await db_session.commit()

        raw = (await client.get(f"{API}/{app.id}/evidence")).text.lower()

        for forbidden in ("password", "cookie", "token", "storage_state", "secret",
                          "fingerprint", "abc123deadbeef"):
            assert forbidden not in raw

    async def test_an_application_with_no_connected_account_says_so(
        self, db_session, current_user, client
    ):
        job = _job(db_session)
        await db_session.commit()
        app = _application(db_session, job)
        await db_session.commit()

        body = (await client.get(f"{API}/{app.id}/evidence")).json()["account"]
        assert body["connected"] is False
        assert "did not sign in" in body["detail"]

    async def test_a_full_address_stored_before_masking_existed_is_masked_on_read(
        self, db_session, current_user, client
    ):
        """Defence in depth: masking at write time is the rule, but a row written by an older
        build must not leak the whole address through this endpoint."""
        db_session.add(
            PlatformSession(
                user_id=TEST_USER_ID, platform="reed", state=SessionState.SESSION_ACTIVE,
                account_label="suraj.pandey@example.com",
            )
        )
        job = _job(db_session)
        await db_session.commit()
        app = _application(db_session, job)
        await db_session.commit()

        body = (await client.get(f"{API}/{app.id}/evidence")).json()["account"]
        assert body["account"] == "sur***@example.com"


class TestRunLog:
    async def test_the_lifecycle_timeline_is_surfaced(
        self, db_session, current_user, client
    ):
        job = _job(db_session)
        await db_session.commit()
        app = _application(db_session, job)
        db_session.add(
            ApplicationEvent(
                user_id=TEST_USER_ID,
                application_id=app.id,
                event_type=ApplicationEventType.APPLICATION_SUBMITTED,
                occurred_at=datetime.now(UTC).replace(tzinfo=None),
                summary="Application submitted",
                actor="agent",
            )
        )
        await db_session.commit()

        body = (await client.get(f"{API}/{app.id}/evidence")).json()

        assert body["log_recorded"] is True
        assert any(e["message"] == "Application submitted" for e in body["log"])

    async def test_the_automation_steps_are_surfaced_alongside_them(
        self, db_session, current_user, client
    ):
        """Both recorders already exist. Surfacing them beats adding a third that would
        immediately disagree with the other two."""
        job = _job(db_session)
        await db_session.commit()
        app = _application(db_session, job)
        db_session.add(
            RunTrajectory(
                user_id=TEST_USER_ID,
                application_id=app.id,
                platform="reed",
                steps=[
                    {"action": "Opening application URL"},
                    {"action": "Resume uploaded"},
                    "Submit action triggered",
                ],
                status="completed",
            )
        )
        await db_session.commit()

        entries = (await client.get(f"{API}/{app.id}/evidence")).json()["log"]
        messages = [e["message"] for e in entries]

        assert "Opening application URL" in messages
        assert "Resume uploaded" in messages
        assert "Submit action triggered" in messages
        assert all(e["source"] == "automation" for e in entries)

    async def test_an_application_with_no_history_says_nothing_was_recorded(
        self, db_session, current_user, client
    ):
        job = _job(db_session)
        await db_session.commit()
        app = _application(db_session, job)
        await db_session.commit()

        body = (await client.get(f"{API}/{app.id}/evidence")).json()
        assert body["log_recorded"] is False
        assert body["log"] == []

    async def test_entries_are_ordered_oldest_first(
        self, db_session, current_user, client
    ):
        job = _job(db_session)
        await db_session.commit()
        app = _application(db_session, job)
        base = datetime.now(UTC).replace(tzinfo=None)
        for offset, summary in ((2, "later"), (0, "earlier")):
            db_session.add(
                ApplicationEvent(
                    user_id=TEST_USER_ID, application_id=app.id,
                    event_type=ApplicationEventType.NOTE_ADDED,
                    occurred_at=base + timedelta(minutes=offset),
                    summary=summary, actor="system",
                )
            )
        await db_session.commit()

        messages = [e["message"] for e in (await client.get(f"{API}/{app.id}/evidence")).json()["log"]]
        assert messages.index("earlier") < messages.index("later")


class TestFailures:
    async def test_a_failed_application_reports_why_and_offers_a_retry(
        self, db_session, current_user, client
    ):
        job = _job(db_session)
        await db_session.commit()
        app = _application(
            db_session, job,
            status=ApplicationStatus.FAILED,
            confirmation_state=ConfirmationState.FAILED,
            notes='Required field "Work Authorisation" was not accepted.',
            applied_at=None,
        )
        await db_session.commit()

        failure = (await client.get(f"{API}/{app.id}/evidence")).json()["failure"]

        assert failure is not None
        assert "Work Authorisation" in failure["message"]
        # The retry endpoint genuinely exists (status -> queued), so the button is real.
        assert failure["can_retry"] is True

    async def test_a_failure_with_no_recorded_reason_says_that_plainly(
        self, db_session, current_user, client
    ):
        job = _job(db_session)
        await db_session.commit()
        app = _application(
            db_session, job, status=ApplicationStatus.FAILED, notes=None, applied_at=None
        )
        await db_session.commit()

        failure = (await client.get(f"{API}/{app.id}/evidence")).json()["failure"]
        assert "without recording a reason" in failure["message"]

    async def test_a_healthy_application_has_no_failure_section(
        self, db_session, current_user, client
    ):
        job = _job(db_session)
        await db_session.commit()
        app = _application(db_session, job)
        await db_session.commit()

        assert (await client.get(f"{API}/{app.id}/evidence")).json()["failure"] is None


class TestEndpoint:
    async def test_an_unknown_application_is_a_404(self, client):
        assert (await client.get(f"{API}/nope/evidence")).status_code == 404

    async def test_the_endpoint_needs_authentication(self, anon_client):
        assert (await anon_client.get(f"{API}/x/evidence")).status_code in (401, 403)


class TestProvenanceIsCapturedAtCreation:
    async def test_creating_an_application_snapshots_the_board_and_url(
        self, db_session, current_user, client
    ):
        """Both columns existed and neither was ever written, so no application could say
        which board it lived on or where to open it."""
        job = _job(db_session)
        await db_session.commit()

        response = await client.post(
            f"{API}/", json={"job_id": job.id, "apply_mode": "review"}
        )
        assert response.status_code == 201
        app_id = response.json()["id"]

        body = (await client.get(f"{API}/{app_id}/evidence")).json()
        assert body["job"]["source"] == "reed"
        assert body["job"]["job_url"] == job.url
