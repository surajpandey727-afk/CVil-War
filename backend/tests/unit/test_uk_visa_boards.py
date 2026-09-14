"""MoveJobs and Tarve adapters — both pinned against real HTML structure captured from the
live sites (2026-08-29), not guessed at. See core.job_discovery.sources.uk_visa_boards for
why ukvisajobs.com/civilservicejobs/workinstartups.com do NOT get adapters here.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from app.core.job_discovery.sources.uk_visa_boards import MoveJobsSource, TarveSource

# ---------------------------------------------------------------------------
# MoveJobs — real per-job URL is inside an HTML COMMENT around the card anchor,
# confirmed on both the unfiltered and keyword-filtered listing pages.
# ---------------------------------------------------------------------------

_MOVEJOBS_CARD = """
<div class="card bbs bg-jb1 iconxl-size jobcardStyle1">
  <div class="card-body">
    <div class="rt-single-icon-box tw-flex-wrap">
      <!--<a href="https://movejobs.uk/jobs/data-scientist-JA5ZJY" class="icon-thumb">-->
      <div class="icon-thumb"><img alt="" src="logo.png"/></div>
      <!--</a>-->
      <div class="iconbox-content">
        <div class="post-info2">
          <div class="post-main-title text-head">
            Data Scientist
            <span class="badge rounded-pill btn-mjb">Full Time</span>
          </div>
          <div class="body-font-4 text-gray-600 pt-2 jobwaylist">
            <ul class="rt-list">
              <li class="rt-mb-10">London, Greater London, United Kingdom</li>
              <li class="rt-mb-10">10K -
                                        100K GBP</li>
              <li class="rt-mb-10"><div class="jddv">We are hiring a data scientist to join our
                team. Visa sponsorship available for the right candidate.</div></li>
            </ul>
          </div>
        </div>
      </div>
    </div>
  </div>
</div>
"""

#: Confirmed live: movejobs.uk's server-rendered HTML shows this "Expired" badge on
#: literally every card, including genuinely current postings — a JS countdown widget that
#: defaults to it before client-side correction, not a real status. This fixture pins that
#: the badge must NOT be used as a filter (see the "no filter" comment in _fetch).
_MOVEJOBS_CARD_WITH_MISLEADING_EXPIRED_BADGE = """
<div class="card">
  <div class="card-body">
    <div class="rt-single-icon-box">
      <!--<a href="https://movejobs.uk/jobs/still-live-role-XYZ123" class="icon-thumb">-->
      <div class="iconbox-content">
        <div class="post-info2">
          <div class="post-main-title text-head">Still Live Role<span class="badge">Full Time</span></div>
          <div class="jobwaylist">
            <ul class="rt-list">
              <li class="rt-mb-10">Manchester, UK</li>
              <li class="rt-mb-10">10K - 100K GBP</li>
              <li class="rt-mb-10"><span class="text-danger">Expired</span></li>
            </ul>
          </div>
        </div>
      </div>
    </div>
  </div>
</div>
"""

_MOVEJOBS_NO_LINK_CARD = """
<div class="card">
  <div class="card-body">
    <div class="rt-single-icon-box">
      <div class="iconbox-content">
        <div class="post-info2">
          <div class="post-main-title text-head">No Link Role</div>
          <div class="jobwaylist"><ul class="rt-list"><li>London</li></ul></div>
        </div>
      </div>
    </div>
  </div>
