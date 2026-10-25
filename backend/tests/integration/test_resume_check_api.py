"""Résumé checker API: deterministic check + Claude review, end to end through the routes."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.core.llm.client import LLMResponse
from app.core.resume_check.review import LlmReview
from app.models.job import Job
from app.models.resume import Resume
from tests.conftest import TEST_USER_ID

API = "/api/v1/resume-checker"

CV = """Alex Morgan
London, UK
M: 07700 900123 | E: alex.morgan@example.com
Product manager with six years shipping B2B data products. Owned the roadmap and
prioritisation for an analytics platform used by enterprise customers, working with
engineering, design and sales to turn discovery into delivered outcomes.
KEY SKILLS
Roadmap, Prioritisation, Stakeholder management, SQL, Agile
WORK EXPERIENCE
Northwind Labs, London, (Platform Team)
Senior Product Manager March 2021 - Present
• Responsible for the onboarding flow for new enterprise accounts.
• Led discovery with 30 customers and cut time-to-value by 40% through a guided setup.
• Defined OKRs and metrics for the analytics dashboard, reviewed weekly with leadership.
• Wrote PRDs and user stories with engineering for each quarterly release.
EDUCATION
BSc Computer Science, University of Leeds, 2016
"""

POSTING = """We're hiring a Senior Product Manager in London.
What you'll do:
Own the product roadmap for our payments platform.
Requirements:
Proven prioritisation and stakeholder management.
Strong SQL and experience defining metrics.
Experience with A/B testing and experimentation.
Nice to have:
Go-to-market experience.
"""


async def _seed(db) -> tuple[Resume, Job]:  # noqa: ANN001
    resume = Resume(
        user_id=TEST_USER_ID, name="alex.pdf", type="base", template_id="modern", content_text=CV
    )
    job = Job(
        user_id=TEST_USER_ID,
        platform="careers:monzo",
        platform_job_id="rc-1",
        title="Senior Product Manager",
        company="Monzo",
        location="London",
        url="https://example.invalid/j",
        description=POSTING,
        status="new",
    )
    db.add_all([resume, job])
    await db.commit()
    return resume, job


class TestCheck:
    async def test_job_target_returns_the_full_report(self, client, db_session) -> None:
        resume, job = await _seed(db_session)
        resp = await client.post(f"{API}/check", json={"resume_id": resume.id, "job_id": job.id})
        assert resp.status_code == 200, resp.text
        body = resp.json()

        assert body["target"] == {
            "kind": "job",
            "job_id": job.id,
            "title": "Senior Product Manager",
            "company": "Monzo",
            "role_titles": [],
        }
        score = body["score"]
        assert 0 <= score["overall"] <= 1
        weights = {c["key"]: c["weight"] for c in score["components"]}
        assert weights == {"must_have": 0.45, "nice_to_have": 0.2, "ats": 0.2, "sections": 0.15}
        recomputed = sum(c["weight"] * c["score"] for c in score["components"])
        assert score["overall"] == pytest.approx(recomputed, abs=1e-3)
        assert "0.45" in score["formula"]

        matched = {m["key"]: m for m in body["matched_skills"]}
        assert "sql" in matched
        for m in body["matched_skills"]:
            for ev in m["evidence"]:
                # Evidence is quoted verbatim from the résumé, never paraphrased.
                assert ev["quote"].strip("…") in " ".join(CV.split())

        missing = body["missing_skills"]
        assert missing, "an A/B-testing must-have is not in the CV"
        musts = [m["must_have"] for m in missing]
        assert musts == sorted(musts, reverse=True), "must-haves are ranked first"

        assert {s["key"] for s in body["sections"]} == {
            "summary", "experience", "skills", "formatting",
        }
        exp = next(s for s in body["sections"] if s["key"] == "experience")
        assert any("open with a duty" in f for f in exp["findings"])

    async def test_weak_bullet_rewrite_is_marked_add_only_if_true(self, client, db_session):
        resume, job = await _seed(db_session)
        body = (
            await client.post(f"{API}/check", json={"resume_id": resume.id, "job_id": job.id})
        ).json()
        rewrites = [s for s in body["suggestions"] if s["kind"] == "rewrite"]
        weak = next(s for s in rewrites if "onboarding flow" in s["original"])
        assert weak["evidence_status"] == "add_only_if_true"
        assert "[outcome]" in weak["suggested"]
        adds = [s for s in body["suggestions"] if s["kind"] == "add" and s["section"] == "skills"]
        missing_must = [s for s in adds if s["evidence_status"] == "add_only_if_true"]
        assert missing_must, "a missing must-have is only ever suggested as add-only-if-true"

    async def test_roles_target(self, client, db_session) -> None:
        resume, _ = await _seed(db_session)
        resp = await client.post(
            f"{API}/check",
            json={"resume_id": resume.id, "role_titles": ["Product Manager"]},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["target"]["kind"] == "roles"
        assert body["corpus"]["uk_jobs_scanned"] >= 0
        assert body["matched_skills"]

    async def test_uk_demand_counts_only_uk_jobs(self, client, db_session) -> None:
        resume, job = await _seed(db_session)
        db_session.add_all(
            [
                Job(
                    user_id=TEST_USER_ID,
                    platform="reed",
                    platform_job_id=f"uk-{i}",
                    title="PM",
                    company="X",
                    location="Manchester",
                    url="https://example.invalid/u",
                    description="Must have A/B testing experience.",
                    status="new",
                )
                for i in range(3)
            ]
            + [
                Job(
                    user_id=TEST_USER_ID,
                    platform="remotive",
                    platform_job_id="us-1",
                    title="PM",
                    company="Y",
                    location="Austin, Texas, United States",
                    url="https://example.invalid/us",
                    description="Must have A/B testing experience.",
                    status="new",
                )
            ]
        )
        await db_session.commit()
        body = (
            await client.post(f"{API}/check", json={"resume_id": resume.id, "job_id": job.id})
        ).json()
        ab = next(m for m in body["missing_skills"] if m["key"] == "experimentation")
        # 3 seeded UK postings + the London target posting itself; the US posting is excluded.
        assert ab["uk_demand"] == 4
        assert body["corpus"]["uk_jobs_scanned"] >= 3

    async def test_exactly_one_target_is_required(self, client, db_session) -> None:
        resume, job = await _seed(db_session)
        none = await client.post(f"{API}/check", json={"resume_id": resume.id})
        both = await client.post(
            f"{API}/check",
            json={"resume_id": resume.id, "job_id": job.id, "role_titles": ["Product Manager"]},
        )
        assert none.status_code == 422
        assert both.status_code == 422

    async def test_unknown_resume_is_404(self, client, db_session) -> None:
        resp = await client.post(f"{API}/check", json={"resume_id": "nope", "role_titles": ["PM"]})
        assert resp.status_code == 404

    async def test_a_resume_with_no_text_is_a_clear_422(self, client, db_session) -> None:
        r = Resume(user_id=TEST_USER_ID, name="scan.pdf", type="base", template_id="modern")
        db_session.add(r)
        await db_session.commit()
        resp = await client.post(f"{API}/check", json={"resume_id": r.id, "role_titles": ["PM"]})
        assert resp.status_code == 422
        assert "No readable text" in resp.json()["detail"]

    async def test_requires_authentication(self, anon_client) -> None:
        resp = await anon_client.post(f"{API}/check", json={"resume_id": "x", "role_titles": ["PM"]})
        assert resp.status_code == 401


def _llm(review: LlmReview) -> AsyncMock:
    meta = LLMResponse(content="{}", model="anthropic/claude-sonnet-5-5", provider="anthropic")
    client = AsyncMock()
    client.complete_json = AsyncMock(return_value=(review, meta))
    return client


class TestReview:
    async def test_valid_review_is_returned_with_policy_marks(self, client, db_session) -> None:
        resume, job = await _seed(db_session)
        review = LlmReview(
            summary="Solid PM fit; the gap is experimentation.",
            section_notes=[
                {"section": "experience", "note": "Lead with outcomes."},
                {"section": "nonsense", "note": "dropped"},
            ],
            rewrites=[
                {  # verbatim original, adds an invented metric -> add_only_if_true
                    "section": "experience",
                    "original": "Responsible for the onboarding flow for new enterprise accounts.",
                    "suggested": "Rebuilt the onboarding flow for new enterprise accounts, "
                    "lifting activation by 25%.",
                    "reason": "Outcome-led.",
                },
                {  # verbatim original, no new claims -> supported
                    "section": "experience",
                    "original": "Wrote PRDs and user stories with engineering for each "
                    "quarterly release.",
                    "suggested": "Wrote PRDs and user stories with engineering for each "
                    "quarterly release",
                    "reason": "Tighter.",
                },
                {  # invented original -> rejected
                    "section": "experience",
                    "original": "Managed a team of 12 at Google.",
                    "suggested": "Led 12 engineers at Google.",
                    "reason": "x",
                },
            ],
        )
        with patch(
            "app.core.llm.factory.build_llm_client_for_user",
            new=AsyncMock(return_value=_llm(review)),
        ):
            resp = await client.post(
                f"{API}/review", json={"resume_id": resume.id, "job_id": job.id}
            )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["available"] is True
        assert body["model"] == "anthropic/claude-sonnet-5-5"
        assert [n["section"] for n in body["section_notes"]] == ["experience"]
        statuses = [s["evidence_status"] for s in body["suggestions"]]
        assert statuses == ["add_only_if_true", "supported"]
        assert all(s["source"] == "llm" for s in body["suggestions"])
        assert body["rejected_count"] == 2  # bad section + invented original

    async def test_provider_failure_is_reported_not_raised(self, client, db_session) -> None:
        from app.core.exceptions import LLMProviderError

        resume, job = await _seed(db_session)
        broken = AsyncMock()
        broken.complete_json = AsyncMock(
            side_effect=LLMProviderError("anthropic", "ANTHROPIC_API_KEY is not set")
        )
        with patch(
            "app.core.llm.factory.build_llm_client_for_user", new=AsyncMock(return_value=broken)
        ):
            resp = await client.post(
                f"{API}/review", json={"resume_id": resume.id, "job_id": job.id}
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["available"] is False
        assert body["detail"] == "The server has no Anthropic API key configured."
        assert body["suggestions"] == []

    async def test_malformed_json_is_reported(self, client, db_session) -> None:
        from app.core.exceptions import LLMProviderError

        resume, job = await _seed(db_session)
        broken = AsyncMock()
        broken.complete_json = AsyncMock(
            side_effect=LLMProviderError("anthropic", "Failed to parse structured output: x")
        )
        with patch(
            "app.core.llm.factory.build_llm_client_for_user", new=AsyncMock(return_value=broken)
        ):
            body = (
                await client.post(f"{API}/review", json={"resume_id": resume.id, "job_id": job.id})
            ).json()
        assert body["available"] is False
        assert "expected format" in body["detail"]
