"""Unit tests for all Pydantic schemas."""

import pytest
from pydantic import ValidationError

from app.config.constants import SUPPORTED_PLATFORMS
from app.schemas.analytics import (
    ATSScoreDistribution,
    DashboardStats,
    LLMUsageStats,
)
from app.schemas.application import (
    ApplicationBatchCreate,
    ApplicationCreate,
    ApplicationListResponse,
    ApplicationStatusUpdate,
)
from app.schemas.job import JobListingResponse, JobListResponse, JobSearchRequest
from app.schemas.resume import (
    ExtractedProfileData,
    ResumeGenerateRequest,
    ResumeScoreResponse,
    ResumeUploadResponse,
)
from app.schemas.settings import (
    CandidateProfileSchema,
    LLMProviderStatus,
    RoleTargetSchema,
    SettingsResponse,
    SettingsUpdate,
    WorkExperienceSchema,
)

# ---------------------------------------------------------------------------
# JobSearchRequest
# ---------------------------------------------------------------------------


class TestJobSearchRequest:
    def test_defaults(self):
        req = JobSearchRequest(query="python developer")
        assert req.query == "python developer"
        assert req.location == ""
        # API sources lead the default fan-out. Defaulting to the three browser platforms
        # alone made every search hit only the broken scrape path and return zero,
        # silently overriding whatever else was registered.
        # None means 'use the default fan-out'; an explicit [] means 'search nothing'.
        assert req.platforms is None
        assert SUPPORTED_PLATFORMS[:4] == ["remotive", "jobicy", "arbeitnow", "remoteok"]
        assert req.filters == {}
        assert req.limit == 20

    def test_all_fields(self):
        req = JobSearchRequest(
            query="backend engineer",
            location="NYC",
            platforms=["linkedin"],
            filters={"remote": True},
            limit=50,
        )
        assert req.location == "NYC"
        assert req.platforms == ["linkedin"]
        assert req.filters == {"remote": True}
        assert req.limit == 50

    def test_limit_ge_1(self):
        with pytest.raises(ValidationError):
            JobSearchRequest(query="test", limit=0)

    def test_limit_le_100(self):
        with pytest.raises(ValidationError):
            JobSearchRequest(query="test", limit=101)

    def test_query_min_length(self):
        with pytest.raises(ValidationError):
            JobSearchRequest(query="")

    def test_query_required(self):
        with pytest.raises(ValidationError):
            JobSearchRequest()

    def test_query_accepts_a_realistic_joined_title_list(self):
        """Regression: the frontend's default query joins every active role-target title
        with ', ' — 31 default titles alone run to ~690 chars. A 500-char cap 422'd every
        default search before it ran, which looked like total job-discovery breakage from
        the UI (nothing to select, nothing to preview) with no visible error."""
        titles = [f"Senior Example Role Title Number {i}" for i in range(31)]
        long_query = ", ".join(titles)
        assert len(long_query) > 690
        req = JobSearchRequest(query=long_query)
        assert req.query == long_query

    def test_query_max_length_2000(self):
        JobSearchRequest(query="x" * 2000)
        with pytest.raises(ValidationError):
            JobSearchRequest(query="x" * 2001)


# ---------------------------------------------------------------------------
# JobListingResponse
# ---------------------------------------------------------------------------


