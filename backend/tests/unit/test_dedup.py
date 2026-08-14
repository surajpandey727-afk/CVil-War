"""Cross-source deduplication.

The failure this prevents is the most visible one automation can produce: three applications
to one employer for one role, because the vacancy was discovered on three boards.

The asymmetry that shapes every threshold here: a false merge hides a real job the operator
will never see, and a missed merge shows a duplicate they can ignore. When the evidence is
thin, listings stay separate.
"""

from __future__ import annotations

import pytest

from app.core.job_discovery.dedup import (
    JobIdentity,
    canonical_url,
    companies_match,
    group,
    locations_compatible,
    normalise_company,
    same_job,
    title_tokens,
    titles_match,
)


def identity(**kw) -> JobIdentity:  # type: ignore[no-untyped-def]
    base = {
        "source": "reed", "source_id": "1", "company": "Monzo",
        "title": "Senior Product Manager", "location": "London", "url": "",
        "application_url": "",
    }
    return JobIdentity(**{**base, **kw})


class TestCompanyNormalisation:
    @pytest.mark.parametrize(
        ("left", "right"),
        [
            ("Ocado", "Ocado Group"),
            ("Monzo", "Monzo Bank Ltd"),
            ("Wise", "WISE"),
            ("Acme Technologies", "Acme"),
            ("Foo Limited", "Foo Ltd"),
            ("Monzo Bank", "Monzo"),
        ],
    )
    def test_one_employer_written_several_ways_still_matches(self, left, right) -> None:  # type: ignore[no-untyped-def]
        """No stopword list survives this indefinitely — strip "bank" and you must then strip
        "group", "labs", "studios" for ever. Containment handles the family."""
        assert companies_match(left, right)

    def test_genuinely_different_employers_do_not_match(self) -> None:
        assert not companies_match("Monzo", "Starling")
        assert not companies_match("Ocado", "Tesco")

    def test_an_empty_name_matches_nothing(self) -> None:
        assert not companies_match("", "Monzo")
        assert not companies_match("Monzo", "")

    def test_normalisation_strips_suffixes_and_case(self) -> None:
        assert normalise_company("Foo Limited") == normalise_company("FOO ltd")


class TestTitleMatching:
    def test_seniority_and_punctuation_do_not_split_one_role(self) -> None:
        assert titles_match("Senior Product Manager", "Product Manager, Senior")
        assert titles_match("Product Manager (m/w/d)", "Product Manager")

    def test_a_trailing_location_suffix_still_matches(self) -> None:
        """Boards routinely append "- London - Hybrid" to an otherwise identical title. The
        place words come from the listing's own location field, not a hard-coded city list,
        which is why the caller supplies them."""
        assert titles_match(
            "Product Manager", "Product Manager - London - Hybrid",
            ignore=frozenset({"london"}),
        )

    def test_an_extra_role_word_is_not_forgiven(self) -> None:
        """The merge that Jaccard fixes: measured against the shorter title, a subset scored
        1.0 and merged these two on real data."""
        assert not titles_match("Product Manager, EU", "Product Marketing Manager")

    def test_a_different_seniority_is_a_different_posting(self) -> None:
        """Identical role words, two postings. Stripping the level merged them."""
        assert not titles_match("Staff Software Engineer", "Senior Software Engineer")
        assert not titles_match("Machine Learning Engineer", "Senior Machine Learning Engineer")

    def test_different_roles_do_not_match(self) -> None:
        # The specific pair that a 0.5 threshold merged: both reduce to two words sharing one.
        assert not titles_match("Product Manager", "Product Designer")
        assert not titles_match("Product Manager", "Security Engineer")
        assert not titles_match("Data Engineer", "Data Scientist")

    def test_an_empty_title_never_matches(self) -> None:
        assert not titles_match("", "Product Manager")
        assert not titles_match("Product Manager", "")

    def test_noise_only_titles_produce_no_tokens(self) -> None:
        """A title of nothing but filler must not match everything."""
        assert title_tokens("Senior (m/w/d)") == frozenset()
        assert not titles_match("Senior (m/w/d)", "Senior Engineer")


class TestUrlCanonicalisation:
    def test_tracking_parameters_do_not_make_one_url_into_several(self) -> None:
        a = canonical_url("https://jobs.example.com/123?utm_source=reed&utm_medium=feed")
        b = canonical_url("https://jobs.example.com/123")
        assert a == b

    def test_scheme_host_case_and_trailing_slash_are_normalised(self) -> None:
        assert canonical_url("HTTP://WWW.Example.com/jobs/1/") == canonical_url(
            "https://example.com/jobs/1"
        )

    def test_a_meaningful_query_parameter_is_kept(self) -> None:
        """Plenty of ATS URLs carry the job id in the query; dropping it would merge every
        posting on that board into one."""
        assert canonical_url("https://x.com/apply?jobId=7") != canonical_url(
            "https://x.com/apply?jobId=8"
        )

    def test_query_order_does_not_matter(self) -> None:
        assert canonical_url("https://x.com/a?b=1&a=2") == canonical_url(
            "https://x.com/a?a=2&b=1"
        )

    def test_an_empty_url_is_empty_not_a_match_key(self) -> None:
        assert canonical_url("") == ""


class TestLocationCompatibility:
    def test_a_missing_location_never_contradicts(self) -> None:
        assert locations_compatible("London", "")
        assert locations_compatible("", "Berlin")

    def test_the_same_place_written_differently_is_compatible(self) -> None:
        assert locations_compatible("London", "London, UK")

    def test_two_specific_different_places_contradict(self) -> None:
        assert not locations_compatible("London", "Berlin")


