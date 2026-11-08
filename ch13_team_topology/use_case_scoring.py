# Chapter 13: Scaling Adoption — Use-Case Funnel and Team Topologies
# Section: 13.1 The impact/effort quadrant and the worked example
# Book: AI-Based Data Engineering (Packt)

"""
Use-case impact/effort scoring for AI adoption prioritization.

Implements the rubric from Section 13.1 exactly:
  - Impact: four dimensions scored 1-5, summed to a total out of 20
  - Effort: four dimensions scored 1-5, summed to a total out of 20
  - Quadrant: impact and effort are each "high" above 10/20

Running this file reproduces the worked-example table for OpsPulse's
next five use cases and asserts the totals match the chapter.
"""

from dataclasses import dataclass
from enum import Enum


class ImpactDimension(str, Enum):
    TIME_SAVED          = "time_saved"           # hours/week recovered across users
    QUALITY_IMPROVEMENT = "quality_improvement"  # reduction in error rate or variance
    RISK_REDUCTION      = "risk_reduction"       # compliance coverage, incident prevention
    STRATEGIC_VALUE     = "strategic_value"      # new capability (5) vs optimization (1-3)


class EffortDimension(str, Enum):
    DATA_READINESS      = "data_readiness"       # curated dbt models (1) .. raw logs (5)
    AI_COMPLEXITY       = "ai_complexity"        # single prompt (1) .. multi-agent + tools (5)
    COMPLIANCE_OVERHEAD = "compliance_overhead"  # minimal risk (1) .. Annex III high-risk (5)
    INTEGRATION_EFFORT  = "integration_effort"   # Snowflake-internal (1) .. many systems (5)


class Quadrant(str, Enum):
    QUICK_WIN    = "Quick win"     # high impact, low effort
    STRATEGIC    = "Strategic"     # high impact, high effort
    FILL_IN      = "Fill-in"       # low impact, low effort
    LOW_PRIORITY = "Low priority"  # low impact, high effort


# Each total is out of 20; strictly above the midpoint counts as "high".
HIGH_THRESHOLD = 10

# Sequencing order: quick wins first, then strategic, then fill-ins.
QUADRANT_ORDER = [Quadrant.QUICK_WIN, Quadrant.STRATEGIC, Quadrant.FILL_IN, Quadrant.LOW_PRIORITY]


@dataclass
class UseCase:
    name:      str
    primitive: str
    impact:    dict[ImpactDimension, int]
    effort:    dict[EffortDimension, int]
    rationale: str = ""

    def __post_init__(self) -> None:
        for dims, scores in ((ImpactDimension, self.impact), (EffortDimension, self.effort)):
            missing = set(dims) - set(scores)
            if missing:
                raise ValueError(f"{self.name}: missing dimensions {sorted(m.value for m in missing)}")
            for dim, value in scores.items():
                if not 1 <= value <= 5:
                    raise ValueError(f"{self.name}: {dim.value}={value} is outside 1-5")

    @property
    def impact_score(self) -> int:
        return sum(self.impact.values())

    @property
    def effort_score(self) -> int:
        return sum(self.effort.values())

    @property
    def quadrant(self) -> Quadrant:
        high_impact = self.impact_score > HIGH_THRESHOLD
        high_effort = self.effort_score > HIGH_THRESHOLD
        if high_impact:
            return Quadrant.STRATEGIC if high_effort else Quadrant.QUICK_WIN
        return Quadrant.LOW_PRIORITY if high_effort else Quadrant.FILL_IN


# ============================================================
# OpsPulse's next five use cases (Section 13.1 worked example)
# ============================================================

I, E = ImpactDimension, EffortDimension

