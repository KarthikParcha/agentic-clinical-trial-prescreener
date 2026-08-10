# Trial-Level Assessment Rules

## Purpose

Criterion-level assessments are aggregated into a preliminary trial-level status.

The automated system must not produce a final eligibility decision.

## Trial-Level Statuses

```text
POSSIBLE_MATCH

UNLIKELY_MATCH

INSUFFICIENT_INFORMATION

HUMAN_REVIEW_REQUIRED
```

## Decision Order

```text
Criterion Assessments
        ↓
Critical conflict or ambiguity?
        ↓
YES → HUMAN_REVIEW_REQUIRED

        ↓ NO

Any inclusion criterion = NOT_MET?
OR
Any exclusion criterion = MET?
        ↓
YES → UNLIKELY_MATCH

        ↓ NO

Too much critical information = UNKNOWN?
        ↓
YES → INSUFFICIENT_INFORMATION

        ↓ NO

POSSIBLE_MATCH
```

## Inclusion Rules

```text
INCLUSION + MET
→ Requirement satisfied

INCLUSION + NOT_MET
→ Known problem

INCLUSION + UNKNOWN
→ Missing evidence
```

## Exclusion Rules

```text
EXCLUSION + MET
→ Exclusion triggered

EXCLUSION + NOT_MET
→ Exclusion not triggered

EXCLUSION + UNKNOWN
→ Cannot determine whether exclusion applies
```

## Possible Match

Use when:

* No known inclusion failure exists.
* No known exclusion is triggered.
* Enough patient information exists to make a useful preliminary assessment.

`POSSIBLE_MATCH` never means final eligibility.

## Unlikely Match

Use when:

* At least one important inclusion criterion is clearly not met, or
* At least one exclusion criterion is clearly triggered.

## Insufficient Information

Use when too much critical patient information is missing to make the preliminary assessment useful.

The missing information must be returned explicitly.

## Human Review Required

Use when automated evaluation cannot safely resolve the assessment because of:

* Conflicting patient evidence
* Ambiguous criterion language
* Complex medical interpretation
* Verification disagreement
* Unsupported assumptions
* Workflow retry limits

## No Percentage Eligibility Score

Version 1 will not calculate an eligibility percentage.

Eligibility criteria do not have equal importance.

One triggered exclusion may outweigh many satisfied inclusion criteria.

## Safety Rule

```text
The system produces a preliminary screening status.

The clinical trial team makes the final eligibility decision.
```