class TestJobListingResponse:
    def test_model_validate_from_dict(self):
        data = {
            "id": "abc123",
            "platform": "linkedin",
            "platform_job_id": "job-1",
            "title": "Dev",
            "company": "Acme",
            "location": "Remote",
            "url": "https://example.com",
            "description": "desc",
            "status": "new",
            "created_at": "2025-01-01T00:00:00",
            "updated_at": "2025-01-01T00:00:00",
        }
        resp = JobListingResponse.model_validate(data)
        assert resp.id == "abc123"
        assert resp.remote is False
        assert resp.salary_range is None
        # Defaults to unknown, not a false "not sponsor", when the source data has no
        # sponsorship field at all (e.g. a job row from before sponsor matching existed).
        assert resp.sponsor_confidence == "unknown"
        assert resp.sponsor_evidence is None

    def test_sponsor_fields_reach_the_response(self):
        """Pins a real gap: sponsor_confidence/sponsor_evidence were computed, stored, and
        used for ranking, but never reached this response — the frontend had no way to
        show per-job sponsorship status despite the backend already knowing it."""
        data = {
            "id": "abc123", "platform": "reed", "platform_job_id": "job-3", "title": "Dev",
            "company": "Acme", "location": "London", "url": "https://example.com",
            "description": "desc", "status": "new",
            "created_at": "2025-01-01T00:00:00", "updated_at": "2025-01-01T00:00:00",
            "sponsor_confidence": "confirmed_register", "sponsor_evidence": "Acme Ltd",
        }
        resp = JobListingResponse.model_validate(data)
        assert resp.sponsor_confidence == "confirmed_register"
        assert resp.sponsor_evidence == "Acme Ltd"

    def test_optional_fields(self):
        data = {
            "id": "abc123",
            "platform": "indeed",
            "platform_job_id": "job-2",
            "title": "Engineer",
            "company": "Corp",
            "location": "NYC",
            "url": "https://example.com",
            "description": "desc",
            "status": "saved",
            "created_at": "2025-01-01T00:00:00",
            "updated_at": "2025-01-01T00:00:00",
            "salary_range": "$100k-$150k",
            "remote": True,
            "match_score": 0.92,
        }
        resp = JobListingResponse.model_validate(data)
        assert resp.salary_range == "$100k-$150k"
        assert resp.remote is True
        assert resp.match_score == 0.92


# ---------------------------------------------------------------------------
# JobListResponse
# ---------------------------------------------------------------------------


class TestJobListResponse:
    def test_with_items_and_pagination(self):
        resp = JobListResponse(items=[], total=0, page=1, page_size=20, has_next=False)
        assert resp.items == []
        assert resp.total == 0
        assert resp.has_next is False

    def test_has_next_true(self):
        resp = JobListResponse(items=[], total=50, page=1, page_size=20, has_next=True)
        assert resp.has_next is True


# ---------------------------------------------------------------------------
# ApplicationCreate
# ---------------------------------------------------------------------------


class TestApplicationCreate:
    def test_defaults(self):
        app = ApplicationCreate(job_id="job1")
        assert app.job_id == "job1"
        assert app.resume_id is None
        assert app.apply_mode == "review"

    def test_explicit_fields(self):
        app = ApplicationCreate(job_id="job1", resume_id="res1", apply_mode="autonomous")
        assert app.resume_id == "res1"
        assert app.apply_mode == "autonomous"


# ---------------------------------------------------------------------------
# ApplicationBatchCreate
# ---------------------------------------------------------------------------


class TestApplicationBatchCreate:
    def test_valid_batch(self):
        batch = ApplicationBatchCreate(job_ids=["j1", "j2"])
        assert len(batch.job_ids) == 2

    def test_min_length_validation(self):
        with pytest.raises(ValidationError):
            ApplicationBatchCreate(job_ids=[])


# ---------------------------------------------------------------------------
# ApplicationStatusUpdate
# ---------------------------------------------------------------------------


class TestApplicationStatusUpdate:
    def test_with_status_only(self):
        update = ApplicationStatusUpdate(status="applied")
        assert update.status == "applied"
        assert update.notes is None

    def test_with_notes(self):
        update = ApplicationStatusUpdate(status="rejected", notes="Not a fit")
        assert update.notes == "Not a fit"


# ---------------------------------------------------------------------------
# ApplicationListResponse
# ---------------------------------------------------------------------------


class TestApplicationListResponse:
    def test_pagination_fields(self):
        resp = ApplicationListResponse(
            items=[], total=5, page=1, page_size=20, has_next=False
        )
        assert resp.total == 5
        assert resp.page == 1
        assert resp.page_size == 20
        assert resp.has_next is False


# ---------------------------------------------------------------------------
# ResumeGenerateRequest
# ---------------------------------------------------------------------------


