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

    async def test_providers_are_derived_from_the_gateway_not_a_fixed_list(self, client):
        """This used to assert exactly five providers named openai/groq/gemini/openrouter/
        github with hard-coded model names. That list was the defect: the configured gateway
        offers none of those model ids, and "configured" only ever meant "an API key string
        was non-empty". The endpoint now reports whatever the gateway actually routes."""
        from unittest.mock import AsyncMock, MagicMock, patch

        from app.core.llm.discovery import reset_cache

        reset_cache()
        response = MagicMock()
        response.json.return_value = {
            "data": [{"id": "Full-Send", "owned_by": "combo"},
                     {"id": "oc/sonnet", "owned_by": "opencode"}]
        }
        response.raise_for_status = MagicMock()
        http = MagicMock()
        http.get = AsyncMock(return_value=response)
        http.__aenter__ = AsyncMock(return_value=http)
        http.__aexit__ = AsyncMock(return_value=False)

        try:
            with patch("httpx.AsyncClient", return_value=http):
                body = (await client.get(f"{API_PREFIX}/llm-providers")).json()
        finally:
            reset_cache()

        assert {item["provider"] for item in body} == {"combo", "opencode"}
        assert all(item["model"] for item in body), "each names a real routable model"

    async def test_an_unreachable_gateway_reports_no_providers_rather_than_five_fake_ones(
        self, client
    ):
        import httpx
        from unittest.mock import patch

        from app.core.llm.discovery import reset_cache

        reset_cache()
        try:
            with patch("httpx.AsyncClient", side_effect=httpx.ConnectError("refused")):
                body = (await client.get(f"{API_PREFIX}/llm-providers")).json()
        finally:
            reset_cache()

        assert body == []


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


class TestAIUsageIsRealTelemetry:
    """`llm_usage` has carried provider, model, tokens, cost and purpose all along — the
    settings screen simply never asked. Every figure here is a SUM over rows the application
    wrote when it made the call; nothing is estimated."""

    @staticmethod
    def _usage(db, **overrides):  # type: ignore[no-untyped-def]
        from datetime import UTC, datetime, timedelta
        from uuid import uuid4

        from app.models.enums import LLMPurpose
        from app.models.llm_usage import LLMUsage

        data = {
            "id": uuid4().hex,
            "user_id": TEST_USER_ID,
            "provider": "combo",
            "model": "Full-Send",
            "prompt_tokens": 100,
            "completion_tokens": 50,
            "total_tokens": 150,
            "cost_usd": 0.0,
            "latency_ms": 900,
            "purpose": LLMPurpose.JOB_ANALYSIS,
        }
        row = LLMUsage(**{**data, **overrides})
        age_days = overrides.pop("_age_days", 0)
        if age_days:
            row.created_at = (datetime.now(UTC) - timedelta(days=age_days)).replace(tzinfo=None)
        db.add(row)
        return row

    async def test_totals_sum_the_recorded_calls(self, client, db_session, current_user):
        self._usage(db_session, prompt_tokens=100, completion_tokens=50, total_tokens=150)
        self._usage(db_session, prompt_tokens=200, completion_tokens=25, total_tokens=225)
        await db_session.commit()

        body = (await client.get(f"{API_PREFIX}/ai/usage?period=all")).json()

        assert body["recorded"] is True
        assert body["prompt_tokens"] == 300
        assert body["completion_tokens"] == 75
        assert body["total_tokens"] == 375
        assert body["requests"] == 2

    async def test_a_period_with_no_calls_says_so_rather_than_showing_zeroes(
        self, client, current_user
    ):
        """A row of confident zeroes reads as "measured, and it was nothing"."""
        body = (await client.get(f"{API_PREFIX}/ai/usage?period=today")).json()

        assert body["recorded"] is False
        assert body["total_tokens"] == 0

    async def test_the_breakdown_names_the_top_model_and_purpose(
        self, client, db_session, current_user
    ):
        from app.models.enums import LLMPurpose

        self._usage(db_session, model="Full-Send", total_tokens=1000)
        self._usage(db_session, model="groq/llama", total_tokens=10,
                    purpose=LLMPurpose.COVER_LETTER)
        await db_session.commit()

        body = (await client.get(f"{API_PREFIX}/ai/usage?period=all")).json()

        assert body["top_model"] == "Full-Send"
        assert body["top_purpose"] == "job_analysis"
        assert [b["key"] for b in body["by_model"]] == ["Full-Send", "groq/llama"]

    async def test_errors_are_counted_separately_from_requests(
        self, client, db_session, current_user
    ):
        self._usage(db_session)
        self._usage(db_session, error="rate limited")
        await db_session.commit()

        body = (await client.get(f"{API_PREFIX}/ai/usage?period=all")).json()
        assert body["requests"] == 2
        assert body["errors"] == 1

    async def test_an_unknown_period_falls_back_rather_than_erroring(
        self, client, current_user
    ):
        body = (await client.get(f"{API_PREFIX}/ai/usage?period=nonsense")).json()
        assert body["period"] == "7d"

    async def test_usage_needs_authentication(self, anon_client):
        assert (await anon_client.get(f"{API_PREFIX}/ai/usage")).status_code in (401, 403)