OPSPULSE_USE_CASES = [
    UseCase(
        name="Finance period-close assistant",
        primitive="Coding + Research",
        impact={I.TIME_SAVED: 5, I.QUALITY_IMPROVEMENT: 5, I.RISK_REDUCTION: 3, I.STRATEGIC_VALUE: 5},
        effort={E.DATA_READINESS: 1, E.AI_COMPLEXITY: 3, E.COMPLIANCE_OVERHEAD: 2, E.INTEGRATION_EFFORT: 3},
        rationale="Clean finance tables; reuses Ch9 SQL generation and Ch5 document search.",
    ),
    UseCase(
        name="Procurement document extraction",
        primitive="Content creation + Research",
        impact={I.TIME_SAVED: 4, I.QUALITY_IMPROVEMENT: 3, I.RISK_REDUCTION: 2, I.STRATEGIC_VALUE: 3},
        effort={E.DATA_READINESS: 2, E.AI_COMPLEXITY: 2, E.COMPLIANCE_OVERHEAD: 1, E.INTEGRATION_EFFORT: 1},
        rationale="Ch8 AI_PARSE_DOCUMENT pipeline pointed at supplier contracts.",
    ),
    UseCase(
        name="HR workforce analytics copilot",
        primitive="Data analysis + Research",
        impact={I.TIME_SAVED: 4, I.QUALITY_IMPROVEMENT: 4, I.RISK_REDUCTION: 5, I.STRATEGIC_VALUE: 4},
        effort={E.DATA_READINESS: 5, E.AI_COMPLEXITY: 4, E.COMPLIANCE_OVERHEAD: 5, E.INTEGRATION_EFFORT: 4},
        rationale="Annex III employment use: GDPR DPIA now, AI Act high-risk duties from 2 Dec 2027.",
    ),
    UseCase(
        name="Supply chain anomaly detection",
        primitive="Data analysis + Automation",
        impact={I.TIME_SAVED: 4, I.QUALITY_IMPROVEMENT: 4, I.RISK_REDUCTION: 3, I.STRATEGIC_VALUE: 4},
        effort={E.DATA_READINESS: 5, E.AI_COMPLEXITY: 4, E.COMPLIANCE_OVERHEAD: 1, E.INTEGRATION_EFFORT: 4},
        rationale="Depends on raw IoT telemetry with the ~4% null-timestamp quirk.",
    ),
    UseCase(
        name="Regulatory compliance Q&A",
        primitive="Research + Content creation",
        impact={I.TIME_SAVED: 2, I.QUALITY_IMPROVEMENT: 2, I.RISK_REDUCTION: 4, I.STRATEGIC_VALUE: 2},
        effort={E.DATA_READINESS: 2, E.AI_COMPLEXITY: 2, E.COMPLIANCE_OVERHEAD: 2, E.INTEGRATION_EFFORT: 2},
        rationale="Low volume; best shipped as a RAG starter template in the kit library.",
    ),
]

# The chapter's worked-example table: (impact/20, effort/20, quadrant)
EXPECTED = {
    "Finance period-close assistant":  (18, 9,  Quadrant.QUICK_WIN),
    "Procurement document extraction": (12, 6,  Quadrant.QUICK_WIN),
    "HR workforce analytics copilot":  (17, 18, Quadrant.STRATEGIC),
    "Supply chain anomaly detection":  (15, 14, Quadrant.STRATEGIC),
    "Regulatory compliance Q&A":       (10, 8,  Quadrant.FILL_IN),
}


def sequence_use_cases(use_cases: list[UseCase]) -> list[UseCase]:
    """Order the pilot roadmap: by quadrant priority, then by impact (highest first)."""
    return sorted(use_cases, key=lambda u: (QUADRANT_ORDER.index(u.quadrant), -u.impact_score))


def check_against_chapter(use_cases: list[UseCase]) -> None:
    """Fail loudly if the scores drift from the table printed in Section 13.1."""
    for uc in use_cases:
        actual = (uc.impact_score, uc.effort_score, uc.quadrant)
        assert actual == EXPECTED[uc.name], f"{uc.name}: got {actual}, chapter says {EXPECTED[uc.name]}"


if __name__ == "__main__":
    check_against_chapter(OPSPULSE_USE_CASES)
    print("OpsPulse use-case roadmap (Section 13.1):\n")
    print(f"{'Seq':<4} {'Use case':<34} {'Impact':>7} {'Effort':>7}  Quadrant")
    print("-" * 70)
    for i, uc in enumerate(sequence_use_cases(OPSPULSE_USE_CASES), 1):
        print(f"{i:<4} {uc.name:<34} {uc.impact_score:>4}/20 {uc.effort_score:>4}/20  {uc.quadrant.value}")
        print(f"     {uc.rationale}")
    print("\nAll totals match the chapter's worked-example table.")
