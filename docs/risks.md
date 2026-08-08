# Project Risks

## 1. Purpose

This document identifies important technical, AI, workflow, and safety risks for Version 1.0 of the Agentic Clinical Trial Pre-Screening Assistant.

The purpose is not to eliminate every possible failure.

The purpose is to:

* Identify high-impact failures early
* Design safeguards before implementation
* Define what must be tested
* Make agent behavior bounded and explainable
* Protect the human-review boundary

---

# 2. Risk 1 — Missing Data Treated as MET

## Example

Trial criterion:

```text
eGFR must be greater than 60.
```

Patient profile:

```text
eGFR not provided.
```

Incorrect result:

```text
MET
```

Correct result:

```text
UNKNOWN
```

## Impact

High.

The system could incorrectly suggest that a patient satisfies a requirement without evidence.

## Mitigation

* Missing information remains explicit
* `null` and `false` are treated differently
* Deterministic validation occurs before evaluation
* LLM prompts prohibit assumptions
* Verification checks every `MET` result for evidence

## Detection

Evaluation dataset must include missing-information cases.

---

# 3. Risk 2 — Inclusion and Exclusion Criteria Are Mixed

## Example

Trial text:

```text
Exclusion:
Current insulin therapy is not permitted.
```

If incorrectly treated as an inclusion criterion, the final assessment may become unsafe.

## Impact

High.

## Mitigation

Every criterion must preserve:

```text
criterion_type = INCLUSION | EXCLUSION
```

The original trial text must also be retained.

## Detection

Manually labelled criteria will be compared against extracted criteria.

---

# 4. Risk 3 — Negation Is Misunderstood

Examples:

```text
No myocardial infarction in the previous six months.

Participants currently using insulin are excluded.

No history of severe hypoglycemia.
```

LLMs can incorrectly reverse the meaning of negated statements.

## Impact

High.

## Mitigation

* Preserve original criterion wording
* Mark complex negation for semantic evaluation
* Verification Agent reviews high-risk conclusions
* Include negation cases in the golden dataset

---

# 5. Risk 4 — Wrong Patient Evidence Is Used

Example:

```text
Criterion:
HbA1c between 7% and 10%.

Incorrect evidence:
BMI = 29
```

## Impact

High.

## Mitigation

Every assessment must identify:

```text
patient_field
patient_value
```

Evaluation components should receive only relevant patient fields where practical.

## Detection

Verification checks whether the patient evidence matches the criterion category.

---

# 6. Risk 5 — Numeric Comparison Error

Examples:

```text
Age >= 18
BMI < 35
HbA1c between 7 and 10
eGFR > 60
```

## Impact

Medium to High.

## Mitigation

Numeric comparisons must use deterministic Python rather than an LLM.

Boundary conditions must be tested explicitly.

Examples:

```text
18
17
65
66
7.0
10.0
```

---

# 7. Risk 6 — Date-Window Error

Example:

```text
No investigational drug use during the previous 90 days.
```

Possible failures:

* Wrong reference date
* Month/day confusion
* Inclusive versus exclusive boundary error
* LLM calculation error

## Impact

High.

## Mitigation

Use deterministic date utilities.

LLMs should identify the relevant date rule but should not calculate elapsed time.

---

# 8. Risk 7 — Eligibility Criterion Hallucination

The criteria extractor may generate a requirement that does not exist in the trial record.

## Impact

High.

## Mitigation

Every extracted criterion must preserve:

```text
original_text
```

No extracted criterion should exist without source evidence.

## Detection

Compare extracted criteria against manually reviewed source text.

Track:

```text
Invented criteria
Missed criteria
Duplicated criteria
```

---

# 9. Risk 8 — Relevant Trial Is Missed

The ClinicalTrials.gov search configuration may be too restrictive.

Example:

```text
Condition wording differs
Location filter is too strict
Study status changes
```

## Impact

Medium.

## Mitigation

* Measure search Recall@K
* Preserve raw API results
* Keep search parameters visible
* Allow controlled search broadening later

Version 1 will initially use deterministic search behavior.

---

# 10. Risk 9 — Verification Agent Repeats the Same Error

A second LLM does not automatically guarantee correctness.

## Impact

High.

## Mitigation

Verification should combine:

```text
Deterministic checks
+
Independent LLM review
+
Human escalation
```

The verifier must receive:

* Original trial evidence
* Patient evidence
* Preliminary status
* Evaluation method

---

# 11. Risk 10 — Final Eligibility Is Claimed

Incorrect output:

```text
The patient is eligible for the trial.
```

Allowed output:

```text
POSSIBLE_MATCH
Human review required.
```

## Impact

Critical.

## Mitigation

* Final statuses exclude `ELIGIBLE`
* Output schema restricts allowed values
* Report template contains mandatory disclaimer
* Verification checks for prohibited final-decision language
* Human review is always required

---

# 12. Risk 11 — Contradictory Patient Information

Example:

```text
Medication list:
Insulin — CURRENT

Another field:
currently_using_insulin = false
```

## Impact

High.

## Mitigation

The input validation layer should detect contradictions.

The workflow should escalate rather than choose one value arbitrarily.

Possible result:

```text
HUMAN_REVIEW_REQUIRED
```

---

# 13. Risk 12 — Outdated Patient Evidence

Example:

```text
HbA1c value measured two years ago.
```

The value may technically exist but may no longer be appropriate evidence.

## Impact

Medium to High.

## Mitigation

Laboratory results retain:

```text
measured_date
```

Freshness rules can be added for supported criteria.

When evidence freshness cannot be determined safely:

```text
UNKNOWN
```

---

# 14. Risk 13 — Agent Infinite Loop

Example:

```text
Search
→ no results
→ search again
→ no results
→ search again
...
```

## Impact

Medium.

It increases cost, latency, and unpredictability.

## Mitigation

Define:

```text
max_agent_iterations
max_search_retries
max_model_retries
```

When limits are reached:

```text
HUMAN_REVIEW
or
STOP
```

---

# 15. Risk 14 — Excessive LLM Cost

Complex trial criteria may create many model calls.

## Mitigation

* Extract trial criteria once
* Cache extracted criteria
* Use deterministic evaluators first
* Send only unresolved criteria to the LLM
* Use smaller models for simple tasks
* Limit candidate trials

---

# 16. Risk 15 — Sensitive Data Exposure

Version 1 uses synthetic patient information only.

Future real-world versions would require stronger privacy, security, audit, authorization, and data-retention controls.

## Version 1 Mitigation

* No real patient information
* No PHI
* No PII
* Secrets stored in environment variables
* Logs contain synthetic identifiers only

---

# 17. Risk Priority

## Critical

* Final eligibility claim

## High

* Missing data treated as MET
* Inclusion/exclusion confusion
* Negation error
* Wrong patient evidence
* Date-window error
* Hallucinated criteria
* Verification failure
* Contradictory patient data

## Medium

* Numeric boundary errors
* Trial search misses
* Outdated evidence
* Agent loops
* Excessive cost

---

# 18. Main Safety Principle

```text
When evidence is missing or conflicting,
the system should become less confident,
not more confident.
```

The safe outcome is:

```text
UNKNOWN
or
HUMAN_REVIEW_REQUIRED
```

rather than an unsupported positive match.
