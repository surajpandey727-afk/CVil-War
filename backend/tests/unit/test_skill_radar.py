"""The Skill Radar aggregation and résumé scoring.

These pin the behaviour the owner asked for: pick a set of roles, see the skills they share,
score a résumé against them, and treat 60-70% as "decent — most skills covered". The matching
cases are the ones that quietly go wrong — slash-joined terms, substrings, plurals.
"""

import pytest

from app.core.skills.aggregate import DECENT_FLOOR, STRONG_CEILING, _present, aggregate, match_resume
from app.core.skills.catalog import SKILLS
from app.core.skills.roles import family_for_title, skills_for_title


class TestMatching:
    def test_slash_joined_terms_match(self):
        # "Agile/Scrum", "CI/CD", "A/B testing" are how résumés actually write these.
        assert _present(SKILLS["agile"], "agile/scrum delivery") == "agile"
        assert _present(SKILLS["cicd"], "built ci/cd pipelines") == "ci/cd"
        assert _present(SKILLS["experimentation"], "ran a/b testing") == "a/b testing"

    def test_substrings_do_not_false_match(self):
        assert _present(SKILLS["sql"], "experience with mysql") is None
        assert _present(SKILLS["ml"], "wrote html and css") is None

    def test_plurals_and_singulars_match(self):
        assert _present(SKILLS["prd"], "wrote prds for three launches") == "prd"
        assert _present(SKILLS["roadmap"], "owned two roadmaps") == "roadmap"


class TestAggregate:
    def test_a_skill_every_role_wants_ranks_first(self):
        agg = aggregate(["Product Manager", "Product Analyst", "Technical Product Manager"])
        top = agg[0]
        assert top.roles_wanting == 3
        assert top.must_have is True

    def test_aggregation_is_driven_by_the_selection(self):
        # Engineering roles surface ML/Python/MLOps; product roles surface roadmap/metrics.
        eng = {a.skill.key for a in aggregate(["ML Engineer"])[:6]}
        pm = {a.skill.key for a in aggregate(["Product Manager"])[:6]}
        assert "python" in eng and "roadmap" not in eng
        assert "roadmap" in pm and "python" not in pm

    def test_corpus_counts_are_passed_through_when_supplied(self):
        agg = aggregate(["Product Manager"], corpus_counts={"roadmap": 42})
        by_key = {a.skill.key: a for a in agg}
        assert by_key["roadmap"].corpus_count == 42
        # A skill the corpus didn't count stays None, never 0 — "not looked at" != "absent".
        assert by_key["metrics"].corpus_count is None

    def test_an_unknown_title_falls_back_to_its_family(self):
        # A title with no explicit profile still resolves via its family.
        assert skills_for_title("Senior Product Manager, Payments") == skills_for_title("Product Manager")
        assert family_for_title("Staff Data Analyst") == "data"


class TestScoring:
    _STRONG_PM = (
        "Product manager, 7 years B2B SaaS. Owned the product roadmap and prioritisation "
        "with RICE. Defined KPIs, OKRs and north star metrics. Ran A/B testing and "
        "experimentation. Strong stakeholder management and cross-functional leadership. "
        "Product strategy and vision. SQL and product analytics with Amplitude. Agile/Scrum. "
        "Wrote PRDs, ran product discovery, led go-to-market."
    )

    def test_a_strong_pm_resume_clears_the_decent_band_for_pm_roles(self):
        r = match_resume(self._STRONG_PM, ["Product Manager", "Product Analyst"])
        assert r.score >= DECENT_FLOOR
        assert r.band in ("decent", "strong")

    def test_the_same_resume_scores_lower_against_ai_pm_roles(self):
        # It names no ML/GenAI, which AI PM roles require — the Radar should say so.
        r = match_resume(self._STRONG_PM, ["AI Product Manager"])
        missing = {h.skill.key for h in r.top_to_add}
        assert "genai" in missing or "ml" in missing

    def test_top_to_add_puts_must_haves_first(self):
        r = match_resume("I write Python.", ["Product Manager"])
        # The highest-value gaps for a PM are core PM skills, not nice-to-haves.
        assert r.top_to_add[0].must_have is True

    def test_band_thresholds(self):
        from app.core.skills.aggregate import _band

        assert _band(STRONG_CEILING) == "strong"
        assert _band(DECENT_FLOOR) == "decent"
        assert _band(0.59) == "gap"

    def test_must_have_score_is_reported_separately(self):
        # A résumé can clear overall coverage while missing a core requirement; the two numbers
        # must be able to disagree.
        r = match_resume(self._STRONG_PM, ["AI Product Manager"])
        assert 0.0 <= r.must_have_score <= 1.0
        assert r.must_have_score != r.score  # they measure different things

    def test_empty_resume_scores_zero_and_everything_is_missing(self):
        r = match_resume("", ["Product Manager"])
        assert r.score == 0.0
        assert len(r.matched) == 0
        assert r.band == "gap"


@pytest.mark.parametrize(
    "titles",
    [["AI Product Manager"], ["ML Engineer", "Data Scientist"], ["Product Analyst"]],
)
def test_every_curated_role_aggregates_to_a_non_empty_ranked_list(titles):
    agg = aggregate(titles)
    assert len(agg) >= 8
    # Sorted by roles_wanting desc then demand desc — monotonic non-increasing on the key.
    keys = [(a.roles_wanting, a.demand) for a in agg]
    assert keys == sorted(keys, key=lambda k: (-k[0], -k[1]))
