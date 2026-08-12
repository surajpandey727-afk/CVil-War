"""Rule-based failure diagnosis for apply runs.

Maps trajectory ``signals`` to a :class:`FailureClass` + root cause + a bounded suggested
remediation. Pure logic (no I/O), so it is fully unit-tested. The signal dict is built by
the observer from the agent history; recognized keys:
  errors: list[str], evaluations: list[str], consecutive_failures: int,
  loop_detected: bool, timed_out: bool, llm_error: bool, final_url: str
"""

from __future__ import annotations

from dataclasses import dataclass

from app.models.enums import FailureClass


@dataclass(frozen=True)
class Diagnosis:
    failure_class: FailureClass
    root_cause: str
    suggested_action: str


def diagnose(signals: dict) -> Diagnosis:
    """Classify a failed run from its trajectory signals."""
    haystack = " ".join([*signals.get("errors", []), *signals.get("evaluations", [])]).lower()
    url = (signals.get("final_url") or "").lower()

    def has(*words: str) -> bool:
        return any(w in haystack or w in url for w in words)

    if signals.get("timed_out"):
        return Diagnosis(
            FailureClass.TIMEOUT,
            "Run exceeded its time budget",
            "raise job_timeout / simplify flow",
        )
    if has("captcha", "are you a robot", "verify you are human", "recaptcha"):
        return Diagnosis(
            FailureClass.CAPTCHA_WALL, "CAPTCHA challenge encountered", "request human intervention"
        )
    if has("two-factor", "2fa", "verification code", "one-time code", "authenticator"):
        return Diagnosis(
            FailureClass.TWOFA_REQUIRED, "2FA prompt encountered", "request human intervention"
        )
    if has("unusual traffic", "access denied", "datadome", "are you human", "blocked"):
        return Diagnosis(
            FailureClass.ANTIBOT_BLOCK, "Anti-bot block detected", "rotate proxy/UA and back off"
        )
    if has("rate limit", "too many requests", "429"):
        return Diagnosis(
            FailureClass.RATE_LIMITED,
            "Platform rate-limited the session",
            "back off and retry later",
        )
    if has("session expired", "logged out", "please sign in", "please log in") or "login" in url:
        return Diagnosis(
            FailureClass.SESSION_EXPIRED,
            "Login/session wall hit",
            "re-authenticate (assisted login)",
        )
    if signals.get("loop_detected"):
        return Diagnosis(
            FailureClass.LOOP,
            "Agent looped without progress",
            "reload domain skill / revise prompt",
        )
    if has("element not found", "selector", "could not find", "no such element", "not visible"):
        return Diagnosis(
            FailureClass.DOM_DRIFT,
            "Expected element missing (page changed)",
            "update domain-skill selectors",
        )
    if has("required field", "missing field", "must fill", "this field is required"):
        return Diagnosis(
            FailureClass.FIELD_MISSING,
            "Required form field not handled",
            "extend the form-fill skill",
        )
    if signals.get("llm_error"):
        return Diagnosis(
            FailureClass.LLM_ERROR,
            "LLM provider error during reasoning",
            "check provider/key; use fallback",
        )
    if int(signals.get("consecutive_failures") or 0) >= 3:
        return Diagnosis(
            FailureClass.AGENT_OFFTRACK,
            "Repeated step failures",
            "simplify the task or add guidance",
        )
    return Diagnosis(FailureClass.UNKNOWN, "Unclassified failure", "review the trajectory manually")
