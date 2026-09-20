"""Unit tests for services.resume_intelligence — master résumé CRUD, branching, versioning,
diffing, and restore. No LLM involved (see test_resume_tailoring.py for that)."""

from __future__ import annotations

import pytest

from app.models.user_settings import UserSettings
from app.schemas.resume_intelligence import CreateBranchRequest, ResumeContent, ResumeHeader
from app.services import resume_intelligence as ri
from tests.conftest import TEST_USER_ID


class TestMasterBootstrap:
    async def test_creates_a_v1_master_when_none_exists(self, db_session):
        version = await ri.get_or_create_master(db_session, TEST_USER_ID)
        assert version.branch_id is None
        assert version.version_label == "MAIN v1.0"
        assert version.sequence == 1
        assert version.source == "initial"

    async def test_bootstraps_from_existing_candidate_profile(self, db_session):
        db_session.add(UserSettings(
            user_id=TEST_USER_ID,
            candidate_profile={
                "full_name": "Jane Doe", "summary": "Experienced engineer.",
                "skills": ["Python", "FastAPI"],
                "experience": [{
                    "title": "Senior Engineer", "company": "Acme",
                    "start_date": "2020", "end_date": "Present",
                    "description": "Led backend systems.",
                    "responsibilities": ["Built APIs"],
                }],
                "education": [{"degree": "BSc CS", "institution": "MIT"}],
            },
        ))
        await db_session.commit()

        version = await ri.get_or_create_master(db_session, TEST_USER_ID)
        content = ResumeContent.model_validate(version.content)
        assert content.header.full_name == "Jane Doe"
        assert content.summary == "Experienced engineer."
        assert "Python" in content.skills
        assert content.experience[0].company == "Acme"
        assert len(content.experience[0].achievements) == 2  # description + 1 responsibility

    async def test_never_fabricates_when_profile_is_empty(self, db_session):
        version = await ri.get_or_create_master(db_session, TEST_USER_ID)
        content = ResumeContent.model_validate(version.content)
        assert content.header.full_name == ""
        assert content.experience == []
        assert content.skills == []

    async def test_is_idempotent(self, db_session):
        v1 = await ri.get_or_create_master(db_session, TEST_USER_ID)
        v2 = await ri.get_or_create_master(db_session, TEST_USER_ID)
        assert v1.id == v2.id


class TestUpdateMaster:
    async def test_creates_a_new_version_not_mutating_the_old_one(self, db_session):
        v1 = await ri.get_or_create_master(db_session, TEST_USER_ID)
        new_content = ResumeContent(header=ResumeHeader(full_name="New Name"), summary="Updated.")
        v2 = await ri.update_master(db_session, TEST_USER_ID, new_content, "Updated header")

        assert v2.id != v1.id
        assert v2.version_label == "MAIN v1.1"
        assert v2.parent_version_id == v1.id
        # The old version's own content must be untouched.
        old = await ri.get_version_row(db_session, TEST_USER_ID, v1.id)
        assert old.content["header"]["full_name"] == ""

    async def test_records_the_edit_as_change_log_entries(self, db_session):
        await ri.get_or_create_master(db_session, TEST_USER_ID)
        new_content = ResumeContent(summary="A brand new summary.", skills=["Python"])
        v2 = await ri.update_master(db_session, TEST_USER_ID, new_content, "Added summary and skill")

        detail = await ri.get_version(db_session, TEST_USER_ID, v2.id)
        types = {c.change_type for c in detail.changes}
        assert "modified" in types  # summary changed
        assert "added" in types  # skill added
        assert all(c.status == "accepted" for c in detail.changes)


class TestBranches:
    async def test_create_branch_seeds_from_master_content(self, db_session):
        master = await ri.get_or_create_master(db_session, TEST_USER_ID)
        await ri.update_master(
            db_session, TEST_USER_ID,
            ResumeContent(summary="Master summary", skills=["Python", "SQL"]),
            "seed",
        )
        branch = await ri.create_branch(
            db_session, TEST_USER_ID,
            CreateBranchRequest(role_name="AI Product Manager", role_family="product"),
        )
        assert branch.role_name == "AI Product Manager"
        assert branch.current_version.version_label == "AI Product Manager v1.0"

        detail = await ri.get_branch(db_session, TEST_USER_ID, branch.id)
        assert detail.current_content.summary == "Master summary"
        assert "Python" in detail.current_content.skills

    async def test_list_branches_returns_current_version_each(self, db_session):
        await ri.create_branch(db_session, TEST_USER_ID, CreateBranchRequest(role_name="Data Scientist"))
        await ri.create_branch(db_session, TEST_USER_ID, CreateBranchRequest(role_name="MLOps Engineer"))
        branches = await ri.list_branches(db_session, TEST_USER_ID)
        assert {b.role_name for b in branches} == {"Data Scientist", "MLOps Engineer"}
        assert all(b.current_version is not None for b in branches)

    async def test_delete_branch_removes_its_versions(self, db_session):
        branch = await ri.create_branch(db_session, TEST_USER_ID, CreateBranchRequest(role_name="Data Scientist"))
        await ri.delete_branch(db_session, TEST_USER_ID, branch.id)
        with pytest.raises(Exception):
            await ri.get_branch(db_session, TEST_USER_ID, branch.id)

    async def test_unknown_role_family_falls_back_to_product(self, db_session):
        branch = await ri.create_branch(
            db_session, TEST_USER_ID, CreateBranchRequest(role_name="X", role_family="not-a-real-family"),
        )
        assert branch.role_family == "product"


class TestVersionHistoryAndDiff:
    async def test_diff_reports_added_removed_modified(self, db_session):
        await ri.get_or_create_master(db_session, TEST_USER_ID)
        v1 = await ri.update_master(
            db_session, TEST_USER_ID, ResumeContent(summary="First", skills=["Python"]), "v1",
        )
        v2 = await ri.update_master(
            db_session, TEST_USER_ID, ResumeContent(summary="Second", skills=["Python", "Go"]), "v2",
        )
        diff = await ri.diff_versions(db_session, TEST_USER_ID, v1.id, v2.id)
        assert any(e.path == "summary" and e.before == "First" and e.after == "Second" for e in diff.modified)
        assert any(e.path == "Go" for e in diff.added)

    async def test_restore_creates_a_new_version_never_deletes_history(self, db_session):
        v1 = await ri.get_or_create_master(db_session, TEST_USER_ID)
        await ri.update_master(db_session, TEST_USER_ID, ResumeContent(summary="Changed"), "change it")

        restored = await ri.restore_version(db_session, TEST_USER_ID, v1.id, "")
        assert restored.version_label == "MAIN v1.2"  # a NEW version, not v1 reappearing
        assert restored.source == "restored"

        versions = await ri.list_versions(db_session, TEST_USER_ID, branch_id=None)
        assert len(versions) == 3  # v1.0, v1.1 (changed), v1.2 (restored) — nothing deleted

        restored_detail = await ri.get_version(db_session, TEST_USER_ID, restored.id)
        assert restored_detail.content.summary == ""  # v1's original (empty) summary


class TestOverview:
    async def test_overview_reports_master_branches_and_recent_changes(self, db_session):
        await ri.update_master(db_session, TEST_USER_ID, ResumeContent(summary="X"), "edit")
        await ri.create_branch(db_session, TEST_USER_ID, CreateBranchRequest(role_name="Data Scientist"))

        overview = await ri.get_overview(db_session, TEST_USER_ID)
        assert overview.master_version is not None
        assert len(overview.branches) == 1
        assert overview.recent_changes_count >= 1
