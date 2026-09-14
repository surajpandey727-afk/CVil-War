"""Unit tests for app.core.sponsorship — visa-sponsorship ranking signal.

Root design constraint under test: classification here is a ranking BOOST by default, never
an automatic hard filter. Nothing here should ever cause a job to be excluded from results for
merely *lacking* sponsorship evidence (``UNKNOWN``) — an explicit *no*-sponsorship statement
(``NOT_SPONSOR``) is different, real evidence, and turning that into a hard exclude is an
opt-in policy choice (``AutomationPolicy.exclude_no_sponsorship``), tested separately in
``test_policy_engine.py``, not something this module does on its own.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

from app.core.sponsorship import keywords, register
from app.core.sponsorship.classify import classify
from app.models.enums import SponsorConfidence

# ---------------------------------------------------------------------------
# keywords.detect
# ---------------------------------------------------------------------------


class TestKeywordDetection:
    def test_detects_explicit_sponsorship_language(self) -> None:
        detected, phrase = keywords.detect("We offer visa sponsorship available for this role.")
        assert detected is True
        assert "sponsorship" in phrase

    def test_detects_skilled_worker_language(self) -> None:
        detected, _ = keywords.detect("This role is eligible under the Skilled Worker route.")
        assert detected is True

    def test_no_match_on_plain_description(self) -> None:
        detected, phrase = keywords.detect("We are looking for a senior data scientist.")
        assert detected is False
        assert phrase == ""

    def test_negation_suppresses_a_positive_match(self) -> None:
        """"No visa sponsorship available" contains "sponsorship available" — the whole
        point of checking negations first is that this must NOT be reported as a positive."""
        detected, _ = keywords.detect("No visa sponsorship available for this position.")
        assert detected is False

    def test_various_negation_phrasings(self) -> None:
        for text in (
            "We are unable to sponsor visas for this role.",
            "This role does not sponsor work visas.",
            "Sponsorship is not available.",
        ):
            assert keywords.detect(text)[0] is False, text

    def test_empty_text_is_not_detected(self) -> None:
        assert keywords.detect("") == (False, "")
        assert keywords.detect(None) == (False, "")  # type: ignore[arg-type]

    def test_case_insensitive(self) -> None:
        detected, _ = keywords.detect("VISA SPONSORSHIP AVAILABLE for the right candidate")
        assert detected is True


class TestNegationDetection:
    """``detect_negation`` — the explicit-refusal signal, distinct from a plain absence."""

    def test_detects_an_explicit_refusal(self) -> None:
        detected, phrase = keywords.detect_negation(
            "No visa sponsorship available for this position."
        )
        assert detected is True
        assert "sponsor" in phrase

    def test_various_negation_phrasings_all_detected(self) -> None:
        for text in (
            "We are unable to sponsor visas for this role.",
            "This role does not sponsor work visas.",
            "Sponsorship is not available.",
        ):
            assert keywords.detect_negation(text)[0] is True, text

    def test_plain_description_with_no_mention_is_not_a_negation(self) -> None:
        """The whole point of the distinction: silence is not a refusal."""
        detected, phrase = keywords.detect_negation("We are looking for a senior data scientist.")
        assert detected is False
        assert phrase == ""

    def test_empty_text_is_not_detected(self) -> None:
        assert keywords.detect_negation("") == (False, "")
        assert keywords.detect_negation(None) == (False, "")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# register.SponsorRegister — pure logic, built from an in-memory row list (no network)
# ---------------------------------------------------------------------------


def _rows(*entries: tuple[str, str]) -> list[dict[str, str]]:
    return [{"Organisation Name": name, "Route": route} for name, route in entries]


class TestSponsorRegisterIndex:
    def test_exact_name_match(self) -> None:
        idx = register.SponsorRegister(_rows(("Monzo Bank Ltd", "Skilled Worker")))
        result = idx.lookup("Monzo Bank Ltd")
        assert result.matched is True
        assert result.skilled_worker_route is True

    def test_fuzzy_match_ignores_legal_suffix_and_short_name(self) -> None:
        """A job board routinely writes "Google" for the register's "Google (UK) Limited"."""
        idx = register.SponsorRegister(_rows(("Google (UK) Limited", "Skilled Worker")))
        result = idx.lookup("Google")
        assert result.matched is True
        assert result.matched_name == "Google (UK) Limited"

    def test_a_generic_descriptor_variant_beats_an_unrelated_org_sharing_one_word(
        self,
    ) -> None:
        """Pins a real bug, confirmed live against the actual GOV.UK register: querying
        "Amazon" matched "Amazon Charitable Trust" instead of the real, correctly-licensed
        "Amazon UK Services Ltd" — containment alone can't tell "the same company written
        more fully" from "an unrelated org that happens to share a first word", and the
        original tie-break had no preference between them at all."""
        idx = register.SponsorRegister(_rows(
            ("Amazon Charitable Trust", "Skilled Worker"),
            ("Amazon UK Services Ltd", "Skilled Worker"),
        ))
        result = idx.lookup("Amazon")
        assert result.matched_name == "Amazon UK Services Ltd"

    def test_fewest_extra_words_wins_when_neither_candidate_is_purely_generic(
        self,
    ) -> None:
        """Confirmed live: a real "Amazon Filters Ltd" entry (an unrelated manufacturer)
        exists in the same bucket. Neither it nor a hypothetical differently-named
        competitor is a pure generic-descriptor variant, so the fallback (fewest extra
        words) decides — a real, if partial, improvement over an unopinionated tie-break,
        not a claim that this always finds the intended employer."""
        idx = register.SponsorRegister(_rows(
            ("Amazon Filters Ltd", "Skilled Worker"),
            ("Amazon Global Logistics Solutions", "Skilled Worker"),
        ))
        result = idx.lookup("Amazon")
        assert result.matched_name == "Amazon Filters Ltd"

    def test_unmatched_company_returns_no_match(self) -> None:
        idx = register.SponsorRegister(_rows(("Google (UK) Limited", "Skilled Worker")))
        result = idx.lookup("Totally Unrelated Startup Ltd")
        assert result.matched is False

    def test_non_skilled_worker_route_is_flagged_as_such(self) -> None:
        """A sponsor licence for a different route (e.g. Intra-company Transfer only) is
        still a match, but not one that supports a Skilled Worker application."""
        idx = register.SponsorRegister(
            _rows(("Some Global Corp Ltd", "Intra Company Transfers (ICT)"))
        )
        result = idx.lookup("Some Global Corp")
        assert result.matched is True
        assert result.skilled_worker_route is False

    def test_blank_rows_are_skipped_without_error(self) -> None:
        idx = register.SponsorRegister([{"Organisation Name": "", "Route": ""}])
        assert idx.row_count == 1
        assert idx.lookup("Anything").matched is False

    def test_empty_company_name_never_matches(self) -> None:
        idx = register.SponsorRegister(_rows(("Google (UK) Limited", "Skilled Worker")))
        assert idx.lookup("").matched is False


