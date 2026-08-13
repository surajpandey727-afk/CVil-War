"""The zero-spend guarantee, enforced rather than documented.

The deployment runs under a hard £0 constraint, so these tests pin the two properties that
make that real: a billable adapter cannot be constructed while the guard is on, and the guard
is on unless someone explicitly turns it off.
"""

from __future__ import annotations

import pytest

from app.config.settings import Settings
from app.core.job_discovery.sources import CAREER_SOURCES, IMPLEMENTED_KEYS
from app.core.job_discovery.sources.base import (
    ApiJobSource,
    CostType,
    SourceUnavailableError,
)
from app.core.job_discovery.sources.boards import ALL_SOURCES


class _PaidSource(ApiJobSource):
    source_name = "paid-example"
    cost_type = CostType.OPTIONAL_PAID
    estimated_cost = 0.01

    async def _fetch(self, client, query, location, limit):  # pragma: no cover - never runs
        return []

    def _to_listing(self, record):  # pragma: no cover - never runs
        return None


class TestCostGuard:
    def test_zero_cost_mode_is_on_by_default(self) -> None:
        """The safe state must be what you get by doing nothing."""
        assert Settings().zero_cost_mode is True

    def test_billable_adapter_cannot_be_constructed_under_zero_cost_mode(self) -> None:
        """Blocked at construction, not at call time.

        A check on the search path alone would leave scheduled refreshes, retries and any
        hand-built request able to reach a paid provider.
        """
        with pytest.raises(SourceUnavailableError, match="ZERO_COST_MODE"):
            _PaidSource()

    def test_billable_adapter_is_allowed_once_the_guard_is_lifted(self, monkeypatch) -> None:
        from app.config import settings as settings_mod

        cfg = Settings()
        cfg.zero_cost_mode = False
        monkeypatch.setattr(settings_mod, "get_settings", lambda: cfg)
        assert _PaidSource().cost_type is CostType.OPTIONAL_PAID

    def test_every_shipped_adapter_is_free(self) -> None:
        """No adapter in the product may bill. New paid ones must be an explicit decision."""
        for cls in [*ALL_SOURCES, *CAREER_SOURCES.values()]:
            assert cls.cost_type is CostType.FREE, f"{cls.source_name} is not FREE"
            assert cls.estimated_cost == 0.0


class TestAdapterContract:
    def test_every_adapter_declares_its_capabilities(self) -> None:
        for cls in [*ALL_SOURCES, *CAREER_SOURCES.values()]:
            caps = cls().capabilities()
            assert caps["search"] is True
            # These are discovery sources: none of them submits an application, and claiming
            # otherwise would make the apply engine route work to a dead end.
            assert caps["can_apply"] is False
            assert caps["application_url"] is True

    def test_implemented_keys_covers_boards_and_employer_pages(self) -> None:
        assert {"remotive", "jobicy", "arbeitnow", "remoteok"} <= IMPLEMENTED_KEYS
        assert "careers:anthropic" in IMPLEMENTED_KEYS
        assert len(IMPLEMENTED_KEYS) >= 13
