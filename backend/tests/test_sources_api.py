"""Job-source catalogue endpoint and registry health derivation."""

from __future__ import annotations

import pytest

from app.core.job_discovery.source_registry import (
    ALL_SOURCES,
    BY_KEY,
    AccessMechanism,
    MechanismState,
    SourceHealth,
    SourceTier,
    health_for,
    usable_keys,
)


def test_every_key_is_unique() -> None:
    keys = [s.key for s in ALL_SOURCES]
    assert len(keys) == len(set(keys))


def test_unimplemented_sources_report_not_implemented() -> None:
    spec = BY_KEY["reed"]
    assert spec.implemented is False
    assert health_for(spec) is SourceHealth.NOT_IMPLEMENTED


def test_known_broken_platforms_report_degraded_not_live() -> None:
    """The browser-scraped platforms are registered but cannot return results (B14).

    Reporting them ``live`` is the specific failure this guards: it is what let a dead
    subsystem masquerade as a neutral "no matching roles" result.
    """
    for key in ("linkedin", "indeed", "glassdoor"):
        assert health_for(BY_KEY[key]) is SourceHealth.DEGRADED


def test_keyless_api_sources_are_live() -> None:
    for key in ("remotive", "jobicy", "arbeitnow", "remoteok"):
        assert health_for(BY_KEY[key]) is SourceHealth.LIVE


def test_usable_keys_drops_everything_that_cannot_answer() -> None:
    """Only keys with a working adapter survive.

    ``careers:monzo`` moved from unusable to usable when the Greenhouse adapter was added, so
    it now belongs on the kept side. ``careers:starling`` replaces it as the unimplemented
    employer: probing Greenhouse, Lever, Ashby and SmartRecruiters found no public board, so
    it is catalogued but cannot answer.
    """
    requested = [
        "remotive",        # keyless aggregator, live
        "careers:monzo",   # Greenhouse board, live
        "linkedin",        # registered but degraded
        "reed",            # catalogued, no adapter
        "careers:starling",  # catalogued, no public ATS board
        "tracjobs",        # blocked upstream (403 to automation)
        "not-a-source",    # unknown key
    ]
    assert usable_keys(requested) == ["remotive", "careers:monzo"]


def test_employer_boards_with_a_real_adapter_are_live() -> None:
    """The catalogue derives `implemented` from the registry, so adding an adapter is enough.

    Previously a hand-maintained flag meant every employer board stayed NOT_IMPLEMENTED even
    after its adapter shipped.
    """
    for key in ("careers:anthropic", "careers:palantir", "careers:monzo"):
        assert health_for(BY_KEY[key]) is SourceHealth.LIVE


def test_a_server_block_does_not_condemn_the_whole_portal() -> None:
    """TRAC refuses server-side automation but a candidate can still sign in normally.

    Reporting the portal UNAVAILABLE off the back of one 403 conflated a single mechanism
    with the site, and hid real reachable jobs. The resolution ladder must fall to the
    browser rung instead.
    """
    spec = BY_KEY["tracjobs"]
    assert spec.blocked_reason and "403" in spec.blocked_reason
    assert spec.mechanism(AccessMechanism.PUBLIC_ENDPOINT) is MechanismState.BLOCKED
    assert spec.mechanism(AccessMechanism.INTERACTIVE_BROWSER) is MechanismState.AVAILABLE
    assert health_for(spec) is SourceHealth.INTERACTIVE_AVAILABLE


def test_best_mechanism_prefers_the_highest_rung_available() -> None:
    """Escalation must be driven by genuine unavailability, not by a rejected request."""
    spec = BY_KEY["tracjobs"]
    # API and public endpoints are out, so the browser rung wins — not HUMAN.
    assert spec.best_mechanism() is AccessMechanism.INTERACTIVE_BROWSER


def test_an_unprobed_mechanism_is_unknown_not_unavailable() -> None:
    """"Never checked" and "checked and refused" are different facts."""
    assert BY_KEY["tracjobs"].mechanism(AccessMechanism.STATUS_SYNC) is MechanismState.UNKNOWN
    assert BY_KEY["remotive"].mechanism(AccessMechanism.INTERACTIVE_BROWSER) is (
        MechanismState.UNKNOWN
    )


def test_career_pages_are_all_in_the_careers_tier() -> None:
    careers = [s for s in ALL_SOURCES if s.key.startswith("careers:")]
    assert careers
    assert all(s.tier is SourceTier.CAREERS for s in careers)


@pytest.mark.asyncio
async def test_catalogue_endpoint_groups_by_tier(client) -> None:  # type: ignore[no-untyped-def]
    """`GET /api/v1/sources/` returns every tier, with live_keys a subset of the catalogue."""
    response = await client.get("/api/v1/sources/")
    assert response.status_code == 200
    body = response.json()

    assert body["total"] == len(ALL_SOURCES)
    assert {t["id"] for t in body["tiers"]} == {t.value for t in SourceTier}

    all_keys = {s["key"] for t in body["tiers"] for s in t["sources"]}
    assert set(body["live_keys"]) <= all_keys
    assert "remotive" in body["live_keys"]
    assert "linkedin" not in body["live_keys"]
