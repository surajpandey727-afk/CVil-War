"""Scoring every row, and tailoring per application, end to end through the HTTP API.

The language model is the only stand-in. Upload, storage, PDF reading, the ATS evaluation, the
tailoring pipeline, persistence and the application attach are the real code, on real PDFs.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

import app.services.resume as resume_service
import app.services.tailored_resume as tailored_service
from app.core.resume_tailoring.pdf_layout import build_document
from app.core.resume_tailoring.plan import EditPlan, ProposedEdit
from app.models.application import Application
from app.models.job import Job
from app.models.resume import Resume
from tests.conftest import TEST_USER_ID
from tests.pdf_cv_factory import make_cv
from tests.unit.test_pdf_tailoring_golden import EVIDENCE, StubLLM

RESUMES = "/api/v1/resumes"
JOBS = "/api/v1/jobs"
APPS = "/api/v1/applications"
GOOD_JD = (
    "Data Scientist\n\nRequirements\nPython and SQL\nA/B testing and experimentation\nforecasting\n"
    "Airflow pipelines in production\nstakeholder management\n\nResponsibilities\n"
    "You will build forecasting models and deploy pipelines to production for the commercial team."
)
PM_JD = (
    "Product Manager\n\nRequirements\nroadmap ownership\nuser research and discovery\nstakeholder management\n"
    "SQL and analytics\nAgile delivery\n\nResponsibilities\nOwn the roadmap and run customer discovery."
)


async def _job(db, title, description, key):
    job = Job(
        user_id=TEST_USER_ID, platform="linkedin", platform_job_id=key, title=title, company="Acme",
        location="London", url=f"https://example.com/{key}", description=description,
        job_type="full-time", remote=False, status="new",
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)
    return job


async def _application(db, job, *, status="pending_review", resume_id=None):
    app = Application(user_id=TEST_USER_ID, job_id=job.id, status=status, resume_id=resume_id)
    db.add(app)
    await db.commit()
    await db.refresh(app)
    return app


async def _upload(client, tmp_path, pdf, name):
    with patch.object(resume_service, "UPLOAD_DIR", tmp_path):
        resp = await client.post(f"{RESUMES}/upload", files={"file": (name, pdf.read_bytes(), "application/pdf")})
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


@pytest.fixture
def ds_pdf(tmp_path):
    return make_cv(tmp_path / "ds.pdf", "serif_teal", "data_scientist")


@pytest.fixture
def pm_pdf(tmp_path):
    return make_cv(tmp_path / "pm.pdf", "sans_green", "product_manager")


def _plan(pdf, fragment, old, new, keyword):
    doc = build_document(str(pdf))
    line = next(ln for ln in doc.bullets() if fragment in ln.text)
    return EditPlan(edits=[ProposedEdit(
        line_id=line.id, action="tweak", after_text=line.text.replace(old, new), reason="Uses the posting's wording.",
        evidence=EVIDENCE, keywords_added=[keyword], level="4_keyword_alignment",
    )])


class TestJobScores:
    async def test_every_job_in_a_batch_is_scored_and_saved(self, client, db_session, tmp_path, ds_pdf):
        await _upload(client, tmp_path, ds_pdf, "ds.pdf")
        jobs = [await _job(db_session, "Data Scientist", GOOD_JD, f"j{i}") for i in range(12)]
        resp = await client.post(f"{JOBS}/score", json={"job_ids": [j.id for j in jobs]})

        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["scored"] == 12 and body["skipped"] == 0
        for item in body["items"]:
            assert 0 < item["match_score"] <= 1
            assert item["scored_with"]["source"] == "best"
        saved = (await db_session.execute(select(Job.match_score).where(Job.id.in_([j.id for j in jobs])))).scalars().all()
        assert all(score is not None for score in saved), "match_score is persisted, not recomputed on every view"

    async def test_there_is_no_per_row_rate_limit_on_bulk_scoring(self, client, db_session, tmp_path, ds_pdf):
        await _upload(client, tmp_path, ds_pdf, "ds.pdf")
        job = await _job(db_session, "Data Scientist", GOOD_JD, "j1")
        statuses = {(await client.post(f"{JOBS}/score", json={"job_ids": [job.id], "force": True})).status_code for _ in range(40)}
        assert statuses == {200}

    async def test_a_posting_with_no_description_is_reported_not_scored(self, client, db_session, tmp_path, ds_pdf):
        await _upload(client, tmp_path, ds_pdf, "ds.pdf")
        empty = await _job(db_session, "Data Scientist", "", "empty")
        body = (await client.post(f"{JOBS}/score", json={"job_ids": [empty.id]})).json()
        assert body["scored"] == 0 and "no description" in body["items"][0]["reason"]
        await db_session.refresh(empty)
        assert empty.match_score is None

    async def test_without_a_resume_the_reason_says_so(self, client, db_session):
        job = await _job(db_session, "Data Scientist", GOOD_JD, "j1")
        body = (await client.post(f"{JOBS}/score", json={"job_ids": [job.id]})).json()
        assert body["scored"] == 0 and "résumé" in body["items"][0]["reason"]

    async def test_the_best_matching_resume_is_the_one_used(self, client, db_session, tmp_path, ds_pdf, pm_pdf):
        ds_id = await _upload(client, tmp_path, ds_pdf, "ds.pdf")
        pm_id = await _upload(client, tmp_path, pm_pdf, "pm.pdf")
        ds_job = await _job(db_session, "Data Scientist", GOOD_JD, "ds")
        pm_job = await _job(db_session, "Product Manager", PM_JD, "pm")
        items = (await client.post(f"{JOBS}/score", json={"job_ids": [ds_job.id, pm_job.id]})).json()["items"]
        by_job = {i["job_id"]: i for i in items}
        assert by_job[ds_job.id]["scored_with"]["resume_id"] == ds_id
        assert by_job[pm_job.id]["scored_with"]["resume_id"] == pm_id


class TestApplicationScores:
    async def test_every_pending_row_gets_a_score_and_says_which_resume(self, client, db_session, tmp_path, ds_pdf):
        resume_id = await _upload(client, tmp_path, ds_pdf, "ds.pdf")
        jobs = [await _job(db_session, "Data Scientist", GOOD_JD, f"a{i}") for i in range(8)]
        apps = [await _application(db_session, j) for j in jobs]
        body = (await client.post(f"{APPS}/score", json={})).json()

        assert body["scored"] == 8 and body["skipped"] == 0
        for item in body["items"]:
            assert 0 < item["ats_score"] <= 1 and item["scored_with"]["resume_id"] == resume_id
            assert item["scored_with"]["source"] == "best" and item["persisted"] is False
            assert item["summary"]["tiers"]["critical"]["total"] >= 3
        for app in apps:
            await db_session.refresh(app)
            assert app.ats_score is None, "a hypothetical résumé must not set the score that gates auto-apply"

    async def test_an_attached_resume_scores_and_saves_the_applications_own_score(self, client, db_session, tmp_path, ds_pdf):
        resume_id = await _upload(client, tmp_path, ds_pdf, "ds.pdf")
        job = await _job(db_session, "Data Scientist", GOOD_JD, "a1")
        app = await _application(db_session, job, resume_id=resume_id)
        item = (await client.post(f"{APPS}/score", json={"application_ids": [app.id]})).json()["items"][0]
        assert item["scored_with"]["source"] == "attached" and item["persisted"] is True
        await db_session.refresh(app)
        assert app.ats_score == pytest.approx(item["ats_score"])

    async def test_rows_that_cannot_be_scored_say_why(self, client, db_session, tmp_path, ds_pdf):
        await _upload(client, tmp_path, ds_pdf, "ds.pdf")
        empty = await _application(db_session, await _job(db_session, "Data Scientist", "", "e"))
        good = await _application(db_session, await _job(db_session, "Data Scientist", GOOD_JD, "g"))
        body = (await client.post(f"{APPS}/score", json={"application_ids": [empty.id, good.id]})).json()
        by_app = {i["application_id"]: i for i in body["items"]}
        assert by_app[empty.id]["scored"] is False and "no description" in by_app[empty.id]["reason"]
        assert by_app[good.id]["scored"] is True and body["scored"] == 1 and body["skipped"] == 1

    async def test_scoring_is_scoped_to_pending_review_by_default(self, client, db_session, tmp_path, ds_pdf):
        await _upload(client, tmp_path, ds_pdf, "ds.pdf")
        pending = await _application(db_session, await _job(db_session, "Data Scientist", GOOD_JD, "p"))
        await _application(db_session, await _job(db_session, "Data Scientist", GOOD_JD, "d"), status="applied")
        body = (await client.post(f"{APPS}/score", json={})).json()
        assert [i["application_id"] for i in body["items"]] == [pending.id]


class TestTailorForApplication:
    async def test_the_tailored_resume_is_attached_and_its_score_is_the_applications(self, client, db_session, tmp_path, ds_pdf):
        base_id = await _upload(client, tmp_path, ds_pdf, "ds.pdf")
        app = await _application(db_session, await _job(db_session, "Data Scientist", GOOD_JD, "t1"))
        llm = StubLLM(_plan(ds_pdf, "Designed an experimentation framework", "rollout decisions across", "rollout decisions for stakeholders across", "stakeholders"))
        with patch.object(tailored_service, "build_llm_client_for_user", AsyncMock(return_value=llm)):
            resp = await client.post(f"{APPS}/{app.id}/tailor", json={})

        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["resume"]["type"] == "tailored" and body["resume"]["base_resume_id"] == base_id
        assert body["application"]["resume_id"] == body["resume"]["id"]
        assert body["ats_after"] == pytest.approx(body["resume"]["ats_score"])
        assert body["ats_before"] is not None and body["ats_after"] >= body["ats_before"]
        assert body["summary"]["parsing"] > 0 and "tiers" in body["summary"]
        await db_session.refresh(app)
        assert app.resume_id == body["resume"]["id"] and app.ats_score == pytest.approx(body["ats_after"])

    async def test_a_repeat_request_reuses_the_version_and_spends_no_second_llm_call(self, client, db_session, tmp_path, ds_pdf):
        await _upload(client, tmp_path, ds_pdf, "ds.pdf")
        app = await _application(db_session, await _job(db_session, "Data Scientist", GOOD_JD, "t2"))
        llm = StubLLM(_plan(ds_pdf, "Designed an experimentation framework", "rollout decisions across", "rollout decisions for stakeholders across", "stakeholders"))
        with patch.object(tailored_service, "build_llm_client_for_user", AsyncMock(return_value=llm)):
            first = (await client.post(f"{APPS}/{app.id}/tailor", json={})).json()
            calls = llm.calls
            second = (await client.post(f"{APPS}/{app.id}/tailor", json={})).json()
        assert second["resume"]["id"] == first["resume"]["id"] and llm.calls == calls
        versions = (await db_session.execute(select(Resume).where(Resume.type == "tailored"))).scalars().all()
        assert len(versions) == 1

    async def test_tailoring_records_a_cv_tailored_timeline_event(self, client, db_session, tmp_path, ds_pdf):
        # Regression: record_event was called without await, so the timeline entry was a
        # discarded coroutine and never persisted — the tailoring left no history.
        from app.models.application_event import ApplicationEvent
        from app.models.enums import ApplicationEventType

        await _upload(client, tmp_path, ds_pdf, "ds.pdf")
        app = await _application(db_session, await _job(db_session, "Data Scientist", GOOD_JD, "tev"))
        llm = StubLLM(_plan(ds_pdf, "Designed an experimentation framework", "rollout decisions across", "rollout decisions for stakeholders across", "stakeholders"))
        with patch.object(tailored_service, "build_llm_client_for_user", AsyncMock(return_value=llm)):
            assert (await client.post(f"{APPS}/{app.id}/tailor", json={})).status_code == 200

        events = (await db_session.execute(
            select(ApplicationEvent).where(
                ApplicationEvent.application_id == app.id,
                ApplicationEvent.event_type == ApplicationEventType.CV_TAILORED,
            )
        )).scalars().all()
        assert len(events) == 1 and events[0].actor == "user"

    async def test_the_best_matching_base_is_chosen_when_none_is_named(self, client, db_session, tmp_path, ds_pdf, pm_pdf):
        await _upload(client, tmp_path, ds_pdf, "ds.pdf")
        pm_id = await _upload(client, tmp_path, pm_pdf, "pm.pdf")
        app = await _application(db_session, await _job(db_session, "Product Manager", PM_JD, "t3"))
        llm = StubLLM(_plan(pm_pdf, "Defined success metrics", "funnel analysis in SQL", "funnel analytics in SQL", "analytics"))
        with patch.object(tailored_service, "build_llm_client_for_user", AsyncMock(return_value=llm)):
            body = (await client.post(f"{APPS}/{app.id}/tailor", json={})).json()
        assert body["resume"]["base_resume_id"] == pm_id

    async def test_an_application_that_is_past_review_cannot_be_retailored(self, client, db_session, tmp_path, ds_pdf):
        await _upload(client, tmp_path, ds_pdf, "ds.pdf")
        app = await _application(db_session, await _job(db_session, "Data Scientist", GOOD_JD, "t4"), status="applied")
        resp = await client.post(f"{APPS}/{app.id}/tailor", json={})
        assert resp.status_code == 409

    async def test_a_posting_without_a_description_fails_visibly(self, client, db_session, tmp_path, ds_pdf):
        await _upload(client, tmp_path, ds_pdf, "ds.pdf")
        app = await _application(db_session, await _job(db_session, "Data Scientist", "", "t5"))
        resp = await client.post(f"{APPS}/{app.id}/tailor", json={})
        assert resp.status_code == 422 and "description" in resp.text

    async def test_an_unknown_application_is_a_404(self, client):
        assert (await client.post(f"{APPS}/does-not-exist/tailor", json={})).status_code == 404

    async def test_tailoring_without_any_resume_says_to_upload_one(self, client, db_session):
        app = await _application(db_session, await _job(db_session, "Data Scientist", GOOD_JD, "t6"))
        resp = await client.post(f"{APPS}/{app.id}/tailor", json={})
        assert resp.status_code == 422 and "Upload" in resp.text


class TestResumeScoreEndpoint:
    async def test_the_job_drawer_score_comes_from_the_same_engine(self, client, db_session, tmp_path, ds_pdf):
        resume_id = await _upload(client, tmp_path, ds_pdf, "ds.pdf")
        job = await _job(db_session, "Data Scientist", GOOD_JD, "s1")
        body = (await client.post(f"{RESUMES}/{resume_id}/score", json={"job_id": job.id})).json()
        listed = (await client.post(f"{JOBS}/score", json={"job_ids": [job.id]})).json()["items"][0]
        assert body["overall_score"] == pytest.approx(listed["match_score"])
        assert body["parsing_score"] is not None and body["shortlist_score"] is not None
        assert body["evaluation"]["tiers"]["critical"]["total"] >= 3
