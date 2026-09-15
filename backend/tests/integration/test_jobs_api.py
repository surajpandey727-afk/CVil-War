"""Integration tests for the Jobs API routes."""

import pytest

from app.models.job import Job

API_PREFIX = "/api/v1/jobs"


@pytest.fixture
def job_data(sample_job_data):
    """Provide sample_job_data with skills_required as a dict (matching schema)."""
    data = dict(sample_job_data)
    data["skills_required"] = {"python": True, "fastapi": True, "postgresql": True}
    return data


class TestSearchJobs:
    """Tests for POST /api/v1/jobs/search."""

    async def test_search_with_no_platforms_selected_returns_empty(self, client):
        """Explicitly selecting no sources must short-circuit, not fan out.

        This previously asserted that a DEFAULT search returns zero — which only held because
        every default platform was broken. It now pins the real contract and, importantly,
        keeps the suite off the network: a default search hits four live job APIs.
        """
        response = await client.post(
            f"{API_PREFIX}/search",
            json={"query": "python developer", "location": "Remote", "platforms": []},
        )

        assert response.status_code == 200
        body = response.json()
        assert body["items"] == []
        assert body["total"] == 0
        assert body["page"] == 1
        assert body["has_next"] is False

    async def test_search_requires_query(self, client):
        response = await client.post(f"{API_PREFIX}/search", json={})

        assert response.status_code == 422

    async def test_search_rejects_empty_query(self, client):
        response = await client.post(f"{API_PREFIX}/search", json={"query": ""})

        assert response.status_code == 422


class TestListJobs:
    """Tests for GET /api/v1/jobs/."""

    async def test_list_empty(self, client):
        response = await client.get(f"{API_PREFIX}/")

        assert response.status_code == 200
        body = response.json()
        assert body["items"] == []
        assert body["total"] == 0
        assert body["page"] == 1
        assert body["has_next"] is False

    async def test_list_with_pagination_params(self, client):
        response = await client.get(f"{API_PREFIX}/", params={"page": 2, "page_size": 5})

        assert response.status_code == 200
        body = response.json()
        assert body["page"] == 2
        assert body["page_size"] == 5

    async def test_list_returns_created_job(self, client, db_session, job_data):
        job = Job(**job_data)
        db_session.add(job)
        await db_session.commit()
        await db_session.refresh(job)

        response = await client.get(f"{API_PREFIX}/")

        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 1
        assert len(body["items"]) == 1
        assert body["items"][0]["title"] == "Senior Python Developer"
        assert body["items"][0]["company"] == "TechCorp Inc."

    async def test_list_filter_by_status(self, client, db_session, job_data):
        job = Job(**job_data)
        db_session.add(job)
        await db_session.commit()

        response = await client.get(f"{API_PREFIX}/", params={"status": "new"})
        assert response.status_code == 200
        assert response.json()["total"] == 1

        response = await client.get(f"{API_PREFIX}/", params={"status": "applied"})
        assert response.status_code == 200
        assert response.json()["total"] == 0


class TestGetJob:
    """Tests for GET /api/v1/jobs/{job_id}."""

    async def test_get_nonexistent_returns_404(self, client):
        response = await client.get(f"{API_PREFIX}/nonexistent-id")

        assert response.status_code == 404

    async def test_get_existing_job(self, client, db_session, job_data):
        job = Job(**job_data)
        db_session.add(job)
        await db_session.commit()
        await db_session.refresh(job)

        response = await client.get(f"{API_PREFIX}/{job.id}")

        assert response.status_code == 200
        body = response.json()
        assert body["id"] == job.id
        assert body["title"] == "Senior Python Developer"
        assert body["platform"] == "linkedin"
        assert body["remote"] is True


class TestUpdateJobStatus:
    """Tests for PATCH /api/v1/jobs/{job_id} — previously no way existed to save/hide a job."""

    async def test_patch_nonexistent_returns_404(self, client):
        response = await client.patch(f"{API_PREFIX}/nonexistent-id", json={"status": "saved"})

        assert response.status_code == 404

    async def test_saves_a_job(self, client, db_session, job_data):
        job = Job(**job_data)
        db_session.add(job)
        await db_session.commit()
        await db_session.refresh(job)

        response = await client.patch(f"{API_PREFIX}/{job.id}", json={"status": "saved"})

        assert response.status_code == 200
        assert response.json()["status"] == "saved"

    async def test_rejects_an_invalid_status(self, client, db_session, job_data):
        job = Job(**job_data)
        db_session.add(job)
        await db_session.commit()
        await db_session.refresh(job)

        response = await client.patch(f"{API_PREFIX}/{job.id}", json={"status": "not_a_real_status"})

        assert response.status_code == 422


