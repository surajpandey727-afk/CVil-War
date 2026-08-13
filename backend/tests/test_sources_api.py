"""Job-source catalogue endpoint and registry health derivation."""

from __future__ import annotations

import pytest

from app.core.job_discovery.source_registry import (
    ALL_SOURCES,
    BY_KEY,
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
    requested = ["remotive", "linkedin", "reed", "careers:monzo", "not-a-source"]
    assert usable_keys(requested) == ["remotive"]


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