class TestAICatalogueIsDiscovered:
    """The list this replaced was five hard-coded providers with model names the configured
    gateway does not offer."""

    async def test_the_catalogue_reports_what_the_gateway_returns(
        self, client, current_user
    ):
        from unittest.mock import AsyncMock, MagicMock, patch

        from app.core.llm.discovery import reset_cache

        reset_cache()
        response = MagicMock()
        response.json.return_value = {
            "data": [
                {"id": "Full-Send", "owned_by": "combo",
                 "capabilities": {"tool_calling": True}, "context_length": 128000},
                {"id": "groq/llama-3.3-70b", "owned_by": "groq"},
            ]
        }
        response.raise_for_status = MagicMock()
        http = MagicMock()
        http.get = AsyncMock(return_value=response)
        http.__aenter__ = AsyncMock(return_value=http)
        http.__aexit__ = AsyncMock(return_value=False)

        try:
            with patch("httpx.AsyncClient", return_value=http):
                body = (await client.get(f"{API_PREFIX}/ai/catalogue?refresh=true")).json()
        finally:
            reset_cache()

        assert body["reachable"] is True
        assert body["model_count"] == 2
        assert {p["id"] for p in body["providers"]} == {"combo", "groq"}
        combo = next(p for p in body["providers"] if p["id"] == "combo")
        assert combo["models"][0]["capabilities"] == ["tool_calling"]
        assert combo["models"][0]["context_length"] == 128000

    async def test_an_unreachable_gateway_reports_the_reason(self, client, current_user):
        import httpx
        from unittest.mock import patch

        from app.core.llm.discovery import reset_cache

        reset_cache()
        try:
            with patch("httpx.AsyncClient", side_effect=httpx.ConnectError("refused")):
                body = (await client.get(f"{API_PREFIX}/ai/catalogue?refresh=true")).json()
        finally:
            reset_cache()

        assert body["reachable"] is False
        assert body["model_count"] == 0
        assert "refused" in body["error"]