class TestResumeGenerateRequest:
    def test_defaults(self):
        req = ResumeGenerateRequest(base_resume_id="r1", job_id="j1")
        assert req.template_id == "modern"
        assert req.output_formats == ["pdf", "docx"]

    def test_custom_values(self):
        req = ResumeGenerateRequest(
            base_resume_id="r1",
            job_id="j1",
            template_id="classic",
            output_formats=["pdf"],
        )
        assert req.template_id == "classic"
        assert req.output_formats == ["pdf"]


# ---------------------------------------------------------------------------
# ResumeScoreResponse
# ---------------------------------------------------------------------------


class TestResumeScoreResponse:
    def test_all_score_fields_present(self):
        resp = ResumeScoreResponse(
            resume_id="r1",
            job_id="j1",
            overall_score=0.8,
            skill_score=0.9,
            experience_score=0.7,
            education_score=0.6,
            keyword_score=0.5,
        )
        assert resp.overall_score == 0.8
        assert resp.skill_score == 0.9
        assert resp.experience_score == 0.7
        assert resp.education_score == 0.6
        assert resp.keyword_score == 0.5
        assert resp.missing_skills == []
        assert resp.suggestions == []


# ---------------------------------------------------------------------------
# ResumeUploadResponse
# ---------------------------------------------------------------------------


class TestResumeUploadResponse:
    def test_required_fields(self):
        resp = ResumeUploadResponse(
            id="r1", name="my_resume.pdf", file_format="pdf", word_count=500
        )
        assert resp.id == "r1"
        assert resp.name == "my_resume.pdf"
        assert resp.file_format == "pdf"
        assert resp.word_count == 500
        assert resp.skills_detected == []

    def test_missing_required_field_raises(self):
        with pytest.raises(ValidationError):
            ResumeUploadResponse(id="r1", name="my_resume.pdf", file_format="pdf")


# ---------------------------------------------------------------------------
# DashboardStats
# ---------------------------------------------------------------------------


class TestDashboardStats:
    def test_all_defaults_are_zero(self):
        stats = DashboardStats()
        assert stats.total_jobs_found == 0
        assert stats.total_applications == 0
        assert stats.applications_pending == 0
        assert stats.applications_applied == 0
        assert stats.applications_interview == 0
        assert stats.applications_rejected == 0
        assert stats.applications_offer == 0
        assert stats.avg_ats_score == 0.0
        assert stats.total_llm_cost_usd == 0.0


# ---------------------------------------------------------------------------
# ATSScoreDistribution
# ---------------------------------------------------------------------------


class TestATSScoreDistribution:
    def test_required_fields(self):
        dist = ATSScoreDistribution(range_label="80-100", count=5)
        assert dist.range_label == "80-100"
        assert dist.count == 5

    def test_missing_field_raises(self):
        with pytest.raises(ValidationError):
            ATSScoreDistribution(range_label="0-20")


# ---------------------------------------------------------------------------
# LLMUsageStats
# ---------------------------------------------------------------------------


class TestLLMUsageStats:
    def test_required_fields(self):
        usage = LLMUsageStats(provider="openai", model="gpt-4")
        assert usage.provider == "openai"
        assert usage.model == "gpt-4"
        assert usage.total_requests == 0
        assert usage.total_tokens == 0
        assert usage.total_cost_usd == 0.0
        assert usage.avg_latency_ms == 0.0


# ---------------------------------------------------------------------------
# SettingsUpdate
# ---------------------------------------------------------------------------


