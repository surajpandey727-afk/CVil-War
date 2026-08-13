"""Deleting a résumé, and knowing which one an employer actually received.

The two are the same feature seen from opposite ends. An application that records only a
``resume_id`` cannot answer "what did they get", and a delete that blanks that id destroys the
answer permanently — the FK is ``ON DELETE SET NULL``, so it would do so silently.
"""

from __future__ import annotations

import itertools
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.core.storage import StorageService, get_storage
from app.models.application import Application
from app.models.enums import ApplicationStatus
from app.models.job import Job
from app.models.resume import Resume
from app.services import resume as resume_service
from tests.conftest import TEST_USER_ID

API = "/api/v1/resumes"
_SEQ = itertools.count(1)


def _job(db, **overrides):  # type: ignore[no-untyped-def]
    data = {
        "id": uuid4().hex,
        "user_id": TEST_USER_ID,
        "platform": "careers:monzo",
        "platform_job_id": f"j{next(_SEQ)}",
        "title": "Senior Product Manager",
        "company": "Monzo",
        "location": "London",
        "url": "https://example.invalid/j",
        "description": "",
        "status": "new",
    }
    job = Job(**{**data, **overrides})
    db.add(job)
    return job


def _resume(db, **overrides):  # type: ignore[no-untyped-def]
    data = {
        "id": uuid4().hex,
        "user_id": TEST_USER_ID,
        "name": "Suraj_Pandey_AIPM.pdf",
        "type": "base",
        "template_id": "modern",
        "ats_score": 0.82,
    }
    resume = Resume(**{**data, **overrides})
    db.add(resume)
    return resume


def _application(db, job, resume, status=ApplicationStatus.QUEUED, **overrides):  # type: ignore[no-untyped-def]
    app = Application(
        user_id=TEST_USER_ID,
        job_id=job.id,
        resume_id=resume.id if resume else None,
        apply_mode="review",
        status=status,
        **overrides,
    )
    db.add(app)
    return app


class TestDeleteUnusedResume:
    async def test_an_unused_resume_is_deleted_outright(self, db_session, current_user):
        resume = _resume(db_session)
        await db_session.commit()

        result = await resume_service.delete_resume(db_session, resume.id)

        assert result.deleted is True
        assert result.archived is False
        assert await db_session.get(Resume, resume.id) is None

    async def test_a_resume_attached_only_to_a_draft_is_still_deletable(
        self, db_session, current_user
    ):
        """A queued application has not been sent anywhere. Preserving a CV for its sake
        would make the list impossible to tidy — every experiment would be permanent."""
        resume = _resume(db_session)
        job = _job(db_session)
        await db_session.commit()
        _application(db_session, job, resume, status=ApplicationStatus.PENDING_REVIEW)
        await db_session.commit()

        result = await resume_service.delete_resume(db_session, resume.id)

        assert result.deleted is True
        assert result.used_by == 0

    async def test_the_stored_files_go_with_it(self, db_session, current_user):
        """Deleting only the row leaves the PDF in storage for ever, reachable by nothing."""
        storage = StorageService(get_storage(), TEST_USER_ID)
        key = f"users/{TEST_USER_ID}/resumes/gone.pdf"
        await storage.put(key, b"%PDF-1.4 test", content_type="application/pdf")
        resume = _resume(db_session, file_path_pdf=key)
        await db_session.commit()

        await resume_service.delete_resume(db_session, resume.id)

        assert await get_storage().exists(key) is False

    async def test_a_missing_stored_file_does_not_block_the_delete(
        self, db_session, current_user
    ):
        """The row is the thing the user asked to remove. Refusing because the object was
        already gone would leave them unable to clear a broken record at all."""
        resume = _resume(db_session, file_path_pdf=f"users/{TEST_USER_ID}/resumes/absent.pdf")
        await db_session.commit()

        result = await resume_service.delete_resume(db_session, resume.id)

        assert result.deleted is True