class TestRoleTargetsAreExtensible:
    """A role target had five fields — title, fit, why, family, active — which cannot express
    a search anyone actually runs. Adding a criterion must not require a code change, and an
    older build must not silently drop one it does not recognise."""

    async def test_rich_criteria_round_trip(self, client):
        target = {
            "title": "AI Product Manager",
            "fit": 5,
            "family": "product",
            "seniority": ["Senior", "Lead"],
            "skills": ["roadmapping", "LLM evaluation"],
            "excluded_keywords": ["unpaid", "commission only"],
            "locations": ["London"],
            "work_mode": "hybrid",
            "min_salary_k": 80,
            "excluded_companies": ["Acme"],
            "job_boards": ["reed", "adzuna"],
            "ai_instructions": "Weight platform experience over people management.",
            "priority": 1,
            "strategy": "autonomous",
        }
        response = await client.put(f"{API_PREFIX}/", json={"role_targets": [target]})
        assert response.status_code == 200

        stored = (await client.get(f"{API_PREFIX}/")).json()["role_targets"][0]
        assert stored["skills"] == ["roadmapping", "LLM evaluation"]
        assert stored["excluded_keywords"] == ["unpaid", "commission only"]
        assert stored["min_salary_k"] == 80
        assert stored["strategy"] == "autonomous"
        assert stored["ai_instructions"].startswith("Weight platform")

    async def test_a_family_outside_the_shipped_four_is_accepted(self, client):
        """`family` was a Literal of product/engineering/architecture/data, so anyone hunting
        for design or security roles had to change code to say so."""
        response = await client.put(
            f"{API_PREFIX}/",
            json={"role_targets": [{"title": "Security Engineer", "family": "security"}]},
        )
        assert response.status_code == 200
        assert (await client.get(f"{API_PREFIX}/")).json()["role_targets"][0]["family"] == (
            "security"
        )

    async def test_an_unknown_criterion_survives_a_round_trip(self, client):
        """Losing an operator's configuration because a field was unrecognised is worse than
        carrying a field nothing reads yet."""
        await client.put(
            f"{API_PREFIX}/",
            json={"role_targets": [{"title": "PM", "clearance_required": "SC"}]},
        )
        stored = (await client.get(f"{API_PREFIX}/")).json()["role_targets"][0]
        assert stored["clearance_required"] == "SC"

    async def test_a_target_stored_in_the_old_five_field_shape_still_loads(self, client):
        """Existing rows predate every criterion above and must not fail validation."""
        await client.put(
            f"{API_PREFIX}/",
            json={"role_targets": [
                {"title": "Data Scientist", "fit": 4, "why": "MSc", "family": "data",
                 "active": True}
            ]},
        )
        stored = (await client.get(f"{API_PREFIX}/")).json()["role_targets"][0]
        assert stored["title"] == "Data Scientist"
        assert stored["skills"] == []
        assert stored["strategy"] == "approval"

    async def test_several_targets_are_independent(self, client):
        """Changing one target must not silently change another."""
        await client.put(
            f"{API_PREFIX}/",
            json={"role_targets": [
                {"title": "AI PM", "locations": ["London"], "strategy": "approval"},
                {"title": "Data Scientist", "locations": ["Remote UK"], "strategy": "autonomous"},
            ]},
        )
        stored = (await client.get(f"{API_PREFIX}/")).json()["role_targets"]
        assert stored[0]["locations"] == ["London"]
        assert stored[0]["strategy"] == "approval"
        assert stored[1]["locations"] == ["Remote UK"]
        assert stored[1]["strategy"] == "autonomous"