class TestSettingsUpdate:
    def test_partial_update_all_optional(self):
        update = SettingsUpdate()
        assert update.apply_mode is None
        assert update.min_ats_score is None
        assert update.max_parallel is None
        assert update.platforms_enabled is None
        assert update.candidate_profile is None

    def test_single_field_update(self):
        update = SettingsUpdate(apply_mode="autonomous")
        assert update.apply_mode == "autonomous"

    def test_min_ats_score_ge_0(self):
        with pytest.raises(ValidationError):
            SettingsUpdate(min_ats_score=-0.1)

    def test_min_ats_score_le_1(self):
        with pytest.raises(ValidationError):
            SettingsUpdate(min_ats_score=1.1)

    def test_min_ats_score_valid_bounds(self):
        assert SettingsUpdate(min_ats_score=0.0).min_ats_score == 0.0
        assert SettingsUpdate(min_ats_score=1.0).min_ats_score == 1.0

    def test_max_parallel_ge_1(self):
        with pytest.raises(ValidationError):
            SettingsUpdate(max_parallel=0)

    def test_max_parallel_le_5(self):
        with pytest.raises(ValidationError):
            SettingsUpdate(max_parallel=6)

    def test_max_parallel_valid_bounds(self):
        assert SettingsUpdate(max_parallel=1).max_parallel == 1
        assert SettingsUpdate(max_parallel=5).max_parallel == 5


# ---------------------------------------------------------------------------
# LLMProviderStatus
# ---------------------------------------------------------------------------


class TestLLMProviderStatus:
    def test_defaults(self):
        status = LLMProviderStatus(provider="openai")
        assert status.provider == "openai"
        assert status.configured is False
        assert status.model == ""
        assert status.is_primary is False

    def test_configured_provider(self):
        status = LLMProviderStatus(
            provider="anthropic", configured=True, model="claude-3", is_primary=True
        )
        assert status.configured is True
        assert status.model == "claude-3"
        assert status.is_primary is True


# ---------------------------------------------------------------------------
# ExtractedProfileData / WorkExperienceSchema alias tolerance
#
# Pins a real bug: a live LLM extraction call returned a correct, complete work
# history under the keys `work_experience`/`job_title`/`employer` instead of the
# schema's `experience`/`title`/`company`. Pydantic silently falls back to each
# field's default on an unrecognised key rather than raising, so the call
# "succeeded" while reporting 0 roles found and discarding a perfect answer.
# ---------------------------------------------------------------------------


class TestWorkExperienceSchemaAliases:
    def test_primary_field_names_still_work(self):
        entry = WorkExperienceSchema(title="ML Engineer", company="Acme")
        assert entry.title == "ML Engineer"
        assert entry.company == "Acme"

    def test_job_title_and_employer_synonyms_populate_the_same_fields(self):
        entry = WorkExperienceSchema.model_validate(
            {"job_title": "ML Engineer", "employer": "Acme"}
        )
        assert entry.title == "ML Engineer"
        assert entry.company == "Acme"


class TestExtractedProfileDataAliases:
    def test_primary_field_names_still_work(self):
        data = ExtractedProfileData.model_validate(
            {
                "experience": [{"title": "Analyst", "company": "Pixis"}],
                "education": [{"degree": "BSc", "institution": "MIT-WPU"}],
            }
        )
        assert len(data.experience) == 1
        assert len(data.education) == 1

    def test_work_experience_synonym_does_not_silently_discard_real_data(self):
        """The exact shape a live LLM call returned for a real résumé.

        Before the AliasChoices fix, this silently validated to an EMPTY
        experience list instead of raising or preserving the data.
        """
        data = ExtractedProfileData.model_validate(
            {
                "work_experience": [
                    {
                        "job_title": "Data Scientist",
                        "employer": "SimplyPhi",
                        "start_date": "June 2024",
                        "end_date": "Present",
                    },
                    {
                        "job_title": "Technology Analyst",
                        "employer": "Pixis",
                        "start_date": "Jan 2021",
                        "end_date": "July 2023",
                    },
                ],
                "education": [
                    {"degree": "MSc Business Analytics", "institution": "Warwick"},
                ],
            }
        )
        assert len(data.experience) == 2
        assert data.experience[0].title == "Data Scientist"
        assert data.experience[0].company == "SimplyPhi"
        assert data.experience[1].title == "Technology Analyst"
        assert data.experience[1].company == "Pixis"
        assert len(data.education) == 1

    def test_education_history_synonym_populates_education(self):
        data = ExtractedProfileData.model_validate(
            {"education_history": [{"degree": "BSc", "institution": "MIT-WPU"}]}
        )
        assert len(data.education) == 1
        assert data.education[0].degree == "BSc"

    def test_unrecognised_key_with_no_synonym_still_falls_back_to_default(self):
        """Guards the boundary of the fix: an alias list is not infinite tolerance.

        A genuinely novel key an LLM might invent still defaults quietly rather
        than raising — documenting the residual risk, not eliminating it.
        """
        data = ExtractedProfileData.model_validate({"prior_roles": [{"title": "X"}]})
        assert data.experience == []


