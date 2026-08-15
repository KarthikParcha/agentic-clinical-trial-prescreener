"""Deterministic evidence normalization for bounded verification."""

from clinical_trial_prescreener.domain.assessment import CriterionAssessment
from clinical_trial_prescreener.domain.criterion import (
    EligibilityCriterion,
    TemporalWindow,
)


class VerificationContextBuilder:
    """Expose effective compound temporal semantics without asking the LLM to infer them."""

    def build(
        self,
        criteria: list[EligibilityCriterion],
        assessments: list[CriterionAssessment],
    ) -> dict[str, object]:
        return {
            "criteria": [self._criterion(item, None) for item in criteria],
            "criterion_assessments": [item.model_dump(mode="json") for item in assessments],
        }

    def _criterion(
        self, criterion: EligibilityCriterion, inherited: TemporalWindow | None
    ) -> dict[str, object]:
        effective = criterion.temporal_window or inherited
        source = (
            "explicit"
            if criterion.temporal_window is not None
            else "inherited_from_parent"
            if inherited is not None
            else "not_applicable"
        )
        data = criterion.model_dump(mode="json")
        data["effective_temporal_window"] = (
            effective.model_dump(mode="json") if effective is not None else None
        )
        data["temporal_source"] = source
        if criterion.temporal_window is not None and inherited is not None and criterion.temporal_window != inherited:
            data["temporal_conflict"] = {
                "expected_inherited": inherited.model_dump(mode="json"),
                "observed_explicit": criterion.temporal_window.model_dump(mode="json"),
            }
        data["children"] = [
            self._criterion(child, effective) for child in criterion.children
        ]
        return data
