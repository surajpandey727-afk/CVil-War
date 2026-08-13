"""Integration tests for the Analytics API routes."""



API_PREFIX = "/api/v1/analytics"


class TestDashboard:
    """Tests for GET /api/v1/analytics/dashboard."""

    async def test_dashboard_empty_db(self, client):
        response = await client.get(f"{API_PREFIX}/dashboard")

        assert response.status_code == 200
        body = response.json()
        assert body["total_jobs_found"] == 0
        assert body["total_applications"] == 0
        assert body["applications_pending"] == 0
        assert body["applications_applied"] == 0
        assert body["applications_interview"] == 0
        assert body["applications_rejected"] == 0
        assert body["applications_offer"] == 0
        assert body["avg_ats_score"] == 0.0
        assert body["total_llm_cost_usd"] == 0.0


class TestFunnel:
    """Tests for GET /api/v1/analytics/funnel."""

    async def test_funnel_returns_all_stages(self, client):
        response = await client.get(f"{API_PREFIX}/funnel")

        assert response.status_code == 200
        body = response.json()
        assert isinstance(body, list)
        assert len(body) == 9  # 9 funnel stages defined in _FUNNEL_STAGES

        stages = [entry["stage"] for entry in body]
        assert "queued" in stages
        assert "approved" in stages
        assert "applied" in stages
        assert "interview" in stages
        assert "offer" in stages
        assert "rejected" in stages

        # All counts should be zero on empty DB
        for entry in body:
            assert entry["count"] == 0


class TestATSScores:
    """Tests for GET /api/v1/analytics/ats-scores."""

    async def test_ats_scores_returns_distribution_buckets(self, client):
        response = await client.get(f"{API_PREFIX}/ats-scores")

        assert response.status_code == 200
        body = response.json()
        assert isinstance(body, list)
        assert len(body) == 5  # 5 score range buckets

        labels = [bucket["range_label"] for bucket in body]
        assert "0-20" in labels
        assert "20-40" in labels
        assert "40-60" in labels
        assert "60-80" in labels
        assert "80-100" in labels

        for bucket in body:
            assert bucket["count"] == 0


class TestLLMUsage:
    """Tests for GET /api/v1/analytics/llm-usage."""

    async def test_llm_usage_returns_empty_list(self, client):
        response = await client.get(f"{API_PREFIX}/llm-usage")

        assert response.status_code == 200
        body = response.json()
        assert isinstance(body, list)
        assert len(body) == 0


class TestTimeline:
    """Tests for GET /api/v1/analytics/timeline."""

    async def test_timeline_returns_empty_list(self, client):
        response = await client.get(f"{API_PREFIX}/timeline")

        assert response.status_code == 200
        body = response.json()
        assert isinstance(body, list)
        assert len(body) == 0


class TestDashboardCountsAreReal:
    """Every number on the dashboard has to come from a row. None of these are hard-coded,
    and the time-boxed ones count submissions rather than rows created — a queued
    application is not an application sent."""

    @staticmethod
    def _seed(db, statuses):  # type: ignore[no-untyped-def]
        from datetime import UTC, datetime, timedelta
        from uuid import uuid4

        from app.models.application import Application
        from app.models.job import Job
        from tests.conftest import TEST_USER_ID

        now = datetime.now(UTC).replace(tzinfo=None)
        for index, (status, applied_offset_days) in enumerate(statuses):
            job = Job(
                id=uuid4().hex, user_id=TEST_USER_ID, platform="reed",
                platform_job_id=f"a{index}", title="PM", company="Acme",
                location="London", url="https://example.invalid/x", description="",
                status="new",
            )
            db.add(job)
            db.add(
                Application(
                    id=uuid4().hex, user_id=TEST_USER_ID, job_id=job.id,
                    apply_mode="review", status=status,
                    applied_at=(
                        None if applied_offset_days is None
                        else now - timedelta(days=applied_offset_days)
                    ),
                )
            )

    async def test_activity_and_failure_counts_track_the_rows(
        self, client, db_session, current_user
    ):
        from app.models.enums import ApplicationStatus

        self._seed(
            db_session,
            [
                (ApplicationStatus.QUEUED, None),
                (ApplicationStatus.QUEUED, None),
                (ApplicationStatus.APPLYING, None),
                (ApplicationStatus.FAILED, None),
                (ApplicationStatus.APPLIED, 0),
            ],
        )
        await db_session.commit()

        body = (await client.get("/api/v1/analytics/dashboard")).json()

        assert body["applications_queued"] == 2
        assert body["applications_applying"] == 1
        assert body["applications_failed"] == 1

    async def test_sent_today_and_this_week_use_the_submission_timestamp(
        self, client, db_session, current_user
    ):
        from app.models.enums import ApplicationStatus

        self._seed(
            db_session,
            [
                (ApplicationStatus.APPLIED, 0),   # today
                (ApplicationStatus.APPLIED, 3),   # this week, not today
                (ApplicationStatus.APPLIED, 30),  # neither
                (ApplicationStatus.QUEUED, None),  # never sent — must not count at all
            ],
        )
        await db_session.commit()

        body = (await client.get("/api/v1/analytics/dashboard")).json()

        assert body["submitted_today"] == 1
        assert body["submitted_this_week"] == 2

    async def test_an_empty_account_reports_zero_rather_than_a_placeholder(
        self, client, current_user
    ):
        body = (await client.get("/api/v1/analytics/dashboard")).json()
        assert body["applications_queued"] == 0
        assert body["submitted_today"] == 0
        assert body["applications_failed"] == 0
