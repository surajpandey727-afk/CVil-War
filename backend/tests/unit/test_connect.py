"""Interactive login capture.

The security properties are the point of these tests, not a side note. This component exists
so that the apply agent can act on the operator's behalf *without* ever holding their
password, and so that connecting one portal cannot quietly harvest every other login in the
browser profile. Both are easy to regress and invisible when they do.
"""

from __future__ import annotations

import ast
import inspect
from datetime import UTC, datetime

import pytest

from app.core.automation import connect
from app.core.automation.connect import (
    ConnectState,
    _earliest_expiry,
    connectable,
    domains_for,
    filter_storage_state,
    signed_in,
    target_for,
)


def cookie(name: str, domain: str, value: str = "v", expires: float | None = None) -> dict:
    c = {"name": name, "value": value, "domain": domain}
    if expires is not None:
        c["expires"] = expires
    return c


class TestNoCredentialEverEntersThisProcess:
    """The whole design rests on this: the operator types their password into the real site.

    If a future change adds a password parameter or reads one from configuration, the promise
    made in the UI ("no password is seen or kept") silently becomes false.
    """

    def test_no_function_accepts_a_password(self) -> None:
        suspicious = {"password", "passwd", "pwd", "secret", "credential", "credentials"}
        for name, obj in vars(connect).items():
            if not (inspect.isfunction(obj) or inspect.isclass(obj)):
                continue
            targets = [obj] if inspect.isfunction(obj) else [
                m for _, m in inspect.getmembers(obj, inspect.isfunction)
            ]
            for fn in targets:
                params = set(inspect.signature(fn).parameters) & suspicious
                assert not params, f"{name}.{fn.__name__} accepts {params}"

    def test_the_module_never_types_into_a_form_field(self) -> None:
        """Entering a credential means calling one of these on a page. The module drives a
        browser but must only ever *navigate* it — the typing is the operator's job.

        Checked over the parsed tree rather than the raw text so that documentation explaining
        the guarantee does not trip the test that enforces it.
        """
        entry_methods = {"fill", "type", "press", "press_sequentially", "set_input_files"}
        called = {
            node.func.attr
            for node in ast.walk(ast.parse(inspect.getsource(connect)))
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        }
        assert not (called & entry_methods), (
            f"{called & entry_methods} would let this module enter credentials itself"
        )

    def test_no_identifier_in_the_code_refers_to_a_credential(self) -> None:
        """Prose may discuss passwords; executable code must not name one."""
        tree = ast.parse(inspect.getsource(connect))
        names = {
            node.id for node in ast.walk(tree) if isinstance(node, ast.Name)
        } | {
            node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)
        } | {
            node.arg for node in ast.walk(tree) if isinstance(node, ast.arg)
        }
        offenders = {n for n in names if any(
            w in n.lower() for w in ("password", "passwd", "pwd", "username", "login_as")
        )}
        assert not offenders, f"credential-bearing identifiers: {offenders}"

    def test_capture_is_headed_so_the_operator_can_see_and_consent(self) -> None:
        """A headless capture is one the operator cannot watch, cannot consent to, and cannot
        complete when the platform asks for a verification code."""
        source = inspect.getsource(connect.ConnectManager._drive)
        assert "headless=False" in source
        assert "headless=True" not in source


class TestOnlyTheTargetPlatformIsCaptured:
    """A browser profile signed into LinkedIn is usually signed into a dozen other things."""

    def test_cookies_for_other_sites_are_discarded(self) -> None:
        state = {
            "cookies": [
                cookie("li_at", ".linkedin.com"),
                cookie("SID", ".google.com"),
                cookie("session", ".mybank.example"),
            ],
            "origins": [],
        }
        kept = filter_storage_state(state, domains_for("linkedin"))
        assert [c["name"] for c in kept["cookies"]] == ["li_at"]

    def test_a_lookalike_host_cannot_donate_cookies(self) -> None:
        """Suffix matching without a dot anchor would accept ``notlinkedin.com``."""
        state = {"cookies": [cookie("li_at", "notlinkedin.com")], "origins": []}
        assert filter_storage_state(state, domains_for("linkedin"))["cookies"] == []

    def test_a_genuine_subdomain_is_kept(self) -> None:
        state = {"cookies": [cookie("li_at", ".www.linkedin.com")], "origins": []}
        assert len(filter_storage_state(state, domains_for("linkedin"))["cookies"]) == 1

    def test_origin_storage_is_scoped_too(self) -> None:
        state = {
            "cookies": [],
            "origins": [
                {"origin": "https://www.linkedin.com", "localStorage": []},
                {"origin": "https://mail.google.com", "localStorage": []},
            ],
        }
        kept = filter_storage_state(state, domains_for("linkedin"))
        assert [o["origin"] for o in kept["origins"]] == ["https://www.linkedin.com"]

    def test_an_empty_state_survives_filtering(self) -> None:
        assert filter_storage_state({}, domains_for("linkedin")) == {"cookies": [], "origins": []}


