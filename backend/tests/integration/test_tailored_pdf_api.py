"""End to end through the HTTP API: upload a PDF CV, tailor it for a job, get a PDF back.

The language model is the only stand-in. Upload, storage, the layout-preserving PDF edit, the
checks, the version record, listing and download are all the real code, against a real PDF.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

import app.services.resume as resume_service
import app.services.tailored_resume as tailored_service
from app.core.resume_tailoring.pdf_layout import build_document
from tests import pdf_tools
from app.core.resume_tailoring.plan import EditPlan, ProposedEdit
from app.models.job import Job
from app.models.resume import Resume
from tests.conftest import TEST_USER_ID
from tests.pdf_cv_factory import make_cv
from tests.unit.test_pdf_tailoring_golden import EVIDENCE, StubLLM

API = "/api/v1/resumes"
JD_A = "Data Scientist. Python, SQL, experimentation and A/B testing, model monitoring, stakeholders."
JD_B = "Data Scientist. Forecasting, Airflow pipelines, model monitoring, mentoring analysts and stakeholders."


async def _job(db, title, description, key):
    job = Job(
        user_id=TEST_USER_ID, platform="linkedin", platform_job_id=key, title=title, company="Acme",
        location="London", url=f"https://example.com/{key}", description=description,
        job_type="full-time", remote=False, match_score=0.9, status="new",
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)
    return job


@pytest.fixture
def cv_pdf(tmp_path):
    return make_cv(tmp_path / "cv.pdf", "serif_teal", "data_scientist")


async def _upload(client, tmp_path, pdf_path, name="Asha_Raman_CV.pdf"):
    with patch.object(resume_service, "UPLOAD_DIR", tmp_path):
        resp = await client.post(
            f"{API}/upload", files={"file": (name, pdf_path.read_bytes(), "application/pdf")}
        )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _plan_for(pdf_path, fragment, old, new, keyword) -> EditPlan:
    doc = build_document(str(pdf_path))
    line = next(ln for ln in doc.bullets() if fragment in ln.text)
    return EditPlan(edits=[ProposedEdit(
        line_id=line.id, action="tweak", after_text=line.text.replace(old, new),
        reason="Works the posting's wording into a bullet that already shows it.",
        evidence=EVIDENCE, keywords_added=[keyword], level="4_keyword_alignment",
    )])


PLAN_A = ("Designed an experimentation framework", "rollout decisions across", "rollout decisions for stakeholders across", "stakeholders")
PLAN_B = ("Productionised batch scoring", "with monitoring for data drift", "with model monitoring for data drift", "model monitoring")


def _llm(plan):
    llm = StubLLM(plan)
    return llm, patch.object(tailored_service, "build_llm_client_for_user", AsyncMock(return_value=llm))


class TestGenerate:
    async def test_the_response_is_a_stored_pdf_version_with_an_honest_audit(self, client, db_session, tmp_path, cv_pdf):
        base_id = await _upload(client, tmp_path, cv_pdf)
        job = await _job(db_session, "Data Scientist", JD_A, "j1")
        llm, patcher = _llm(_plan_for(cv_pdf, *PLAN_A))
        with patcher:
            resp = await client.post(f"{API}/generate", json={"base_resume_id": base_id, "job_id": job.id})

        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["type"] == "tailored" and body["base_resume_id"] == base_id and body["job_id"] == job.id
        assert body["has_pdf"] is True and body["has_docx"] is False
        assert 0 <= body["ats_score"] <= 1, "stored scores are 0-1 (the UI multiplies by 100)"
        audit = body["tailoring_audit"]
        assert audit["generation_status"] == "generated" and audit["validation_status"] == "passed"
        assert audit["formatting_preserved"] is True and audit["checks"]["ok"] is True
        assert audit["checks"]["pixels_changed_outside_edits"] == 0
        assert audit["ats_scored_from"] == "generated_pdf"
        assert audit["original_ats_score"] <= audit["final_ats_score"] <= 100
        assert audit["base_resume_id"] == base_id and audit["job_id"] == job.id
        assert audit["original_file"] and audit["tailored_file"] and audit["original_file"] != audit["tailored_file"]
        assert [c["keywords_added"] for c in audit["changes"]] == [["stakeholders"]]

    async def test_the_pdf_downloads_opens_and_is_what_was_stored(self, client, db_session, tmp_path, cv_pdf):
        base_id = await _upload(client, tmp_path, cv_pdf)
        job = await _job(db_session, "Data Scientist", JD_A, "j1")
        _llm_stub, patcher = _llm(_plan_for(cv_pdf, *PLAN_A))
        with patcher:
            created = (await client.post(f"{API}/generate", json={"base_resume_id": base_id, "job_id": job.id})).json()

        dl = await client.get(f"{API}/{created['id']}/download", params={"format": "pdf"})
        assert dl.status_code == 200 and dl.headers["content-type"] == "application/pdf"
        assert pdf_tools.page_count(cv_pdf) == len(pdf_tools.page_boxes(dl.content))
        assert pdf_tools.page_boxes(dl.content) == pdf_tools.page_boxes(cv_pdf)
        text = pdf_tools.flat_text(dl.content)
        assert "for stakeholders across" in text
        base_download = await client.get(f"{API}/{base_id}/download", params={"format": "pdf"})
        assert base_download.content == cv_pdf.read_bytes(), "the original must stay untouched"
        assert dl.content != base_download.content

        row = await db_session.get(Resume, created["id"])
        assert row.file_path_pdf and row.tailoring_audit["generation_status"] == "generated"

    async def test_the_version_survives_a_refresh_and_is_listed_against_its_job(self, client, db_session, tmp_path, cv_pdf):
        base_id = await _upload(client, tmp_path, cv_pdf)
        job = await _job(db_session, "Data Scientist", JD_A, "j1")
        _s, patcher = _llm(_plan_for(cv_pdf, *PLAN_A))
        with patcher:
            created = (await client.post(f"{API}/generate", json={"base_resume_id": base_id, "job_id": job.id})).json()

        listed = (await client.get(f"{API}/")).json()["items"]
        match = [r for r in listed if r["id"] == created["id"]]
        assert len(match) == 1 and match[0]["job_id"] == job.id and match[0]["has_pdf"] is True
        assert match[0]["tailoring_audit"]["changes"], "the change log must come back with the list"

    async def test_a_repeat_request_returns_the_existing_version_and_regenerate_makes_a_new_one(
        self, client, db_session, tmp_path, cv_pdf
    ):
        base_id = await _upload(client, tmp_path, cv_pdf)
        job = await _job(db_session, "Data Scientist", JD_A, "j1")
        llm, patcher = _llm(_plan_for(cv_pdf, *PLAN_A))
        with patcher:
            first = (await client.post(f"{API}/generate", json={"base_resume_id": base_id, "job_id": job.id})).json()
            calls_for_one_generation = llm.calls
            again = (await client.post(f"{API}/generate", json={"base_resume_id": base_id, "job_id": job.id})).json()
            calls_after_repeat = llm.calls
            forced = (await client.post(
                f"{API}/generate", json={"base_resume_id": base_id, "job_id": job.id, "regenerate": True}
            )).json()

        assert again["id"] == first["id"] and calls_after_repeat == calls_for_one_generation, (
            "the repeat must not call the model again"
        )
        assert forced["id"] != first["id"]

    async def test_simultaneous_clicks_make_one_version_and_one_model_call(self, client, db_session, tmp_path, cv_pdf):
        base_id = await _upload(client, tmp_path, cv_pdf)
        job = await _job(db_session, "Data Scientist", JD_A, "j1")
        llm, patcher = _llm(_plan_for(cv_pdf, *PLAN_A))
        from unittest.mock import AsyncMock, patch

        from app.core.resume_tailoring.pdf_pipeline import tailor_pdf as real_pipeline

        counting = AsyncMock(side_effect=real_pipeline)
        with patcher, patch("app.services.tailored_resume.tailor_pdf", counting):
            responses = await asyncio.gather(*[
                client.post(f"{API}/generate", json={"base_resume_id": base_id, "job_id": job.id}) for _ in range(3)
            ])
        ids = {r.json()["id"] for r in responses}
        assert all(r.status_code == 201 for r in responses) and len(ids) == 1
        assert counting.call_count == 1, "three clicks must run the pipeline once"

    async def test_two_jobs_get_two_independent_versions(self, client, db_session, tmp_path, cv_pdf):
        base_id = await _upload(client, tmp_path, cv_pdf)
        job_a = await _job(db_session, "Data Scientist", JD_A, "ja")
        job_b = await _job(db_session, "Forecasting Data Scientist", JD_B, "jb")

        _a, patch_a = _llm(_plan_for(cv_pdf, *PLAN_A))
        with patch_a:
            a = (await client.post(f"{API}/generate", json={"base_resume_id": base_id, "job_id": job_a.id})).json()
        _b, patch_b = _llm(_plan_for(cv_pdf, *PLAN_B))
        with patch_b:
            b = (await client.post(f"{API}/generate", json={"base_resume_id": base_id, "job_id": job_b.id})).json()

        assert a["id"] != b["id"] and a["job_id"] == job_a.id and b["job_id"] == job_b.id
        text_a = pdf_tools.flat_text((await client.get(f"{API}/{a['id']}/download")).content)
        text_b = pdf_tools.flat_text((await client.get(f"{API}/{b['id']}/download")).content)
        assert "for stakeholders across" in text_a and "model monitoring" not in text_a
        assert "model monitoring" in text_b and "for stakeholders across" not in text_b
        assert a["tailoring_audit"]["job_id"] == job_a.id and b["tailoring_audit"]["job_id"] == job_b.id


class TestFailuresAreVisibleNotSilent:
    async def _setup(self, client, db_session, tmp_path, cv_pdf):
        base_id = await _upload(client, tmp_path, cv_pdf)
        job = await _job(db_session, "Data Scientist", JD_A, "j1")
        return base_id, job

    async def _count(self, db_session):
        from sqlalchemy import func, select

        return (await db_session.execute(select(func.count()).select_from(Resume).where(Resume.type == "tailored"))).scalar_one()

    async def test_an_unknown_job_is_a_404(self, client, db_session, tmp_path, cv_pdf):
        base_id = await _upload(client, tmp_path, cv_pdf)
        resp = await client.post(f"{API}/generate", json={"base_resume_id": base_id, "job_id": "does-not-exist"})
        assert resp.status_code == 404

    async def test_an_unknown_resume_is_a_404(self, client, db_session, tmp_path, cv_pdf):
        job = await _job(db_session, "Data Scientist", JD_A, "j1")
        resp = await client.post(f"{API}/generate", json={"base_resume_id": "nope", "job_id": job.id})
        assert resp.status_code == 404

    async def test_a_job_with_no_description_says_so(self, client, db_session, tmp_path, cv_pdf):
        base_id = await _upload(client, tmp_path, cv_pdf)
        job = await _job(db_session, "Mystery role", "", "j0")
        resp = await client.post(f"{API}/generate", json={"base_resume_id": base_id, "job_id": job.id})
        assert resp.status_code == 422 and "no description" in resp.json()["detail"]
        assert await self._count(db_session) == 0

    async def test_a_deleted_pdf_is_reported_not_papered_over(self, client, db_session, tmp_path, cv_pdf):
        from app.core.storage import StorageService, get_storage

        base_id, job = await self._setup(client, db_session, tmp_path, cv_pdf)
        base = await db_session.get(Resume, base_id)
        await StorageService(get_storage(), TEST_USER_ID).delete(base.file_path_pdf)

        resp = await client.post(f"{API}/generate", json={"base_resume_id": base_id, "job_id": job.id})
        assert resp.status_code == 422 and "missing" in resp.json()["detail"]
        assert await self._count(db_session) == 0

    async def test_an_unreadable_pdf_is_a_clear_error(self, client, db_session, tmp_path, cv_pdf):
        bad = tmp_path / "bad.pdf"
        bad.write_bytes(b"%PDF-1.4\nthis is not really a pdf at all\n%%EOF")
        base_id = await _upload(client, tmp_path, bad, name="bad.pdf")
        job = await _job(db_session, "Data Scientist", JD_A, "j1")
        resp = await client.post(f"{API}/generate", json={"base_resume_id": base_id, "job_id": job.id})
        assert resp.status_code == 422 and "could not be read" in resp.json()["detail"]
        assert await self._count(db_session) == 0

    async def test_a_model_that_is_down_fails_visibly_and_saves_nothing(self, client, db_session, tmp_path, cv_pdf):
        base_id, job = await self._setup(client, db_session, tmp_path, cv_pdf)

        class Down:
            async def complete_with_structured_output(self, **_):
                raise TimeoutError("gateway timed out")

        with patch.object(tailored_service, "build_llm_client_for_user", AsyncMock(return_value=Down())):
            resp = await client.post(f"{API}/generate", json={"base_resume_id": base_id, "job_id": job.id})
        assert resp.status_code == 422 and "language model" in resp.json()["detail"]
        assert await self._count(db_session) == 0, "a failed attempt leaves nothing behind to be reused"

    async def test_a_hung_model_is_cut_off_instead_of_hanging_the_request(self, client, db_session, tmp_path, cv_pdf):
        import app.core.resume_tailoring.engine as engine

        base_id, job = await self._setup(client, db_session, tmp_path, cv_pdf)

        class Hung:
            async def complete_with_structured_output(self, **_):
                await asyncio.sleep(30)

        with (
            patch.object(engine, "PLAN_TIMEOUT_SECONDS", 0.2),
            patch.object(tailored_service, "build_llm_client_for_user", AsyncMock(return_value=Hung())),
        ):
            resp = await client.post(f"{API}/generate", json={"base_resume_id": base_id, "job_id": job.id})
        assert resp.status_code == 422 and "in time" in resp.json()["detail"]

    async def test_a_malformed_model_response_fails_visibly(self, client, db_session, tmp_path, cv_pdf):
        base_id, job = await self._setup(client, db_session, tmp_path, cv_pdf)

        class Garbled:
            async def complete_with_structured_output(self, **_):
                raise ValueError("model returned text that is not valid JSON")

        with patch.object(tailored_service, "build_llm_client_for_user", AsyncMock(return_value=Garbled())):
            resp = await client.post(f"{API}/generate", json={"base_resume_id": base_id, "job_id": job.id})
        assert resp.status_code == 422 and await self._count(db_session) == 0

    async def test_a_pdf_writing_failure_is_an_error_and_saves_nothing(self, client, db_session, tmp_path, cv_pdf):
        base_id, job = await self._setup(client, db_session, tmp_path, cv_pdf)
        _s, patcher = _llm(_plan_for(cv_pdf, *PLAN_A))
        with patcher, patch("app.core.resume_tailoring.pdf_pipeline.edit_pdf_in_place", side_effect=RuntimeError("boom")):
            resp = await client.post(f"{API}/generate", json={"base_resume_id": base_id, "job_id": job.id})
        assert resp.status_code == 422 and "could not be generated" in resp.json()["detail"]
        assert await self._count(db_session) == 0

    async def test_a_storage_failure_is_an_error_and_saves_nothing(self, client, db_session, tmp_path, cv_pdf):
        base_id, job = await self._setup(client, db_session, tmp_path, cv_pdf)
        _s, patcher = _llm(_plan_for(cv_pdf, *PLAN_A))
        real_put = tailored_service.StorageService.put

        async def failing_put(self, key, data, *, content_type):
            if "/resumes/" in key:
                raise OSError("disk full")
            return await real_put(self, key, data, content_type=content_type)

        with patcher, patch.object(tailored_service.StorageService, "put", failing_put):
            resp = await client.post(f"{API}/generate", json={"base_resume_id": base_id, "job_id": job.id})
        assert resp.status_code == 422 and "could not be stored" in resp.json()["detail"]
        assert await self._count(db_session) == 0

    async def test_a_failed_attempt_can_be_retried(self, client, db_session, tmp_path, cv_pdf):
        base_id, job = await self._setup(client, db_session, tmp_path, cv_pdf)
        _s, patcher = _llm(_plan_for(cv_pdf, *PLAN_A))
        with patcher:
            with patch("app.core.resume_tailoring.pdf_pipeline.edit_pdf_in_place", side_effect=RuntimeError("boom")):
                failed = await client.post(f"{API}/generate", json={"base_resume_id": base_id, "job_id": job.id})
            retried = await client.post(f"{API}/generate", json={"base_resume_id": base_id, "job_id": job.id})
        assert failed.status_code == 422 and retried.status_code == 201
        assert await self._count(db_session) == 1