class TestAnalyzeJob:
    """Tests for POST /api/v1/jobs/{job_id}/analyze."""

    async def test_analyze_nonexistent_returns_404(self, client):
        response = await client.post(f"{API_PREFIX}/nonexistent-id/analyze")

        assert response.status_code == 404

    async def test_analyze_existing_job(self, client, db_session, job_data):
        job = Job(**job_data)
        db_session.add(job)
        await db_session.commit()
        await db_session.refresh(job)

        response = await client.post(f"{API_PREFIX}/{job.id}/analyze")

        assert response.status_code == 200
        body = response.json()
        assert body["job_id"] == job.id
        assert "match_score" in body
        assert "skill_match" in body
        assert "keyword_match" in body
        assert "missing_skills" in body
        assert "suggestions" in body


class TestDeleteJob:
    """Tests for DELETE /api/v1/jobs/{job_id}."""

    async def test_delete_nonexistent_returns_404(self, client):
        response = await client.delete(f"{API_PREFIX}/nonexistent-id")

        assert response.status_code == 404

    async def test_delete_existing_job(self, client, db_session, job_data):
        job = Job(**job_data)
        db_session.add(job)
        await db_session.commit()
        await db_session.refresh(job)

        response = await client.delete(f"{API_PREFIX}/{job.id}")
        assert response.status_code == 204

        # Verify job is gone
        response = await client.get(f"{API_PREFIX}/{job.id}")
        assert response.status_code == 404