class TestDetectingACompletedSignIn:
    def test_the_declared_auth_cookie_is_decisive(self) -> None:
        assert signed_in({"cookies": [cookie("li_at", ".linkedin.com")]}, "linkedin")

    def test_consent_and_analytics_cookies_are_not_a_session(self) -> None:
        """Every visitor gets these before signing in. Treating them as success would store a
        useless session and report "Connected"."""
        state = {"cookies": [
            cookie("lidc", ".linkedin.com"),
            cookie("bcookie", ".linkedin.com"),
            cookie("_ga", ".linkedin.com"),
        ]}
        assert not signed_in(state, "linkedin")

    def test_an_empty_auth_cookie_value_is_not_a_session(self) -> None:
        assert not signed_in({"cookies": [cookie("li_at", ".linkedin.com", value="")]}, "linkedin")

    def test_a_cookie_from_another_site_never_signals_sign_in(self) -> None:
        assert not signed_in({"cookies": [cookie("li_at", ".evil.example")]}, "linkedin")

    def test_a_portal_with_no_declared_hint_falls_back_to_a_first_party_cookie(self) -> None:
        """Reed declares no auth-cookie name; a durable non-consent cookie is the best
        available evidence, and refusing to connect at all would be worse."""
        assert signed_in({"cookies": [cookie("ASP.NET_SessionId", ".reed.co.uk")]}, "reed")

    def test_the_fallback_still_rejects_consent_cookies(self) -> None:
        assert not signed_in({"cookies": [cookie("OptanonConsent", ".reed.co.uk")]}, "reed")

    def test_no_cookies_at_all_is_not_a_session(self) -> None:
        assert not signed_in({"cookies": []}, "linkedin")


class TestWhichPortalsCanBeConnected:
    @pytest.mark.parametrize("platform", ["linkedin", "indeed", "glassdoor", "reed"])
    def test_portals_behind_a_login_are_connectable(self, platform: str) -> None:
        assert connectable(platform)

    def test_a_keyless_public_api_is_not_connectable(self) -> None:
        """Offering "Connect" for a source needing no login is a dead control."""
        assert not connectable("remotive")

    def test_an_unknown_platform_is_not_connectable(self) -> None:
        assert not connectable("definitely-not-a-portal")
        assert target_for("definitely-not-a-portal") is None

    def test_every_declared_target_points_at_a_real_login_page(self) -> None:
        for platform, target in connect.LOGIN_TARGETS.items():
            assert target.login_url.startswith("https://"), platform
            # The login host must belong to the portal, or the operator is being sent
            # somewhere the registry does not vouch for.
            host = target.login_url.removeprefix("https://").split("/")[0]
            assert any(
                host == d or host.endswith(f".{d}") for d in domains_for(platform)
            ), f"{platform}: {host} is not one of {sorted(domains_for(platform))}"


class TestSessionExpiry:
    def test_the_soonest_expiring_cookie_decides(self) -> None:
        state = {"cookies": [
            cookie("a", ".linkedin.com", expires=2000000000),
            cookie("li_at", ".linkedin.com", expires=1800000000),
        ]}
        assert _earliest_expiry(state) == datetime.fromtimestamp(1800000000, tz=UTC)

    def test_session_cookies_with_no_expiry_report_none(self) -> None:
        """Playwright writes -1 for a session cookie. Treating that as an epoch date would
        claim the session expired in 1969 and prompt a reconnect immediately."""
        assert _earliest_expiry({"cookies": [cookie("li_at", ".linkedin.com", expires=-1)]}) is None

    def test_no_cookies_reports_none(self) -> None:
        assert _earliest_expiry({"cookies": []}) is None


class TestAttemptLifecycle:
    def test_terminal_states_are_the_ones_that_stop_polling(self) -> None:
        assert ConnectState.CONNECTED.terminal
        assert ConnectState.FAILED.terminal
        assert ConnectState.CANCELLED.terminal
        assert ConnectState.TIMED_OUT.terminal
        assert not ConnectState.AWAITING_LOGIN.terminal
        assert not ConnectState.OPENING.terminal
        assert not ConnectState.CAPTURING.terminal

    def test_an_attempt_is_scoped_to_its_owner(self) -> None:
        """An attempt id must not be readable across accounts."""
        manager = connect.ConnectManager()
        attempt = connect.ConnectAttempt(id="x", user_id="alice", platform="linkedin")
        manager._attempts["x"] = attempt
        assert manager.get("x", "alice") is attempt
        assert manager.get("x", "bob") is None

    def test_cancelling_another_users_attempt_does_nothing(self) -> None:
        manager = connect.ConnectManager()
        attempt = connect.ConnectAttempt(id="x", user_id="alice", platform="linkedin")
        manager._attempts["x"] = attempt
        assert not manager.cancel("x", "bob")
        assert not attempt.cancelled.is_set()

    def test_a_finished_attempt_cannot_be_cancelled(self) -> None:
        manager = connect.ConnectManager()
        attempt = connect.ConnectAttempt(
            id="x", user_id="alice", platform="linkedin", state=ConnectState.CONNECTED
        )
        manager._attempts["x"] = attempt
        assert not manager.cancel("x", "alice")

    def test_a_second_connect_reuses_the_running_attempt(self) -> None:
        """Two clicks on Connect must not open two windows onto the same login."""
        manager = connect.ConnectManager()
        attempt = connect.ConnectAttempt(
            id="x", user_id="alice", platform="linkedin", state=ConnectState.AWAITING_LOGIN
        )
        manager._attempts["x"] = attempt
        assert manager.active_for("alice", "linkedin") is attempt
        assert manager.active_for("alice", "indeed") is None
        assert manager.active_for("bob", "linkedin") is None