</div>
"""


def _html_client(html: str) -> MagicMock:
    response = MagicMock()
    response.text = html
    response.raise_for_status = MagicMock()
    client = MagicMock()
    client.get = AsyncMock(return_value=response)
    return client


class TestMoveJobsSource:
    async def test_extracts_url_from_the_commented_anchor(self) -> None:
        source = MoveJobsSource()
        client = _html_client(f"<html><body>{_MOVEJOBS_CARD}</body></html>")
        records = await source._fetch(client, "data scientist", "", 50)
        assert len(records) == 1
        assert records[0]["url"] == "https://movejobs.uk/jobs/data-scientist-JA5ZJY"
        assert records[0]["title"] == "Data Scientist"
        assert records[0]["job_type"] == "Full Time"

    async def test_keyword_is_sent_as_a_query_param(self) -> None:
        source = MoveJobsSource()
        client = _html_client("<html><body></body></html>")
        await source._fetch(client, "data scientist", "", 50)
        client.get.assert_awaited_once()
        _, kwargs = client.get.await_args
        assert kwargs["params"] == {"keyword": "data scientist"}

    async def test_misleading_expired_badge_is_not_used_as_a_filter(self) -> None:
        """Confirmed live: the badge is shown on every card regardless of true status —
        using it as a filter previously discarded 100% of real, live results."""
        source = MoveJobsSource()
        client = _html_client(
            f"<html><body>{_MOVEJOBS_CARD_WITH_MISLEADING_EXPIRED_BADGE}</body></html>"
        )
        records = await source._fetch(client, "", "", 50)
        listing = source._to_listing(records[0])
        assert listing is not None
        assert listing.title == "Still Live Role"

    async def test_card_with_no_recoverable_url_is_dropped(self) -> None:
        source = MoveJobsSource()
        client = _html_client(f"<html><body>{_MOVEJOBS_NO_LINK_CARD}</body></html>")
        records = await source._fetch(client, "", "", 50)
        assert records[0]["url"] == ""
        assert source._to_listing(records[0]) is None

    async def test_valid_card_becomes_a_listing_with_no_salary_populated(self) -> None:
        """The salary line is a search-bucket label ("10K - 100K GBP"), not a real per-job
        figure — parsing it into salary_min/max would corrupt the salary-floor filter far
        worse than leaving it unpublished."""
        source = MoveJobsSource()
        client = _html_client(f"<html><body>{_MOVEJOBS_CARD}</body></html>")
        records = await source._fetch(client, "", "", 50)
        listing = source._to_listing(records[0])
        assert listing is not None
        assert listing.salary_min is None
        assert listing.salary_max is None
        assert listing.platform_job_id == "data-scientist-JA5ZJY"
        assert "sponsorship available" in listing.description.casefold()

    async def test_company_uses_the_sites_own_placeholder_not_an_empty_string(self) -> None:
        """Confirmed live: every movejobs.uk posting shows the employer as this same generic
        label, on both the listing card and the job's own detail page — there is no real
        per-job company field to extract. An empty string here would silently vanish every
        result, since ApiJobSource.search() drops any listing with no company at all."""
        source = MoveJobsSource()
        client = _html_client(f"<html><body>{_MOVEJOBS_CARD}</body></html>")
        records = await source._fetch(client, "", "", 50)
        listing = source._to_listing(records[0])
        assert listing is not None
        assert listing.company == "Movejob Portal"

    async def test_full_search_pipeline_end_to_end(self) -> None:
        """Exercises the real ApiJobSource.search() wrapper, not just _fetch/_to_listing —
        this is what originally caught the company="" bug that _fetch/_to_listing tests
        alone missed (the base class silently drops any listing with no company)."""
        source = MoveJobsSource()
        html = f"<html><body>{_MOVEJOBS_CARD}{_MOVEJOBS_CARD_WITH_MISLEADING_EXPIRED_BADGE}</body></html>"

        async def _fake_client_get(url, params=None, headers=None):
            response = MagicMock()
            response.text = html
            response.raise_for_status = MagicMock()
            return response

        import httpx

        real_client_cls = httpx.AsyncClient

        class _FakeAsyncClient(real_client_cls):
            async def get(self, url, **kwargs):
                return await _fake_client_get(url, **kwargs)

        import app.core.job_discovery.sources.base as base_mod

        original = base_mod.httpx.AsyncClient
        base_mod.httpx.AsyncClient = _FakeAsyncClient
        try:
            listings = await source.search("data scientist")
        finally:
            base_mod.httpx.AsyncClient = original

        # Both cards survive — neither the (misleading) Expired badge nor the missing
        # per-job company field silently discards a real result.
        assert len(listings) == 2
        assert {listing.title for listing in listings} == {"Data Scientist", "Still Live Role"}
        assert all(listing.company == "Movejob Portal" for listing in listings)


# ---------------------------------------------------------------------------
# Tarve — simple, clean anchors; no keyword search endpoint (filtered client-side).
# ---------------------------------------------------------------------------

_TARVE_PAGE_1 = """
<html><body><main>
  <section>
    <ul class="jobs">
      <li><a href="/jobs/data-scientist-anthropic-abc123"><strong>Data Scientist</strong></a>
          <span class="muted">Anthropic · London, UK · 28 August 2026</span></li>
      <li><a href="/jobs/kitchen-assistant-greene-king-def456"><strong>Kitchen Assistant</strong></a>
          <span class="muted">Greene King · Ower, Hampshire · 28 August 2026</span></li>
    </ul>
  </section>
</main></body></html>
"""

_TARVE_EMPTY_PAGE = "<html><body><main><section><ul class=\"jobs\"></ul></section></main></body></html>"


class TestTarveSource:
    async def test_extracts_title_company_location_and_url(self) -> None:
        source = TarveSource()

        call_count = 0

        async def _get(url, params=None, headers=None):
            nonlocal call_count
            call_count += 1
            response = MagicMock()
            response.text = _TARVE_PAGE_1 if call_count == 1 else _TARVE_EMPTY_PAGE
            response.raise_for_status = MagicMock()
            return response

        client = MagicMock()
        client.get = AsyncMock(side_effect=_get)

        records = await source._fetch(client, "", "", 50)
        assert len(records) == 2
        assert records[0]["title"] == "Data Scientist"
        assert records[0]["company"] == "Anthropic"
        assert records[0]["location"] == "London, UK"
        assert records[0]["url"] == "https://tarve.co.uk/jobs/data-scientist-anthropic-abc123"

    async def test_stops_paginating_once_a_page_has_no_links(self) -> None:
        source = TarveSource()
        response = MagicMock()
        response.text = _TARVE_EMPTY_PAGE
        response.raise_for_status = MagicMock()
        client = MagicMock()
        client.get = AsyncMock(return_value=response)

        records = await source._fetch(client, "", "", 50)
        assert records == []
        client.get.assert_awaited_once()  # stopped after page 1, never tried page 2/3

    async def test_to_listing_carries_the_sites_own_sponsor_claim(self) -> None:
        source = TarveSource()
        record = {
            "title": "Data Scientist", "company": "Anthropic", "location": "London, UK",
            "posted_at": "28 August 2026",
            "url": "https://tarve.co.uk/jobs/data-scientist-anthropic-abc123",
        }
        listing = source._to_listing(record)
        assert listing is not None
        assert listing.raw_data["site_claims_verified_sponsor"] is True
        assert listing.platform_job_id == "abc123"

    async def test_record_with_no_company_is_dropped(self) -> None:
        source = TarveSource()
        record = {"title": "X", "company": "", "location": "", "posted_at": "", "url": "/jobs/x"}
        assert source._to_listing(record) is None