class TestLocationFilteringEndToEnd:
    """The filter has to survive the whole round trip, not just exist in a helper.

    It previously existed nowhere: `GET /jobs` took no location parameter at all, so a London
    search returned every job the account had ever stored — including a Cleveland
    accounts-payable role and a Worldwide office assistant.
    """

    @staticmethod
    def _job(user_id, **overrides):  # type: ignore[no-untyped-def]
        from uuid import uuid4

        from app.models.job import Job

        data = {
            "id": uuid4().hex,
            "user_id": user_id,
            "platform": "reed",
            "platform_job_id": uuid4().hex[:12],
            "title": "Product Manager",
            "company": "Acme",
            "location": "London",
            "url": "https://example.invalid/j",
            "description": "",
            "status": "new",
        }
        return Job(**{**data, **overrides})

    async def _seed(self, db_session):  # type: ignore[no-untyped-def]
        from tests.conftest import TEST_USER_ID

        rows = [
            self._job(TEST_USER_ID, title="Senior Product Manager", location="London, UK"),
            self._job(TEST_USER_ID, title="Group Product Manager", location="Canary Wharf"),
            self._job(TEST_USER_ID, title="Product Owner", location="EC4N6EU"),
            self._job(TEST_USER_ID, title="Assistant Account Payable", location="USA"),
            self._job(TEST_USER_ID, title="Remote Office Assistant", location="Worldwide",
                      remote=True),
            self._job(TEST_USER_ID, title="Sales Jedi", location="Europe"),
            self._job(TEST_USER_ID, title="Delivery Manager", location="United Kingdom"),
            self._job(TEST_USER_ID, title="Data Engineer", location="Manchester"),
        ]
        for row in rows:
            db_session.add(row)
        await db_session.commit()

    async def test_a_london_filter_returns_only_london_jobs(self, client, db_session):
        await self._seed(db_session)

        response = await client.get("/api/v1/jobs/?location=London&page_size=100")

        assert response.status_code == 200
        body = response.json()
        locations = {item["location"] for item in body["items"]}
        assert locations == {"London, UK", "Canary Wharf", "EC4N6EU"}
        assert "USA" not in locations
        assert "United Kingdom" not in locations
        assert "Worldwide" not in locations

    async def test_the_reported_total_counts_matches_not_stored_rows(self, client, db_session):
        """`total` drives the "38 roles" counter. Counting every stored job while showing a
        filtered list is how the UI came to claim results it was not displaying."""
        await self._seed(db_session)

        body = (await client.get("/api/v1/jobs/?location=London&page_size=100")).json()
        assert body["total"] == 3

    async def test_pagination_pages_through_the_filtered_set(self, client, db_session):
        """Filtering client-side meant page 2 of a London search was not London at all."""
        await self._seed(db_session)

        page1 = (await client.get("/api/v1/jobs/?location=London&page=1&page_size=2")).json()
        page2 = (await client.get("/api/v1/jobs/?location=London&page=2&page_size=2")).json()

        assert len(page1["items"]) == 2
        assert page1["has_next"] is True
        assert len(page2["items"]) == 1
        assert page2["has_next"] is False
        seen = {i["location"] for i in page1["items"]} | {i["location"] for i in page2["items"]}
        assert seen == {"London, UK", "Canary Wharf", "EC4N6EU"}

    async def test_the_title_filter_is_applied_server_side_too(self, client, db_session):
        await self._seed(db_session)

        body = (await client.get("/api/v1/jobs/?q=Product%20Manager&page_size=100")).json()
        titles = {i["title"] for i in body["items"]}

        assert "Senior Product Manager" in titles
        assert "Assistant Account Payable" not in titles

    async def test_location_and_title_filters_combine(self, client, db_session):
        await self._seed(db_session)

        body = (
            await client.get("/api/v1/jobs/?location=London&q=Product%20Manager&page_size=100")
        ).json()
        titles = {i["title"] for i in body["items"]}

        assert titles == {"Senior Product Manager", "Group Product Manager"}

    async def test_a_newly_imported_job_is_filtered_by_the_same_rule(self, client, db_session):
        """No static list anywhere: the filter reads Job.location, so an import added after
        the fact is filtered on its own merits."""
        from tests.conftest import TEST_USER_ID

        await self._seed(db_session)
        db_session.add(
            self._job(TEST_USER_ID, title="Late Import PM", location="Shoreditch, London")
        )
        await db_session.commit()

        body = (await client.get("/api/v1/jobs/?location=London&page_size=100")).json()
        assert "Late Import PM" in {i["title"] for i in body["items"]}

    async def test_no_filter_still_returns_everything(self, client, db_session):
        await self._seed(db_session)

        body = (await client.get("/api/v1/jobs/?page_size=100")).json()
        assert body["total"] == 8


class TestResumeRecommendation:
    """GET /api/v1/jobs/{job_id}/resume-recommendation — backs the floating ATS widget."""

    async def test_404_for_an_unknown_job(self, client):
        response = await client.get(f"{API_PREFIX}/nonexistent/resume-recommendation")
        assert response.status_code == 404

    async def test_no_resumes_is_reported_honestly_not_as_an_error(
        self, client, db_session, job_data
    ):
        job = Job(**job_data)
        db_session.add(job)
        await db_session.commit()

        response = await client.get(f"{API_PREFIX}/{job.id}/resume-recommendation")
        assert response.status_code == 200
        body = response.json()
        assert body["recommended_resume_id"] is None
        assert body["rankings"] == []

    async def test_ranks_multiple_resumes_and_names_the_winner(
        self, client, db_session, job_data
    ):
        from app.models.resume import Resume
        from tests.conftest import TEST_USER_ID

        job = Job(**job_data)
        db_session.add(job)
        strong = Resume(
            user_id=TEST_USER_ID, name="Tailored CV", type="base", template_id="modern",
            content_text="Experienced Python FastAPI PostgreSQL engineer",
        )
        weak = Resume(
            user_id=TEST_USER_ID, name="Generic CV", type="base", template_id="modern",
            content_text="Looking for any opportunity",
        )
        db_session.add_all([strong, weak])
        await db_session.commit()

        response = await client.get(f"{API_PREFIX}/{job.id}/resume-recommendation")
        assert response.status_code == 200
        body = response.json()
        assert len(body["rankings"]) == 2
        assert body["recommended_resume_id"] == strong.id
        assert body["rankings"][0]["resume_id"] == strong.id
        assert "Tailored CV" in body["synopsis"]