class TestSponsorRegisterCacheLifecycle:
    """status()/refresh() file-cache behaviour, without a real network call."""

    def test_status_with_no_cached_file_is_honest_about_it(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setattr(register, "_CSV_PATH", tmp_path / "missing.csv")
        monkeypatch.setattr(register, "_META_PATH", tmp_path / "missing.meta.json")
        result = register.status()
        assert result == {"fetched_at": None, "row_count": 0, "stale": True}

    def test_status_reports_a_fresh_cached_file_as_not_stale(self, tmp_path, monkeypatch) -> None:
        meta_path = tmp_path / "sponsors.meta.json"
        meta_path.write_text(
            json.dumps({"fetched_at": datetime.now(UTC).isoformat(), "row_count": 140000})
        )
        monkeypatch.setattr(register, "_META_PATH", meta_path)
        result = register.status()
        assert result["stale"] is False
        assert result["row_count"] == 140000

    def test_status_reports_an_old_cached_file_as_stale(self, tmp_path, monkeypatch) -> None:
        meta_path = tmp_path / "sponsors.meta.json"
        old = datetime.now(UTC) - timedelta(days=register.STALE_AFTER_DAYS + 1)
        meta_path.write_text(json.dumps({"fetched_at": old.isoformat(), "row_count": 140000}))
        monkeypatch.setattr(register, "_META_PATH", meta_path)
        result = register.status()
        assert result["stale"] is True

    async def test_refresh_skips_download_when_cache_is_fresh(self, tmp_path, monkeypatch) -> None:
        csv_path = tmp_path / "sponsors.csv"
        meta_path = tmp_path / "sponsors.meta.json"
        csv_path.write_text("Organisation Name,Route\nFoo Ltd,Skilled Worker\n")
        meta_path.write_text(
            json.dumps({"fetched_at": datetime.now(UTC).isoformat(), "row_count": 1})
        )
        monkeypatch.setattr(register, "_CSV_PATH", csv_path)
        monkeypatch.setattr(register, "_META_PATH", meta_path)

        async def _fail_if_called(*args, **kwargs):
            raise AssertionError("should not have made a network call")

        monkeypatch.setattr(register, "_discover_csv_url", _fail_if_called)
        result = await register.refresh()
        assert result == 1

    async def test_refresh_rejects_a_suspiciously_small_download(
        self, tmp_path, monkeypatch
    ) -> None:
        """A ~140k-row dataset served as a handful of rows means the URL served an error
        page or something else entirely — refuse it rather than caching garbage."""
        import httpx

        monkeypatch.setattr(register, "_CSV_PATH", tmp_path / "sponsors.csv")
        monkeypatch.setattr(register, "_META_PATH", tmp_path / "sponsors.meta.json")

        async def _fake_discover(client):
            return "https://example.com/fake.csv"

        class _FakeResponse:
            content = b"Organisation Name,Route\nOnly One Row Ltd,Skilled Worker\n"

            def raise_for_status(self) -> None:
                return None

        class _FakeClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                return False

            async def get(self, url, **kwargs):
                return _FakeResponse()

        monkeypatch.setattr(register, "_discover_csv_url", _fake_discover)
        monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: _FakeClient())

        with pytest.raises(RuntimeError, match="refusing to replace"):
            await register.refresh(force=True)
        assert not (tmp_path / "sponsors.csv").exists()


