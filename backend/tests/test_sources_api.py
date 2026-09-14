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
    """A catalogued source with no adapter must say so rather than look merely unconfigured.

    This used to assert on ``reed``, which stopped being true the moment its adapter shipped —
    the point of the test is the derivation, so it now uses an employer with no public board.
    """
    spec = BY_KEY["careers:starling"]
    assert spec.implemented is False
    assert health_for(spec) is SourceHealth.NOT_IMPLEMENTED


def test_known_broken_platforms_report_degraded_not_live() -> None:
    """A registered platform that cannot return results must not report ``live``.

    Reporting them ``live`` is the specific failure this guards: it is what let a dead
    subsystem masquerade as a neutral "no matching roles" result.

    LinkedIn used to be in this list and no longer is — it reads the public job listing now,
    which needs no account. Indeed and Glassdoor still target the removed browser-use API.
    """
    for key in ("indeed", "glassdoor"):
        assert health_for(BY_KEY[key]) is SourceHealth.DEGRADED


def test_linkedin_is_live_through_its_public_listing() -> None:
    """The counterpart to the test above: LinkedIn is served by a real adapter.

    Worth pinning explicitly rather than leaving as an absence, because the thing that makes
    it live is a deliberate design choice — discovery reads the signed-out listing, so no
    account is involved and nothing about it depends on the operator connecting a session.
    """
    assert health_for(BY_KEY["linkedin"]) is SourceHealth.LIVE
    assert BY_KEY["linkedin"].known_broken is None


def test_connecting_a_session_is_still_offered_for_linkedin() -> None:
    """Discovery needs no login; applying does. The ladder has to say both at once."""
    spec = BY_KEY["linkedin"]
    assert spec.mechanism(AccessMechanism.PUBLIC_WEBSITE) is MechanismState.AVAILABLE
    assert spec.mechanism(AccessMechanism.AUTHENTICATED_BROWSER) is MechanismState.AUTH_REQUIRED


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
        "indeed",          # registered but degraded (removed browser-use API)
        "careers:starling",  # catalogued, no public ATS board
        "civilservice",    # blocked upstream (bot-verification gate)
        "not-a-source",    # unknown key
    ]
    assert usable_keys(requested) == ["remotive", "careers:monzo"]


def test_keyed_uk_aggregators_are_live_once_configured() -> None:
    """Adzuna and Reed need a key but cannot bill, so a configured key makes them LIVE.

    They were catalogued as unimplemented until their adapters shipped; the registry now
    derives this, so the flag cannot drift out of date again.
    """
    for key in ("adzuna", "reed"):
        assert health_for(BY_KEY[key]) in (
            SourceHealth.LIVE,
            SourceHealth.AUTH_REQUIRED,  # no key configured in CI
        )


def test_employer_boards_with_a_real_adapter_are_live() -> None:
    """The catalogue derives `implemented` from the registry, so adding an adapter is enough.

    Previously a hand-maintained flag meant every employer board stayed NOT_IMPLEMENTED even
    after its adapter shipped.
    """
    for key in ("careers:anthropic", "careers:palantir", "careers:monzo"):
        assert health_for(BY_KEY[key]) is SourceHealth.LIVE


def test_a_server_block_does_not_condemn_the_whole_portal() -> None:
    """Civil Service Jobs refuses server-side automation but a candidate can still sign in
    normally through a real (headed) browser session.

    Reporting the portal UNAVAILABLE off the back of one blocked mechanism conflated a
    single rung with the site, and hid real reachable jobs. The resolution ladder must fall
    to the browser rung instead.
    """
    spec = BY_KEY["civilservice"]
    assert spec.blocked_reason and "verification gate" in spec.blocked_reason
    assert spec.mechanism(AccessMechanism.PUBLIC_WEBSITE) is MechanismState.BLOCKED
    assert spec.mechanism(AccessMechanism.INTERACTIVE_BROWSER) is MechanismState.AVAILABLE
    assert health_for(spec) is SourceHealth.INTERACTIVE_AVAILABLE


def test_best_mechanism_prefers_the_highest_rung_available() -> None:
    """Escalation must be driven by genuine unavailability, not by a rejected request."""
    spec = BY_KEY["civilservice"]
    # API and public endpoints are out, so the browser rung wins — not HUMAN.
    assert spec.best_mechanism() is AccessMechanism.INTERACTIVE_BROWSER


def test_an_unprobed_mechanism_is_unknown_not_unavailable() -> None:
    """"Never checked" and "checked and refused" are different facts."""
    assert BY_KEY["civilservice"].mechanism(AccessMechanism.STATUS_SYNC) is MechanismState.UNKNOWN
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
    # LinkedIn reads the public listing and is live; Indeed still has no working adapter.
    assert "linkedin" in body["live_keys"]
    assert "indeed" not in body["live_keys"]
