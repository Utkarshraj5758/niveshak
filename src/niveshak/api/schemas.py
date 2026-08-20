"""Request/response contracts for the API."""

from __future__ import annotations

from pydantic import BaseModel, Field

from niveshak.parse.tip import Source


class ScoreRequest(BaseModel):
    text: str = Field(min_length=1, max_length=4000, description="The tip message to score.")
    source: Source = "manual"


# The response is the RiskScore model from score.assemble (re-exported for the OpenAPI docs).
from niveshak.score.assemble import RiskScore as ScoreResponse  # noqa: E402,F401
