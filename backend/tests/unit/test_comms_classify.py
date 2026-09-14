"""Unit tests for core.comms.classify — best-effort rejection/interview-invite detection."""

from app.core.comms.classify import classify


class TestClassify:
    def test_rejection_phrase_detected(self) -> None:
        result = classify(
            "Update on your application",
            "Unfortunately, we have decided not to move forward with your application.",
        )
        assert result == "rejection"

    def test_interview_invite_phrase_detected(self) -> None:
        result = classify(
            "Next steps",
            "We would like to invite you to interview for the Data Scientist role.",
        )
        assert result == "interview_invite"

    def test_rejection_wins_when_both_phrases_present(self) -> None:
        """A rejection that mentions "interview" (e.g. "after your interview, we've decided
        not to move forward") must not be reported as an invite."""
        result = classify(
            "Application update",
            "Thank you for interviewing with us. Unfortunately, we have decided not to move "
            "forward with your application at this time.",
        )
        assert result == "rejection"

    def test_generic_reply_when_neither_phrase_present(self) -> None:
        result = classify("Re: your application", "Thanks for reaching out, will review soon.")
        assert result == "reply"

    def test_never_raises_on_empty_text(self) -> None:
        assert classify("", "") == "reply"