# ---------------------------------------------------------------------------
# CandidateProfileSchema malformed-data tolerance
#
# Pins a real, live 500: GET /api/v1/settings/ crashed with an unhandled
# pydantic ValidationError for an account whose stored candidate_profile had a
# non-string skill, a bare string in place of an experience dict, and a bare
# string in place of the education list. One bad list item took the whole
# settings response down instead of degrading gracefully.
# ---------------------------------------------------------------------------


class TestCandidateProfileSchemaResilience:
    def test_well_formed_profile_is_unaffected(self):
        profile = CandidateProfileSchema.model_validate(
            {
                "skills": ["python", "sql"],
                "experience": [{"title": "Eng", "company": "Acme"}],
                "education": [{"degree": "BSc", "institution": "MIT"}],
            }
        )
        assert profile.skills == ["python", "sql"]
        assert len(profile.experience) == 1
        assert len(profile.education) == 1

    def test_non_string_skill_entries_are_dropped_not_crashed_on(self):
        profile = CandidateProfileSchema.model_validate(
            {"skills": [123, None, "python"]}
        )
        assert profile.skills == ["python"]

    def test_non_dict_experience_entry_is_dropped_not_crashed_on(self):
        profile = CandidateProfileSchema.model_validate(
            {"experience": [{"title": "Eng"}, "not a dict"]}
        )
        assert len(profile.experience) == 1
        assert profile.experience[0].title == "Eng"

    def test_education_as_a_bare_string_degrades_to_empty_list(self):
        profile = CandidateProfileSchema.model_validate(
            {"education": "BSc Computer Science"}
        )
        assert profile.education == []

    def test_the_exact_live_crash_shape_no_longer_raises(self):
        """The precise stored shape that raised ValidationError out of GET /settings/."""
        profile = CandidateProfileSchema.model_validate(
            {
                "skills": [123, None, "python"],
                "experience": [{"duration_years": "two", "title": "Eng"}, "not a dict"],
                "education": "BSc Computer Science",
            }
        )
        assert profile.skills == ["python"]
        assert len(profile.experience) == 1
        assert profile.education == []


# ---------------------------------------------------------------------------
# RoleTargetSchema / SettingsResponse.role_targets malformed-data tolerance
#
# Same crash class as CandidateProfileSchema, proactively hardened before it
# became a live incident: role_targets is the same kind of loosely-typed JSON
# column, so a non-dict entry in the list or a non-string entry in one of its
# criteria lists would raise the identical unhandled ValidationError out of
# GET /settings/.
# ---------------------------------------------------------------------------


class TestRoleTargetSchemaResilience:
    def test_non_string_entries_in_a_criteria_list_are_dropped(self):
        target = RoleTargetSchema.model_validate(
            {"title": "Eng", "alternative_titles": [123, None, "SWE"]}
        )
        assert target.alternative_titles == ["SWE"]

    def test_a_bare_string_in_place_of_a_criteria_list_degrades_to_empty(self):
        target = RoleTargetSchema.model_validate({"title": "Eng", "skills": "python"})
        assert target.skills == []

    def test_settings_response_drops_non_dict_role_target_entries(self):
        response = SettingsResponse.model_validate(
            {
                "role_targets": [
                    {"title": "Eng", "alternative_titles": [123, None, "SWE"], "skills": "python"},
                    "not a dict",
                    None,
                ],
            }
        )
        assert len(response.role_targets) == 1
        assert response.role_targets[0].alternative_titles == ["SWE"]
        assert response.role_targets[0].skills == []
