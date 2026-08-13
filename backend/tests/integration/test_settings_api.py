"""Integration tests for the Settings API routes."""

from app.core.policy import RULES
from app.models.application import Application
from app.models.enums import ApplicationStatus
from app.models.job import Job
from tests.conftest import TEST_USER_ID

API_PREFIX = "/api/v1/settings"


class TestGetSettings:
    """Tests for GET /api/v1/settings/."""

    async def test_get_default_settings(self, client):
        response = await client.get(f"{API_PREFIX}/")

        assert response.status_code == 200
        body = response.json()
        assert body["apply_mode"] == "review"
        assert body["min_ats_score"] == 0.75
        assert body["max_parallel"] == 3
        assert isinstance(body["platforms_enabled"], list)
        assert "linkedin" in body["platforms_enabled"]


class TestUpdateSettings:
    """Tests for PUT /api/v1/settings/."""

    async def test_update_partial_settings(self, client):
        response = await client.put(
            f"{API_PREFIX}/",
            json={"apply_mode": "autonomous", "max_parallel": 5},
        )

        assert response.status_code == 200
        body = response.json()
        assert body["apply_mode"] == "autonomous"
        assert body["max_parallel"] == 5
        # Unchanged fields should remain at defaults
        assert body["min_ats_score"] == 0.75

    async def test_update_min_ats_score(self, client):
        response = await client.put(
            f"{API_PREFIX}/",
            json={"min_ats_score": 0.9},
        )

        assert response.status_code == 200
        assert response.json()["min_ats_score"] == 0.9

    async def test_update_platforms_enabled(self, client):
        response = await client.put(
            f"{API_PREFIX}/",
            json={"platforms_enabled": ["linkedin"]},
        )

        assert response.status_code == 200
        assert response.json()["platforms_enabled"] == ["linkedin"]


class TestListLLMProviders:
    """Tests for GET /api/v1/settings/llm-providers."""

    async def test_list_providers_returns_defaults(self, client):
        response = await client.get(f"{API_PREFIX}/llm-providers")

        assert response.status_code == 200
        body = response.json()
        assert isinstance(body, list)
        assert len(body) == 5

        providers = {item["provider"] for item in body}
        assert {"openai", "groq", "gemini", "openrouter", "github"} <= providers

        for item in body:
            assert "configured" in item
            assert "model" in item


class TestAutomationPolicyCatalogue:
    """GET /api/v1/settings/automation-policy — the schema-driven UI's data source."""

    async def test_the_catalogue_carries_every_rule_with_its_control(self, client):
        response = await client.get(f"{API_PREFIX}/automation-policy")

        assert response.status_code == 200
        body = response.json()
        rules = [r for g in body["groups"] for r in g["rules"]]
        assert {r["id"] for r in rules} == {r.id for r in RULES}
        for rule in rules:
            assert rule["clause"]
            assert rule["rationale"]
            assert rule["control"]["kind"]

    async def test_a_locked_invariant_says_so_and_offers_nothing_to_change(self, client):
        """The §1 clauses are shown so the operator can see what the system will not do.
        Presenting one as editable would be a lie the UI then has nowhere to store."""
        response = await client.get(f"{API_PREFIX}/automation-policy")
        rules = {r["id"]: r for g in response.json()["groups"] for r in g["rules"]}

        fabrication = rules["integrity.no_fabrication"]
        assert fabrication["locked"] is True
        assert fabrication["control"]["kind"] == "locked"
        assert fabrication["value"] is None
        assert fabrication["enforced_by"]

    async def test_the_catalogue_reflects_what_the_operator_actually_saved(self, client):
        await client.put(f"{API_PREFIX}/", json={"automation": {"max_per_day": 7}})

        response = await client.get(f"{API_PREFIX}/automation-policy")
        rules = {r["id"]: r for g in response.json()["groups"] for r in g["rules"]}
        assert rules["volume.daily_cap"]["value"] == 7
        assert response.json()["policy"]["max_per_day"] == 7

    async def test_groups_are_ordered_for_presentation(self, client):
        response = await client.get(f"{API_PREFIX}/automation-policy")
        ids = [g["id"] for g in response.json()["groups"]]
        # Oversight first (the kill switch), integrity last (nothing to change).
        assert ids[0] == "oversight"
        assert ids[-1] == "integrity"

    async def test_the_endpoint_needs_authentication(self, anon_client):
        response = await anon_client.get(f"{API_PREFIX}/automation-policy")
        assert response.status_code in (401, 403)


class TestAutomationPolicyPreview:
    """POST /api/v1/settings/automation-policy/preview — dry-run before saving."""

    async def test_an_empty_queue_previews_as_nothing_evaluated(self, client):
        response = await client.post(
            f"{API_PREFIX}/automation-policy/preview", json={"max_per_day": 5}
        )

        assert response.status_code == 200
        assert response.json()["evaluated"] == 0

    async def test_a_candidate_policy_is_judged_without_being_saved(
        self, client, db_session, current_user
    ):
        """The whole point is to see a change's blast radius before committing to it. If the
        preview saved, there would be nothing to preview."""
        job = Job(
            user_id=TEST_USER_ID,
            platform="careers:monzo",
            platform_job_id="preview-1",
            title="Product Manager",
            company="Monzo",
            location="London",
            url="https://example.invalid/1",
            description="",
            status="new",
        )
        db_session.add(job)
        await db_session.commit()
        db_session.add(
            Application(
                user_id=TEST_USER_ID,
                job_id=job.id,
                apply_mode="review",
                status=ApplicationStatus.QUEUED,
                ats_score=0.5,
            )
        )
        await db_session.commit()

        response = await client.post(
            f"{API_PREFIX}/automation-policy/preview",
            json={"min_ats_score": 0.9, "run_window": {"days": [], "timezone": "UTC"}},
        )

        assert response.status_code == 200
        body = response.json()
        assert body["evaluated"] == 1
        assert body["items"][0]["company"] == "Monzo"
        assert "match.min_ats_score" in body["items"][0]["rule_ids"]
        assert body["items"][0]["reasons"], "a refusal must say why"

        # Nothing persisted: the stored policy still has its default threshold.
        saved = await client.get(f"{API_PREFIX}/automation-policy")
        assert saved.json()["policy"]["min_ats_score"] == 0.75

    async def test_an_invalid_candidate_policy_is_rejected_not_silently_clamped(self, client):
        """A threshold above 1.0 is a client bug. Clamping it would hide the bug and apply a
        rule the operator did not ask for."""
        response = await client.post(
            f"{API_PREFIX}/automation-policy/preview", json={"min_ats_score": 5}
        )
        assert response.status_code == 422
