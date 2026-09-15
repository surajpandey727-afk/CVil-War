"""Unit tests for the dashboard action queue's click-through routing.

The queue is only useful if a click lands on the exact thing that needs doing rather
than a page the operator must then navigate onward from — these pin the mapping from
each NextAction to where the frontend's ROUTE_FOR_TARGET actually sends the click.
"""

from __future__ import annotations

from app.api.v1.command_centre import _ACTION_TARGET
from app.models.enums import NextAction


class TestActionTargetRouting:
    def test_upload_cv_routes_to_the_specific_application(self) -> None:
        """Regression: this used to be "documents", which took the operator to the
        generic /resumes page with no indication of which application needed a CV, and
        no way to attach one back to it once there. "application" resolves to
        /applications/{id} on the frontend, where the CV picker actually lives."""
        assert _ACTION_TARGET[NextAction.UPLOAD_CV] == "application"
