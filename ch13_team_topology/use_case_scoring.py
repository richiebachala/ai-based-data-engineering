# Chapter 13: Scaling Adoption — Use-Case Funnel and Team Topologies
# Section: 13.1 Use-case impact/effort scoring
# Book: AI-Based Data Engineering (Packt)
#
# NOTE: Code snippets marked with ... are illustrative stubs from the book text.
# Complete implementations are provided where the full code is shown.

"""
Use-case scoring model for AI adoption prioritization.

Chapter 13 covers the organizational questions:
  - Which use cases to pursue first (impact vs effort scoring)
  - Team topologies for AI-augmented data engineering
  - Honest communication about what AI automation changes

This file implements the impact/effort scoring framework.
"""

from dataclasses import dataclass, field
from typing import Optional
from enum import Enum


class ImpactDimension(str, Enum):
    TIME_SAVINGS        = "time_savings"        # hours/week saved across team
    QUALITY_IMPROVEMENT = "quality_improvement"  # reduces incidents or errors
    ADOPTION_SIGNAL     = "adoption_signal"      # increases usage of data products
    COST_REDUCTION      = "cost_reduction"       # reduces compute or labor costs


class EffortDimension(str, Enum):
    CONTEXT_READINESS   = "context_readiness"   # is the data AI-ready?
    INTEGRATION_EFFORT  = "integration_effort"   # how much plumbing is needed?
    EVAL_COMPLEXITY     = "eval_complexity"      # how hard to verify outputs?
    RISK_LEVEL          = "risk_level"           # what breaks if it's wrong?


@dataclass
class UseCaseScore:
    name:         str
    description:  str
    impact:       dict[str, float]   # dimension → score 0.0–1.0
    effort:       dict[str, float]   # dimension → score 0.0–1.0 (higher = more effort)
    notes:        str = ""
    chapter_ref:  str = ""

    @property
    def impact_score(self) -> float:
        return sum(self.impact.values()) / len(self.impact) if self.impact else 0.0

    @property
    def effort_score(self) -> float:
        return sum(self.effort.values()) / len(self.effort) if self.effort else 0.0

    @property
    def roi_score(self) -> float:
        """High impact / low effort = high ROI."""
        return self.impact_score / (self.effort_score + 0.01)


# ============================================================
# OpsPulse use-case portfolio
# ============================================================

OPSPULSE_USE_CASES = [
    UseCaseScore(
        name="Column description auto-generation",
        description="Generate dbt column descriptions for all tables via evaluator-optimizer loop",
        impact={
            ImpactDimension.TIME_SAVINGS:        0.90,  # eliminates 2-3h manual work per table
            ImpactDimension.QUALITY_IMPROVEMENT: 0.70,  # consistent, reviewable descriptions
            ImpactDimension.ADOPTION_SIGNAL:     0.60,  # better catalog → more usage
            ImpactDimension.COST_REDUCTION:      0.50,
        },
        effort={
            EffortDimension.CONTEXT_READINESS:  0.30,  # needs INFORMATION_SCHEMA only
            EffortDimension.INTEGRATION_EFFORT: 0.25,
            EffortDimension.EVAL_COMPLEXITY:    0.20,  # easy to judge description quality
            EffortDimension.RISK_LEVEL:         0.10,  # low: descriptions are advisory
        },
        notes="Best first use case for most teams. Low risk, high volume, easy to eval.",
        chapter_ref="Chapter 8",
    ),
    UseCaseScore(
        name="SQL generation assistant",
        description="Natural-language to Snowflake SQL with self-healing guardrails",
        impact={
            ImpactDimension.TIME_SAVINGS:        0.80,
            ImpactDimension.QUALITY_IMPROVEMENT: 0.65,
            ImpactDimension.ADOPTION_SIGNAL:     0.85,  # analysts get faster answers
            ImpactDimension.COST_REDUCTION:      0.60,
        },
        effort={
            EffortDimension.CONTEXT_READINESS:  0.50,  # needs semantic layer
            EffortDimension.INTEGRATION_EFFORT: 0.45,
            EffortDimension.EVAL_COMPLEXITY:    0.55,  # SQL correctness is hard to eval
            EffortDimension.RISK_LEVEL:         0.40,  # wrong SQL can mislead decisions
        },
        notes="High value but requires semantic layer and eval infrastructure.",
        chapter_ref="Chapter 9",
    ),
    UseCaseScore(
        name="Pipeline failure triage",
        description="Automated anomaly classification and runbook generation for Airflow failures",
        impact={
            ImpactDimension.TIME_SAVINGS:        0.75,
            ImpactDimension.QUALITY_IMPROVEMENT: 0.80,  # fewer incidents slip through
            ImpactDimension.ADOPTION_SIGNAL:     0.40,
            ImpactDimension.COST_REDUCTION:      0.65,
        },
        effort={
            EffortDimension.CONTEXT_READINESS:  0.45,
            EffortDimension.INTEGRATION_EFFORT: 0.60,  # needs Airflow callbacks + DAG wiring
            EffortDimension.EVAL_COMPLEXITY:    0.40,
            EffortDimension.RISK_LEVEL:         0.35,  # triage classifies; doesn't act autonomously
        },
        notes="High team satisfaction: replaces repetitive on-call triage work.",
        chapter_ref="Chapter 10",
    ),
    UseCaseScore(
        name="Lineage impact analysis",
        description="Automated blast-radius assessment before schema changes",
        impact={
            ImpactDimension.TIME_SAVINGS:        0.70,
            ImpactDimension.QUALITY_IMPROVEMENT: 0.90,  # prevents change-induced incidents
            ImpactDimension.ADOPTION_SIGNAL:     0.50,
            ImpactDimension.COST_REDUCTION:      0.55,
        },
        effort={
            EffortDimension.CONTEXT_READINESS:  0.55,  # needs dbt manifest + ACCESS_HISTORY
            EffortDimension.INTEGRATION_EFFORT: 0.50,
            EffortDimension.EVAL_COMPLEXITY:    0.50,
            EffortDimension.RISK_LEVEL:         0.20,  # analysis only; human decides
        },
        notes="Prevents the most expensive class of incidents: silent downstream breakage.",
        chapter_ref="Chapter 6",
    ),
]


def rank_use_cases(
    use_cases: list[UseCaseScore],
    sort_by: str = "roi",   # "roi" | "impact" | "effort"
) -> list[UseCaseScore]:
    """Rank use cases by the specified criterion."""
    key_map = {
        "roi":    lambda u: u.roi_score,
        "impact": lambda u: u.impact_score,
        "effort": lambda u: -u.effort_score,  # lower effort = higher rank
    }
    return sorted(use_cases, key=key_map.get(sort_by, key_map["roi"]), reverse=True)


if __name__ == "__main__":
    ranked = rank_use_cases(OPSPULSE_USE_CASES, sort_by="roi")
    print("OpsPulse AI use-case portfolio (ranked by ROI):\n")
    print(f"{'Rank':<6} {'Use Case':<40} {'Impact':>8} {'Effort':>8} {'ROI':>8}")
    print("-" * 72)
    for i, uc in enumerate(ranked, 1):
        print(f"{i:<6} {uc.name:<40} {uc.impact_score:>8.2f} {uc.effort_score:>8.2f} {uc.roi_score:>8.2f}")
        print(f"       {uc.notes}")