class TestPlatformManagement:
    """Settings and Sources must read the same registry. They previously did not: Settings
    hard-coded four platforms while the registry served fifty-five."""

    async def test_the_whole_registry_is_returned_not_a_curated_subset(self, client):
        from app.core.job_discovery.source_registry import ALL_SOURCES

        body = (await client.get(f"{API_PREFIX}/platforms")).json()

        assert body["total"] == len(ALL_SOURCES)
        assert {p["key"] for p in body["platforms"]} == {s.key for s in ALL_SOURCES}

    async def test_each_platform_carries_its_health_and_capabilities(self, client):
        body = (await client.get(f"{API_PREFIX}/platforms")).json()
        by_key = {p["key"]: p for p in body["platforms"]}

        remotive = by_key["remotive"]
        assert remotive["implemented"] is True
        assert remotive["health"] == "live"
        assert "search" in remotive["capabilities"]

    async def test_a_catalogued_source_with_no_adapter_says_so(self, client):
        body = (await client.get(f"{API_PREFIX}/platforms")).json()
        by_key = {p["key"]: p for p in body["platforms"]}

        starling = by_key["careers:starling"]
        assert starling["implemented"] is False
        assert starling["health"] == "not_implemented"

    async def test_a_blocked_portal_reports_the_reason_rather_than_a_blank(self, client):
        body = (await client.get(f"{API_PREFIX}/platforms")).json()
        trac = next(p for p in body["platforms"] if p["key"] == "tracjobs")
        assert trac["last_error"] and "403" in trac["last_error"]

    async def test_nothing_is_connected_for_a_user_with_no_sessions(self, client):
        body = (await client.get(f"{API_PREFIX}/platforms")).json()

        assert body["connected"] == 0
        assert all(p["connected"] is False for p in body["platforms"])
        assert all(p["connection_state"] == "not_connected" for p in body["platforms"])

    async def test_a_connected_session_is_reported_with_a_masked_account(
        self, client, db_session, current_user
    ):
        from app.models.enums import SessionState
        from app.models.platform_session import PlatformSession

        db_session.add(PlatformSession(
            user_id=TEST_USER_ID, platform="linkedin", state=SessionState.SESSION_ACTIVE,
            account_label="suraj.pandey@example.com",
        ))
        await db_session.commit()

        body = (await client.get(f"{API_PREFIX}/platforms")).json()
        linkedin = next(p for p in body["platforms"] if p["key"] == "linkedin")

        assert linkedin["connected"] is True
        # Masked on read as well as on write — a row from an older build must not leak.
        assert linkedin["account"] == "sur***@example.com"
        assert body["connected"] == 1

    async def test_an_expired_session_is_not_reported_as_connected(
        self, client, db_session, current_user
    ):
        """Saying "connected" when the agent cannot authenticate sends the operator looking
        in entirely the wrong place."""
        from app.models.enums import SessionState
        from app.models.platform_session import PlatformSession

        db_session.add(PlatformSession(
            user_id=TEST_USER_ID, platform="indeed", state=SessionState.SESSION_EXPIRED,
            state_detail="Session expired three days ago.",
        ))
        await db_session.commit()

        body = (await client.get(f"{API_PREFIX}/platforms")).json()
        indeed = next(p for p in body["platforms"] if p["key"] == "indeed")

        assert indeed["connected"] is False
        assert indeed["connection_state"] == "session_expired"
        assert "expired" in indeed["detail"]

    async def test_enablement_comes_from_the_users_saved_settings(
        self, client
    ):
        await client.put(f"{API_PREFIX}/", json={"platforms_enabled": ["remotive"]})

        body = (await client.get(f"{API_PREFIX}/platforms")).json()
        by_key = {p["key"]: p for p in body["platforms"]}

        assert by_key["remotive"]["enabled"] is True
        assert by_key["jobicy"]["enabled"] is False

    async def test_actions_state_why_they_are_unavailable(self, client):
        """A disabled control with a reason beats a button that silently does nothing."""
        body = (await client.get(f"{API_PREFIX}/platforms")).json()
        by_key = {p["key"]: p for p in body["platforms"]}

        # A keyless public API needs no login, and says so rather than hiding the control.
        connect = next(a for a in by_key["remotive"]["actions"] if a["key"] == "connect")
        assert connect["available"] is False
        assert "public API" in connect["reason"]

        # A source with no adapter cannot be enabled for discovery.
        toggle = next(
            a for a in by_key["careers:starling"]["actions"] if a["key"] == "toggle"
        )
        assert toggle["available"] is False
        assert "adapter" in toggle["reason"]

    async def test_no_credential_appears_in_the_payload(self, client, db_session, current_user):
        from app.models.enums import SessionState
        from app.models.platform_session import PlatformSession

        db_session.add(PlatformSession(
            user_id=TEST_USER_ID, platform="linkedin", state=SessionState.SESSION_ACTIVE,
            account_label="sur***@example.com", fingerprint_hash="deadbeefcafe",
        ))
        await db_session.commit()

        raw = (await client.get(f"{API_PREFIX}/platforms")).text.lower()
        for forbidden in ("password", "cookie", "token", "storage_state", "deadbeefcafe"):
            assert forbidden not in raw

    async def test_the_endpoint_needs_authentication(self, anon_client):
        assert (await anon_client.get(f"{API_PREFIX}/platforms")).status_code in (401, 403)