class TestArchiveInsteadOfLosingTheRecord:
    async def test_a_submitted_resume_is_archived_not_deleted(
        self, db_session, current_user
    ):
        resume = _resume(db_session)
        job = _job(db_session)
        await db_session.commit()
        _application(db_session, job, resume, status=ApplicationStatus.APPLIED)
        await db_session.commit()

        result = await resume_service.delete_resume(db_session, resume.id)

        assert result.deleted is False
        assert result.archived is True
        assert result.used_by == 1
        assert "1 application" in result.detail

    async def test_the_application_still_names_the_cv_that_went_out(
        self, db_session, current_user
    ):
        """The specific loss being prevented: the FK is ON DELETE SET NULL, so a hard delete
        would blank this without erroring and the record would quietly become 'no CV'."""
        resume = _resume(db_session)
        job = _job(db_session)
        await db_session.commit()
        app = _application(db_session, job, resume, status=ApplicationStatus.APPLIED)
        await db_session.commit()

        await resume_service.delete_resume(db_session, resume.id)
        await db_session.refresh(app)

        assert app.resume_id == resume.id
        assert await db_session.get(Resume, resume.id) is not None

    async def test_archiving_twice_is_a_no_op_that_reports_the_same_thing(
        self, db_session, current_user
    ):
        resume = _resume(db_session)
        job = _job(db_session)
        await db_session.commit()
        _application(db_session, job, resume, status=ApplicationStatus.APPLIED)
        await db_session.commit()

        first = await resume_service.delete_resume(db_session, resume.id)
        second = await resume_service.delete_resume(db_session, resume.id)

        assert first.archived and second.archived
        assert first.used_by == second.used_by

    @pytest.mark.parametrize(
        "status",
        [
            ApplicationStatus.APPLYING,
            ApplicationStatus.APPLIED,
            ApplicationStatus.INTERVIEW,
            ApplicationStatus.REJECTED,
            ApplicationStatus.OFFER,
        ],
    )
    async def test_every_status_that_reached_an_employer_protects_the_cv(
        self, db_session, current_user, status
    ):
        """A rejection is exactly when you most want to know what you sent."""
        resume = _resume(db_session)
        job = _job(db_session)
        await db_session.commit()
        _application(db_session, job, resume, status=status)
        await db_session.commit()

        result = await resume_service.delete_resume(db_session, resume.id)
        assert result.archived is True

    async def test_a_failed_application_does_not_protect_the_cv(
        self, db_session, current_user
    ):
        """A failed submission never reached the employer, so there is no record to keep."""
        resume = _resume(db_session)
        job = _job(db_session)
        await db_session.commit()
        _application(db_session, job, resume, status=ApplicationStatus.FAILED)
        await db_session.commit()

        assert (await resume_service.delete_resume(db_session, resume.id)).deleted is True


class TestListing:
    async def test_the_list_reports_how_often_each_cv_has_been_used(
        self, db_session, current_user
    ):
        resume = _resume(db_session)
        await db_session.commit()
        for status in (ApplicationStatus.APPLIED, ApplicationStatus.QUEUED):
            _application(db_session, _job(db_session), resume, status=status)
        await db_session.commit()

        listed = await resume_service.list_resumes(db_session)
        item = next(i for i in listed.items if i.id == resume.id)
        assert item.used_in_applications == 2
        assert item.submitted_applications == 1

    async def test_an_archived_cv_is_hidden_but_counted(self, db_session, current_user):
        """Hiding it without saying so leaves the user hunting for a CV that is still there."""
        _resume(db_session, archived_at=datetime.now(UTC))
        _resume(db_session, name="Live.pdf")
        await db_session.commit()

        listed = await resume_service.list_resumes(db_session)
        assert listed.total == 1
        assert listed.archived_count == 1

        with_archived = await resume_service.list_resumes(db_session, include_archived=True)
        assert with_archived.total == 2
        assert any(i.archived for i in with_archived.items)


