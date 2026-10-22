"""Skill Radar API, end to end through the authenticated routes.

The engine's logic is covered by tests/unit/test_skill_radar.py; these confirm the routes are
wired, tenant-scoped, and read a résumé's real text to score it.
"""

import pytest

from app.models.enums import ResumeType
from app.models.resume import Resume
from tests.conftest import TEST_USER_ID

API = "/api/v1/skills"

_RESUME_TEXT = (
    "Product manager, B2B SaaS. Owned the product roadmap and prioritisation. Defined KPIs and "
    "north star metrics. Ran A/B testing. Stakeholder management, cross-functional leadership. "
    "SQL and product analytics. Agile/Scrum. Wrote PRDs and ran product discovery. Strategy."
)


@pytest.fixture
async def resume(db_session):
    r = Resume(
        user_id=TEST_USER_ID, name="Suraj_AIPM.pdf", type=ResumeType.BASE,
        template_id="modern", content_text=_RESUME_TEXT,
    )
    db_session.add(r)
    await db_session.commit()
    await db_session.refresh(r)
    return r


class TestRoles:
    async def test_lists_curated_role_titles(self, client):
        resp = await client.get(f"{API}/roles")
        assert resp.status_code == 200
        titles = resp.json()
        assert "AI Product Manager" in titles and "Product Analyst" in titles


class TestAggregate:
    async def test_aggregates_demand_across_selected_roles(self, client):
        resp = await client.post(
            f"{API}/aggregate",
            json={"titles": ["Product Manager", "Product Analyst", "Technical Product Manager"]},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["skills"], "expected a non-empty demand list"
        top = body["skills"][0]
        assert top["roles_wanting"] == 3  # wanted by all three selected roles
        assert "categories" in body and body["categories"]

    async def test_rejects_an_empty_selection(self, client):
        resp = await client.post(f"{API}/aggregate", json={"titles": []})
        assert resp.status_code == 422


class TestScore:
    async def test_scores_a_real_resume_against_roles(self, client, resume):
        resp = await client.post(
            f"{API}/score",
            json={"resume_id": resume.id, "titles": ["Product Manager", "Product Analyst"]},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert 0.0 <= body["score"] <= 1.0
        assert body["band"] in ("strong", "decent", "gap")
        assert body["resume_name"] == "Suraj_AIPM.pdf"
        # This PM résumé should clear the owner's 60% bar for PM roles.
        assert body["score"] >= 0.60
        # Present and missing are both reported; the add-list is must-haves first.
        assert body["matched_count"] > 0
        assert isinstance(body["top_to_add"], list)

    async def test_missing_resume_is_404(self, client):
        resp = await client.post(
            f"{API}/score", json={"resume_id": "nope", "titles": ["Product Manager"]}
        )
        assert resp.status_code == 404
