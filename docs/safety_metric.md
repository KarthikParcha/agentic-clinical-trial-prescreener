# Success Metrics

## 1. Purpose

This document defines measurable success criteria for Version 1.0 of the Agentic Clinical Trial Pre-Screening Assistant.

The project should not be considered successful only because the application runs or produces convincing natural-language responses.

Success must be measured across:

* Trial discovery
* Criteria extraction
* Criterion evaluation
* Missing-information handling
* Verification
* Safety
* Reliability
* Performance

---

# 2. Version 1 Success Definition

Version 1 is successful when it can:

1. Accept a validated synthetic Type 2 Diabetes patient profile.
2. Find relevant recruiting clinical trials.
3. Extract individual inclusion and exclusion criteria.
4. Evaluate supported criteria correctly.
5. Preserve trial and patient evidence.
6. Mark unavailable information as `UNKNOWN`.
7. Verify preliminary assessments.
8. Produce a structured pre-screening report.
9. Avoid unsupported eligibility claims.
10. Require human review.

---

# 3. Evaluation Dataset

The initial golden dataset should contain approximately:

```text
3–5 synthetic patient profiles
5–10 selected trials
30–50 important eligibility criteria
```

Each manually labelled criterion should contain:

```text
Expected criterion type
Expected status
Expected patient evidence
Expected trial evidence
Expected missing information
Reviewer notes
```

The golden dataset is the reference used to evaluate the system.

---

# 4. Trial Discovery Metrics

## Recall@5

Question:

> Is the expected relevant trial present among the first five returned trials?

Formula conceptually:

```text
Expected relevant trials found in Top 5
----------------------------------------
Total expected relevant trials
```

### Initial target

```text
Recall@5 >= 80%
```

This is an initial project target and may be revised after observing the dataset.

---

# 5. Criteria Extraction Metrics

Measure:

```text
Correct criteria extracted
Missed criteria
Invented criteria
Duplicate criteria
Incorrect INCLUSION / EXCLUSION classification
```

## Important Safety Target

```text
Invented criteria = 0
```

The model must not create eligibility requirements that are absent from the trial source.

## Initial Extraction Target

```text
Correct important criteria >= 90%
```

Focus first on important eligibility criteria rather than every formatting detail.

---

# 6. Criterion Evaluation Accuracy

Evaluate separately:

```text
MET accuracy
NOT_MET accuracy
UNKNOWN accuracy
NOT_APPLICABLE accuracy
```

Example:

```text
Expected: MET
Predicted: MET
→ Correct
```

```text
Expected: UNKNOWN
Predicted: MET
→ Critical error
```

## Initial Overall Target

```text
Criterion-status accuracy >= 90%
```

The most safety-sensitive error categories should have stricter targets.

---

# 7. Missing-Information Safety Metric

The most important metric is:

```text
Missing-data false-MET rate
```

Example:

```text
Patient eGFR unavailable
System predicts MET
```

This is a serious error.

## Target

```text
Missing-data false-MET rate = 0%
```

---

# 8. Evidence Coverage

Every `MET` and `NOT_MET` assessment should contain:

```text
Trial evidence
+
Patient evidence
```

## Target

```text
Evidence coverage = 100%
```

For `UNKNOWN`, the system should identify:

```text
Missing information
```

whenever possible.

---

# 9. Inclusion / Exclusion Classification

The extractor must correctly identify whether each criterion belongs to:

```text
INCLUSION
or
EXCLUSION
```

## Initial target

```text
Classification accuracy >= 95%
```

Any incorrectly classified exclusion criterion must be manually reviewed during evaluation.

---

# 10. Verification Metrics

Create intentionally incorrect preliminary assessments.

Measure:

```text
Incorrect assessments detected by verifier
Incorrect assessments missed by verifier
Correct assessments incorrectly rejected
```

## Initial target

```text
Verifier detects >= 90% of deliberately injected high-risk errors.
```

High-risk injected errors should include:

* Missing evidence classified as MET
* Wrong patient field
* Missed exclusion criterion
* Reversed negation
* Incorrect numeric conclusion

---

# 11. Final Eligibility Claim Metric

Automated output must never state that the patient is definitively eligible.

Examples of prohibited outputs:

```text
Patient is eligible.
Patient qualifies for this trial.
Patient should be enrolled.
```

## Target

```text
Final eligibility claims = 0
```

---

# 12. Human Review Metric

Every final Version 1 report must preserve:

```text
requires_human_review = true
```

## Target

```text
Human-review flag coverage = 100%
```

---

# 13. Structured Output Reliability

LLM outputs that require schemas must successfully validate.

Measure:

```text
Valid structured outputs
Schema validation failures
Retry count
Permanent failures
```

## Initial target

```text
Structured-output success >= 98%
after one controlled retry.
```

---

# 14. Workflow Reliability

Measure:

```text
Successful end-to-end executions
Failed executions
API failures
Model failures
Agent-loop failures
Human escalations
```

## Initial target

```text
End-to-end technical completion >= 95%
for the controlled evaluation dataset.
```

This does not mean 95% medical correctness.

It measures whether the workflow executes successfully.

---

# 15. Agent-Boundary Metric

Coordinator and Verification Agents must remain within configured limits.

Track:

```text
Iterations per run
Tool calls per run
Retries per run
```

## Requirement

No workflow may exceed:

```text
max_agent_iterations
```

without stopping or escalating.

---

# 16. Performance Metrics

Track:

```text
Trial-search latency
Criteria-extraction latency
Evaluation latency
Verification latency
Total workflow latency
LLM calls
Prompt tokens
Completion tokens
Estimated cost
Cache hits
```

Version 1 prioritizes correctness over speed.

Performance measurements are primarily used to identify inefficient design.

---

# 17. Cost Metric

Track approximate model cost per patient-trial assessment.

The goal is not a fixed rupee value initially.

The initial goal is:

```text
Avoid unnecessary LLM calls.
```

Desired architecture:

```text
Deterministic evaluation first
        ↓
LLM only for unresolved semantic criteria
```

---

# 18. Failure Taxonomy

Every incorrect result should be classified.

Possible categories:

```text
SEARCH_FAILURE

EXTRACTION_FAILURE

NORMALIZATION_FAILURE

RULE_FAILURE

LLM_REASONING_FAILURE

MISSING_DATA_FAILURE

VERIFICATION_FAILURE

REPORTING_FAILURE
```

This allows improvements to target the correct component.

---

# 19. Minimum Version 1 Release Criteria

Version 1 should not be tagged as complete until:

```text
[ ] Missing-data false-MET rate = 0
[ ] Final eligibility claims = 0
[ ] Every MET / NOT_MET result has evidence
[ ] Inclusion and exclusion criteria remain distinguishable
[ ] Golden dataset has been executed
[ ] Verification Agent has been tested with injected errors
[ ] Agent loops have maximum limits
[ ] Human-review flag appears on all reports
[ ] Known limitations are documented
[ ] Evaluation results are published honestly
```

---

# 20. Engineering Principle

```text
If we cannot measure whether the system improved,
we do not know whether the change was actually an improvement.
```

Evaluation is part of the product, not something added after development.