class TestSameJob:
    def test_a_shared_application_url_is_decisive(self) -> None:
        """Two adverts pointing at one form are one vacancy, whatever they are called."""
        left = identity(source="reed", title="Product Manager",
                        application_url="https://apply.co/1")
        right = identity(source="linkedin", source_id="9", company="Monzo Bank Ltd",
                         title="Senior PM, Payments", location="Remote",
                         application_url="https://apply.co/1")
        assert same_job(left, right)

    def test_the_same_posting_rescraped_is_not_a_new_job(self) -> None:
        assert same_job(identity(), identity(title="Senior Product Manager (Updated)"))

    def test_two_postings_from_one_board_are_never_merged_by_title(self) -> None:
        """When a board publishes two postings under two of its own ids it is asserting they
        are different jobs, and it knows better than any title heuristic. Ignoring that
        merged three unrelated engineering roles on real data."""
        assert not same_job(
            identity(source="arbeitnow", source_id="1", company="Wingcopter",
                     title="UAV Operations Engineer - Data Operations"),
            identity(source="arbeitnow", source_id="2", company="Wingcopter",
                     title="Field Robotics Engineer - Data Operations"),
        )

    def test_the_cross_source_case_merges_on_employer_title_and_location(self) -> None:
        reed = identity(source="reed", source_id="1", url="https://reed.co.uk/1")
        careers = identity(source="careers:monzo", source_id="99", company="Monzo Bank Ltd",
                           title="Product Manager, Senior", location="London, UK",
                           url="https://monzo.com/careers/99")
        assert same_job(reed, careers)

    def test_two_roles_at_one_employer_stay_separate(self) -> None:
        """The merge that would hide a real job."""
        assert not same_job(
            identity(title="Senior Product Manager"),
            identity(source_id="2", title="Senior Security Engineer"),
        )

    def test_one_title_at_two_employers_stays_separate(self) -> None:
        assert not same_job(
            identity(company="Monzo"), identity(company="Starling", source_id="2")
        )

    def test_contradicting_locations_prevent_a_merge(self) -> None:
        assert not same_job(
            identity(location="London"),
            identity(source="linkedin", source_id="2", location="Berlin"),
        )

    def test_an_empty_source_id_does_not_match_another_empty_one(self) -> None:
        """Blank ids are common; treating them as equal would merge a board's whole feed."""
        left = JobIdentity(source="x", source_id="", company="A", title="Analyst",
                           location="London", url="https://a.com/1")
        right = JobIdentity(source="x", source_id="", company="B", title="Chef",
                            location="Paris", url="https://b.com/2")
        assert not same_job(left, right)


class TestGrouping:
    def test_three_sources_of_one_vacancy_become_one_group(self) -> None:
        rows = [
            identity(source="reed", source_id="1", url="https://reed.co.uk/1"),
            identity(source="linkedin", source_id="2", company="Monzo Bank",
                     title="Product Manager, Senior", url="https://li.com/2"),
            identity(source="careers:monzo", source_id="3", company="Monzo Ltd",
                     title="Senior Product Manager - London", url="https://monzo.com/3"),
        ]
        groups = group(rows)
        assert len(groups) == 1
        assert sorted(groups[0]) == [0, 1, 2]

    def test_unrelated_jobs_stay_in_their_own_groups(self) -> None:
        rows = [
            identity(company="Monzo", title="Product Manager"),
            identity(company="Starling", title="Product Manager", source_id="2"),
            identity(company="Monzo", title="Security Engineer", source_id="3"),
        ]
        assert len(group(rows)) == 3

    def test_a_bridge_listing_joins_two_that_would_not_match_directly(self) -> None:
        """A~B and B~C must put all three together: one source's wording often bridges two
        others that share too little to match on their own."""
        rows = [
            identity(source="a", source_id="1", title="Product Manager",
                     application_url="https://apply.co/x"),
            identity(source="b", source_id="2", title="Senior Product Manager Payments",
                     application_url="https://apply.co/x"),
            identity(source="c", source_id="3", title="Senior Product Manager Payments",
                     application_url="https://apply.co/y"),
        ]
        groups = group(rows)
        assert len(groups) == 1

    def test_an_empty_input_yields_no_groups(self) -> None:
        assert group([]) == []

    def test_every_listing_appears_in_exactly_one_group(self) -> None:
        rows = [identity(source_id=str(i), title=f"Role {i}") for i in range(6)]
        groups = group(rows)
        flat = [index for cluster in groups for index in cluster]
        assert sorted(flat) == list(range(6))


class TestTrackingParametersAreEnumeratedNotGuessed:
    """A prefix rule stripped Greenhouse's job id and merged five distinct postings."""

    def test_the_greenhouse_job_id_survives_canonicalisation(self) -> None:
        a = canonical_url("https://wayve.firststage.co/jobs?gh_jid=8487813002")
        b = canonical_url("https://wayve.firststage.co/jobs?gh_jid=8622191002")
        assert a != b, "gh_jid identifies the posting and must never be stripped"

    def test_the_greenhouse_source_parameter_is_still_stripped(self) -> None:
        a = canonical_url("https://x.com/jobs?gh_jid=1&gh_src=abc123")
        b = canonical_url("https://x.com/jobs?gh_jid=1")
        assert a == b

    def test_five_postings_sharing_a_path_stay_five_vacancies(self) -> None:
        rows = [
            JobIdentity(
                source="careers:wayve", source_id=str(i), company="Wayve",
                title=title, location="London",
                url=f"https://wayve.firststage.co/jobs?gh_jid={i}",
            )
            for i, title in enumerate([
                "Staff Data Scientist",
                "Senior Data Scientist",
                "Software Engineer (Product, AI Portal)",
                "Machine Learning Engineer, ADAS",
                "Senior Machine Learning Engineer, AI Performance",
            ])
        ]
        assert len(group(rows)) == 5
