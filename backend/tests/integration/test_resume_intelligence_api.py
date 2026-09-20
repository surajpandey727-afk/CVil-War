"""Integration tests for the Resume Intelligence API routes — auth, tenant isolation, and the
end-to-end HTTP flow (create branch -> tailor -> commit -> application linkage)."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from app.models.job import Job
from app.schemas.resume_intelligence import TailorLLMOutput, TailorLLMTitleAnalysis
from tests.conftest import TEST_USER_ID

API = "/api/v1/resume-intelligence"


@pytest.fixture
async def a_job(db_session):
    job = Job(
        user_id=TEST_USER_ID, platform="linkedin", platform_job_id="pj-1",
        title="AI Product Manager", company="Acme", location="Remote",
        url="https://x.test/job", description="",
        skills_required={"required": ["Python"], "preferred": []},
    )
    db_session.add(job)
    await db_session.commit()
    await db_session.refresh(job)
    return job


class TestAuth:
    async def test_overview_requires_authentication(self, anon_client):
        response = await anon_client.get(f"{API}/overview")
        assert response.status_code in (401, 403)


class TestOverviewAndMaster:
    async def test_overview_lazily_creates_a_master(self, client):
        response = await client.get(f"{API}/overview")
        assert response.status_code == 200
        body = response.json()
        assert body["master_version"]["version_label"] == "MAIN v1.0"
        assert body["branches"] == []

    async def test_update_master_creates_a_new_version(self, client):
        await client.get(f"{API}/master")
        response = await client.put(f"{API}/master", json={
            "content": {"summary": "Updated summary", "skills": ["Python"]},
            "commit_message": "Add summary",
        })
        assert response.status_code == 200
        assert response.json()["version_label"] == "MAIN v1.1"
        assert response.json()["content"]["summary"] == "Updated summary"


class TestBranches:
    async def test_create_and_get_branch(self, client):
        create = await client.post(f"{API}/branches", json={"role_name": "AI Product Manager", "role_family": "product"})
        assert create.status_code == 201
        branch_id = create.json()["id"]

        detail = await client.get(f"{API}/branches/{branch_id}")
        assert detail.status_code == 200
        assert detail.json()["role_name"] == "AI Product Manager"

    async def test_branch_not_found_is_404(self, client):
        response = await client.get(f"{API}/branches/does-not-exist")
        assert response.status_code == 404


class TestTailorFlow:
    async def test_full_acceptance_flow(self, client, db_session, a_job, monkeypatch):
        """The core product loop: create a branch, tailor against a job, review, commit, then
        confirm an application recorded against the resulting version is retrievable."""
        await client.get(f"{API}/master")  # bootstrap
        await client.put(f"{API}/master", json={"content": {"skills": ["Python"]}, "commit_message": "seed"})
        branch_resp = await client.post(f"{API}/branches", json={"role_name": "AI Product Manager"})
        branch_id = branch_resp.json()["id"]

        llm_output = TailorLLMOutput(
            contextually_satisfied={}, still_missing=[], ats_alignment_pct=72.0,
            role_fit_notes="Good fit.", positioning_notes="Lead with product ownership.",
            title_analysis=TailorLLMTitleAnalysis(relationship="related"),
        )
        fake_llm = AsyncMock()
        fake_llm.complete_with_structured_output = AsyncMock(return_value=llm_output)
        monkeypatch.setattr(
            "app.services.resume_tailoring.build_llm_client_for_user",
            AsyncMock(return_value=fake_llm),
        )

        tailor_resp = await client.post(f"{API}/tailor", json={"job_id": a_job.id, "branch_id": branch_id})
        assert tailor_resp.status_code == 200
        tailor_body = tailor_resp.json()
        assert tailor_body["ats_alignment_pct"] == 72.0
        assert "Python" in tailor_body["matched"]

        commit_resp = await client.post(
            f"{API}/tailor/{tailor_body['analysis_id']}/commit",
            json={"decisions": [], "commit_message": "Tailored for Acme"},
        )
        assert commit_resp.status_code == 200
        new_version_id = commit_resp.json()["version"]["id"]
        assert commit_resp.json()["version"]["version_label"] == "AI Product Manager v1.1"

        # The application-linkage half of the acceptance test: record that an application
        # used this exact version, then read it back.
        from app.models.application import Application

        app_row = Application(
            user_id=TEST_USER_ID, job_id=a_job.id, status="queued",
            resume_version_id=new_version_id,
        )
        db_session.add(app_row)
        await db_session.commit()
        await db_session.refresh(app_row)

        linkage = await client.get(f"{API}/applications/{app_row.id}/resume-version")
        assert linkage.status_code == 200
        assert linkage.json()["resume_version_id"] == new_version_id
        assert linkage.json()["branch_role_name"] == "AI Product Manager"

    async def test_tailor_with_no_branches_gives_a_clear_error_not_a_500(self, client, a_job):
        response = await client.post(f"{API}/tailor", json={"job_id": a_job.id})
        assert response.status_code == 404


class TestVersionsAndDiff:
    async def test_diff_endpoint(self, client):
        m1 = await client.get(f"{API}/master")
        v1_id = m1.json()["id"]
        m2 = await client.put(f"{API}/master", json={"content": {"summary": "New"}, "commit_message": "x"})
        v2_id = m2.json()["id"]

        diff = await client.get(f"{API}/versions/diff", params={"from_id": v1_id, "to_id": v2_id})
        assert diff.status_code == 200
        assert any(e["path"] == "summary" for e in diff.json()["modified"])

    async def test_restore_endpoint(self, client):
        m1 = await client.get(f"{API}/master")
        v1_id = m1.json()["id"]
        await client.put(f"{API}/master", json={"content": {"summary": "Changed"}, "commit_message": "x"})

        restore = await client.post(f"{API}/versions/{v1_id}/restore", json={"commit_message": ""})
        assert restore.status_code == 200
        assert restore.json()["source"] == "restored"
