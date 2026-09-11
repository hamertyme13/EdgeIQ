"""Typed result dataclasses for the EdgeIQ analytics pipeline.

These classes replace the free-form ``dict`` returns that were previously
returned by core pipeline functions.  They are defined as ``dataclasses``
rather than Pydantic models so that they remain a zero-dependency layer
importable from any analytics module.

Usage
-----
New analytics code should accept and return these types wherever possible.
Existing callers that still expect ``dict`` can use ``dataclasses.asdict()``
to convert, or access attributes directly.

All fields are typed; optional external-provider data uses ``float | None``
or ``str | None`` so that mypy can enforce the distinction between "not
available" and "zero".
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class DataQuality:
    """Score and labels describing how much data supports a prop analysis."""

    score: float
    """0–100 composite data-quality score."""
    label: str
    """Human-readable quality tier, e.g. ``"Strong"`` or ``"Limited"``."""
    sample_size: int
    """Number of verified historical games used for the score."""
    reasons: list[str] = field(default_factory=list)
    """Factors that raised or lowered the score."""


@dataclass
class AnalyzedProp:
    """A single provider prop enriched with EdgeIQ analytics.

    This is the primary unit of output from the confirmation and feed-analysis
    pipeline.  It captures everything needed for recommendation ranking,
    entry building, and serialisation to the API response layer.
    """

    # --- Identity ---
    player: str
    stat: str
    line: float
    direction: str
    platform: str
    sport: str

    # --- Projection & edge ---
    projection: float
    edge: float
    confidence: float
    """Win probability as a percentage (0–100)."""

    # --- Model outputs ---
    grade: str
    """Letter grade A–F produced by the EV recommendation function."""
    ev_percent: float
    """Expected value as a percentage, e.g. ``5.2`` means +5.2% EV."""

    # --- Data quality ---
    data_quality: DataQuality

    # --- Optional context ---
    game: str = ""
    team: str = ""
    game_time: str = ""
    position: str = ""
    projection_source: str = ""
    auto_projected: bool = False

    # --- Provider context ---
    trending_count: int = 0
    end_to_end_confirmed: bool = False
    eligibility_reason: str = ""

    # --- Provider-specific optional fields ---
    forecast_snapshot: dict | None = None
    forecast_paid_eligible: bool = False
    espn: dict | None = None
    line_movement: dict | None = None
    source_signals: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Return a plain dict compatible with the legacy JSON pipeline."""
        import dataclasses
        raw = dataclasses.asdict(self)
        # Flatten DataQuality into the top-level dict as legacy code expects.
        raw["data_quality"] = dataclasses.asdict(self.data_quality)
        return raw


@dataclass
class ConfirmedProp(AnalyzedProp):
    """An ``AnalyzedProp`` that has passed all end-to-end eligibility checks.

    A prop is *confirmed* when:
    - ``end_to_end_confirmed`` is ``True``
    - It cleared plausibility validation
    - It is backed by at least one provider offer on the current board
    """

    provider_backed: bool = True
    """Always ``True`` for a confirmed prop; included for explicitness."""


@dataclass
class EntryLeg:
    """One prop leg within a placed or analysed entry."""

    player: str
    stat: str
    line: float
    direction: str
    platform: str
    sport: str
    game: str = ""
    team: str = ""
    game_time: str = ""
    position: str = ""
    projection: float | None = None
    edge: float | None = None
    confidence: float | None = None
    actual: float | None = None
    final_result: str = ""
    final_source: str = ""


@dataclass
class EntryAnalysis:
    """Complete analysis result for a multi-leg entry.

    Returned by the entry analysis pipeline and used to drive the placement
    check, payout analysis, and risk-guardrail calculations.
    """

    legs: list[EntryLeg]
    platform: str

    # --- Aggregate metrics ---
    average_confidence: float
    average_edge: float
    grade: str
    recommendation: str

    # --- Risk & payout ---
    correlation_warnings: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    payout_analysis: dict | None = None

    # --- Model metadata ---
    model_version: str = ""
    recommended_by_app: bool = False

    @property
    def leg_count(self) -> int:
        return len(self.legs)

    def to_dict(self) -> dict:
        """Return a plain dict compatible with the legacy JSON pipeline."""
        import dataclasses
        return dataclasses.asdict(self)
