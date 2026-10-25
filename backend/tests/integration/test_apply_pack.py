"""The application pack: what it contains, and that it never invents an answer."""

from __future__ import annotations

from app.models.application import Application
from app.models.enums import ApplicationStatus
from app.models.job import Job
from app.models.resume import Resume
from app.models.user_settings import UserSettings
from tests.conftest import TEST_USER_ID

CV = """Alex Morgan
London, UK
Product manager with six years shipping B2B data products. Owned the roadmap and
prioritisation for an analytics platform used by enterprise customers.
KEY SKILLS
Roadmap, Prioritisation, Stakeholder management, SQL, Agile
WORK EXPERIENCE
Senior Product Manager, Northwind Labs, March 2021 - Present
• Led discovery with 30 customers and cut time-to-value by 40% through a guided setup.
• Defined OKRs and metrics for the analytics dashboard, reviewed weekly with leadership.
"""
POSTING = (
    "Requirements: strong SQL, stakeholder management, prioritisation and a product roadmap. "
    "Defining metrics for a payments platform. Nice to have: go-to-market."
)


async def _seed(db, *, profile=None, with_resume=True):  # noqa: ANN001, ANN202
    resume = None
    if with_resume:
        resume = Resume(user_id=TEST_USER_ID, name="alex.pdf", type="base", template_id="m",
                        content_text=CV, file_path_pdf="users/x/uploads/a.pdf")
        db.add(resume)
    job = Job(user_id=TEST_USER_ID, platform="careers:monzo", platform_job_id="p1",
              title="Senior Product Manager", company="Monzo", location="London",
              url="https://monzo.example/jobs/1", description=POSTING, status="new")
    db.add(job)
    if profile is not None:
        db.add(UserSettings(user_id=TEST_USER_ID, candidate_profile=profile))
    await db.flush()
    app = Application(user_id=TEST_USER_ID, job_id=job.id, resume_id=resume.id if resume else None,
                      apply_mode="review", status=ApplicationStatus.PENDING_REVIEW)
    db.add(app)
    await db.commit()
    return app


def _answers(body):  # noqa: ANN001, ANN202
    return {a["question"]: a for a in body["answers"]}


class TestApplyPack:
    async def test_pack_contents(self, client, db_session, current_user) -> None:
        app = await _seed(db_session, profile={"full_name": "Alex Morgan", "email": "a@example.com"})
        resp = await client.get(f"/api/v1/applications/{app.id}/pack")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["employer_url"] == "https://monzo.example/jobs/1"
        assert body["cv"]["download_path"].endswith("format=pdf")
        assert body["manual_reason"]  # live apply is off in tests
        assert 0 <= body["fit_overall"] <= 1
        assert any("Attach the CV" in c for c in body["checklist"])

    async def test_profile_facts_are_supported_and_unknowns_are_placeholders(
        self, client, db_session, current_user
    ) -> None:
        app = await _seed(db_session, profile={"full_name": "Alex Morgan", "email": "a@example.com"})
        answers = _answers((await client.get(f"/api/v1/applications/{app.id}/pack")).json())
        assert answers["Full name"] == {
            "question": "Full name", "answer": "Alex Morgan",
            "evidence_status": "supported", "note": "",
        }
        for q in (
            "Phone",
            "Do you have the right to work in the UK?",
            "Will you now or in the future require visa sponsorship?",
            "What is your notice period?",
            "What are your salary expectations?",
        ):
            assert answers[q]["answer"] == "[Add only if true]", q
            assert answers[q]["evidence_status"] == "add_only_if_true", q

    async def test_why_this_role_quotes_the_cv_and_is_never_marked_as_fact(
        self, client, db_session, current_user
    ) -> None:
        app = await _seed(db_session, profile={})
        answers = _answers((await client.get(f"/api/v1/applications/{app.id}/pack")).json())
        why = answers["Why do you want to work at Monzo?"]
        assert "Senior Product Manager role centres on" in why["answer"]
        # It carries a placeholder for the candidate's own reason, so it is add-only-if-true.
        assert why["evidence_status"] == "add_only_if_true"

    async def test_no_cv_is_said_plainly(self, client, db_session, current_user) -> None:
        app = await _seed(db_session, profile={}, with_resume=False)
        body = (await client.get(f"/api/v1/applications/{app.id}/pack")).json()
        assert body["cv"] is None and body["fit_overall"] is None
        assert any("none is linked" in c for c in body["checklist"])

    async def test_unknown_application_is_404(self, client, db_session, current_user) -> None:
        assert (await client.get("/api/v1/applications/nope/pack")).status_code == 404