# ---------------------------------------------------------------------------
# classify — the single entry point used at ingestion
# ---------------------------------------------------------------------------


class TestClassify:
    def test_register_match_wins_over_keyword_detection(self, monkeypatch) -> None:
        """A confirmed register match is stronger evidence than posting text — should be
        reported even when the description also happens to contain sponsorship language."""
        monkeypatch.setattr(
            "app.core.sponsorship.classify.register.is_registered_sponsor",
            lambda company: register.SponsorMatch(
                matched=True, matched_name="Acme Ltd", skilled_worker_route=True
            ),
        )
        confidence, evidence = classify("Acme", "We also offer visa sponsorship available.")
        assert confidence is SponsorConfidence.CONFIRMED_REGISTER
        assert "Acme Ltd" in (evidence or "")

    def test_falls_back_to_keyword_when_no_register_match(self, monkeypatch) -> None:
        monkeypatch.setattr(
            "app.core.sponsorship.classify.register.is_registered_sponsor",
            lambda company: register.SponsorMatch(matched=False),
        )
        confidence, evidence = classify("Unknown Startup", "Visa sponsorship available.")
        assert confidence is SponsorConfidence.KEYWORD_DETECTED
        assert evidence

    def test_unknown_when_neither_signal_fires(self, monkeypatch) -> None:
        monkeypatch.setattr(
            "app.core.sponsorship.classify.register.is_registered_sponsor",
            lambda company: register.SponsorMatch(matched=False),
        )
        confidence, _evidence = classify("Unknown Startup", "A normal job description.")
        assert confidence is SponsorConfidence.UNKNOWN

    def test_not_sponsor_when_posting_explicitly_refuses(self, monkeypatch) -> None:
        monkeypatch.setattr(
            "app.core.sponsorship.classify.register.is_registered_sponsor",
            lambda company: register.SponsorMatch(matched=False),
        )
        confidence, evidence = classify(
            "Unknown Startup", "We do not sponsor visas for this position."
        )
        assert confidence is SponsorConfidence.NOT_SPONSOR
        assert evidence

    def test_register_match_wins_even_over_an_explicit_refusal(self, monkeypatch) -> None:
        """A licensed sponsor's own boilerplate ("no sponsorship") is a common false
        negative — the independently-verified register match is the stronger evidence."""
        monkeypatch.setattr(
            "app.core.sponsorship.classify.register.is_registered_sponsor",
            lambda company: register.SponsorMatch(matched=True, matched_name="Acme Ltd"),
        )
        confidence, evidence = classify("Acme", "We do not sponsor visas for this position.")
        assert confidence is SponsorConfidence.CONFIRMED_REGISTER
        assert "Acme Ltd" in (evidence or "")