class TestUsage:
    async def test_usage_names_the_roles_and_whether_each_went_out(
        self, db_session, current_user
    ):
        resume = _resume(db_session)
        applied_job = _job(db_session, title="Product Manager", company="Wise")
        draft_job = _job(db_session, title="Group PM", company="Monzo")
        await db_session.commit()
        _application(db_session, applied_job, resume, status=ApplicationStatus.APPLIED)
        _application(db_session, draft_job, resume, status=ApplicationStatus.QUEUED)
        await db_session.commit()

        usage = await resume_service.resume_usage(db_session, resume.id)

        assert usage.total == 2
        assert usage.submitted == 1
        assert {i.company for i in usage.items} == {"Wise", "Monzo"}
        assert [i.submitted for i in usage.items].count(True) == 1

    async def test_an_unknown_resume_is_a_404_not_an_empty_list(
        self, db_session, current_user
    ):
        """Reporting "used nowhere" for an id that does not exist reads as a safe delete."""
        from app.core.exceptions import RecordNotFoundError

        with pytest.raises(RecordNotFoundError):
            await resume_service.resume_usage(db_session, "not-a-resume")


class TestProvenanceOnTheApplication:
    async def test_an_application_reports_the_cv_that_went_with_it(
        self, db_session, current_user, client
    ):
        resume = _resume(db_session, name="Tailored - AIPM.pdf", ats_score=0.91)
        job = _job(db_session)
        await db_session.commit()
        app = _application(
            db_session, job, resume, status=ApplicationStatus.APPLIED,
            cover_letter_path=f"users/{TEST_USER_ID}/letters/1.pdf",
        )
        await db_session.commit()

        response = await client.get(f"/api/v1/applications/{app.id}")

        assert response.status_code == 200
        body = response.json()
        assert body["resume_name"] == "Tailored - AIPM.pdf"
        assert body["resume_ats_score"] == 0.91
        assert body["has_cover_letter"] is True

    async def test_an_archived_cv_is_still_named_and_flagged_as_archived(
        self, db_session, current_user, client
    ):
        """This is the payoff for archiving rather than deleting: the application can still
        say what was sent, and say that the CV is no longer in the working list."""
        resume = _resume(db_session, archived_at=datetime.now(UTC))
        job = _job(db_session)
        await db_session.commit()
        app = _application(db_session, job, resume, status=ApplicationStatus.APPLIED)
        await db_session.commit()

        body = (await client.get(f"/api/v1/applications/{app.id}")).json()

        assert body["resume_name"] == resume.name
        assert body["resume_archived"] is True

    async def test_an_application_with_no_cv_says_so_rather_than_inventing_one(
        self, db_session, current_user, client
    ):
        job = _job(db_session)
        await db_session.commit()
        app = _application(db_session, job, None)
        await db_session.commit()

        body = (await client.get(f"/api/v1/applications/{app.id}")).json()

        assert body["resume_name"] is None
        assert body["has_cover_letter"] is False


class TestEndpoints:
    async def test_delete_returns_what_happened(self, db_session, current_user, client):
        resume = _resume(db_session)
        await db_session.commit()

        response = await client.delete(f"{API}/{resume.id}")

        assert response.status_code == 200
        assert response.json()["deleted"] is True

    async def test_deleting_an_unknown_resume_is_a_404(self, client):
        assert (await client.delete(f"{API}/nope")).status_code == 404

    async def test_usage_endpoint_is_reachable(self, db_session, current_user, client):
        resume = _resume(db_session)
        await db_session.commit()

        response = await client.get(f"{API}/{resume.id}/usage")

        assert response.status_code == 200
        assert response.json() == {
            "resume_id": resume.id, "total": 0, "submitted": 0, "items": []
        }

    async def test_both_endpoints_need_authentication(self, anon_client):
        assert (await anon_client.delete(f"{API}/x")).status_code in (401, 403)
        assert (await anon_client.get(f"{API}/x/usage")).status_code in (401, 403)
