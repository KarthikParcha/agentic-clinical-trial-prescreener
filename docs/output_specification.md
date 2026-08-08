# System Output Specification

## 1. Purpose

This document defines the outputs produced by Version 1.0 of the Agentic Clinical Trial Pre-Screening Assistant.

The system must produce structured, evidence-backed results that can be:

* Reviewed by humans
* Verified by the Verification Agent
* Stored in a database
* Used for evaluation
* Reused by future dashboard and chat interfaces

The system must not return only an uncontrolled natural-language response.

---

# 2. Output Flow

```text
Patient Profile
        +
Clinical Trial
        ↓
Eligibility Criteria
        ↓
Criterion Assessments
        ↓
Trial-Level Assessment
        ↓
Verification Result
        ↓
Pre-Screening Report
        ↓
Human Review
```

---

# 3. Criterion Assessment

Each eligibility criterion must produce one structured assessment.

Required fields include:

| Field                 | Purpose                               |
| --------------------- | ------------------------------------- |
| criterion_id          | Unique identifier for the criterion   |
| criterion_type        | INCLUSION or EXCLUSION                |
| category              | Age, BMI, HbA1c, medication, etc.     |
| criterion_text        | Original trial wording                |
| status                | MET, NOT_MET, UNKNOWN, NOT_APPLICABLE |
| reason                | Why the status was selected           |
| trial_evidence        | Trial text supporting the rule        |
| patient_evidence      | Patient information used              |
| missing_information   | Information required but unavailable  |
| evaluation_method     | Python rule or LLM-assisted           |
| requires_human_review | Whether human review is needed        |

---

# 4. Criterion Status Definitions

## MET

The available patient information clearly satisfies the criterion.

Example:

```text
Criterion:
Participant age must be between 18 and 65.

Patient:
Age 48.

Status:
MET.
```

---

## NOT_MET

The available patient information clearly fails the criterion.

Example:

```text
Criterion:
HbA1c must be 10% or lower.

Patient:
HbA1c = 10.8%.

Status:
NOT_MET.
```

---

## UNKNOWN

The system does not have enough reliable patient information to evaluate the criterion.

Example:

```text
Criterion:
eGFR must be greater than 60.

Patient:
No eGFR result available.

Status:
UNKNOWN.

Missing Information:
Latest eGFR result.
```

Missing information must never automatically produce `MET`.

---

## NOT_APPLICABLE

The criterion explicitly does not apply to the current patient or assessment.

This status must not be used simply because information is unavailable.

---

# 5. Evidence Requirements

Every criterion assessment should preserve two forms of evidence.

## Trial Evidence

The original text from the clinical-trial eligibility criteria.

Example:

```text
Participants must have an HbA1c between 7.0% and 10.0%.
```

## Patient Evidence

The specific patient field used for evaluation.

Example:

```text
Field: HbA1c
Value: 8.2%
Measured Date: 2026-07-15
```

If no patient evidence is available:

```text
Patient Evidence:
Not available

Status:
UNKNOWN
```

---

# 6. Evaluation Method

Each assessment should identify how it was produced.

Possible values:

```text
DETERMINISTIC_RULE
LLM_ASSISTED
HUMAN_REVIEW
```

Example:

```text
Age comparison
→ DETERMINISTIC_RULE

Complex medical-history criterion
→ LLM_ASSISTED
```

This improves explainability and debugging.

---

# 7. Trial-Level Assessment

After all criteria for one trial are evaluated, the system will produce a trial-level assessment.

Required fields may include:

| Field                 | Purpose                           |
| --------------------- | --------------------------------- |
| patient_id            | Synthetic patient identifier      |
| trial_id              | NCT identifier                    |
| trial_title           | Trial title                       |
| recruitment_status    | Trial recruitment state           |
| criterion_assessments | All criterion results             |
| met_count             | Number of MET criteria            |
| not_met_count         | Number of NOT_MET criteria        |
| unknown_count         | Number of UNKNOWN criteria        |
| not_applicable_count  | Number of NOT_APPLICABLE criteria |
| overall_status        | Preliminary trial-match status    |
| missing_information   | Consolidated missing patient data |
| possible_exclusions   | Important exclusion findings      |
| verification_status   | Verification result               |
| requires_human_review | Human-review flag                 |

---

# 8. Overall Trial Status

Version 1 will use the following preliminary statuses.

## POSSIBLE_MATCH

Available information suggests that the patient may be worth further screening.

This does not mean the patient is eligible.

---

## UNLIKELY_MATCH

One or more clear eligibility findings suggest the patient is unlikely to qualify.

The final decision remains with the study team.

---

## INSUFFICIENT_INFORMATION

Critical information required to evaluate the trial is unavailable.

The system should clearly identify the missing information.

---

## HUMAN_REVIEW_REQUIRED

The automated workflow cannot safely determine a reliable preliminary status.

Possible reasons include:

* Conflicting patient information
* Ambiguous eligibility language
* Unsupported medical interpretation
* Verification disagreement
* Maximum retry limit reached

---

# 9. Verification Output

The Verification Agent must return a structured verification result.

Possible statuses:

```text
APPROVED
CORRECTED
REQUIRES_REEVALUATION
HUMAN_REVIEW
```

The verification result should contain:

* Verification status
* Findings
* Corrected assessments if applicable
* Unsupported conclusions
* Missing evidence
* Overlooked exclusions
* Human-review reason

---

# 10. Missing-Information Output

Missing information should be returned as structured data.

Example:

```json
[
  {
    "field": "eGFR",
    "reason": "Required to evaluate INC-006",
    "priority": "HIGH"
  },
  {
    "field": "insulin_history",
    "reason": "Required to evaluate EXC-003",
    "priority": "HIGH"
  }
]
```

Potential priorities:

```text
HIGH
MEDIUM
LOW
```

Version 1 may begin with only `HIGH` and `NORMAL` if simpler.

---

# 11. Example Criterion Assessment

```json
{
  "criterion_id": "INC-003",
  "criterion_type": "INCLUSION",
  "category": "HBA1C",
  "criterion_text": "Participants must have HbA1c between 7.0% and 10.0%.",
  "status": "MET",
  "reason": "Patient HbA1c is within the required range.",
  "trial_evidence": "Participants must have HbA1c between 7.0% and 10.0%.",
  "patient_evidence": {
    "field": "HbA1c",
    "value": 8.2,
    "unit": "%",
    "measured_date": "2026-07-15"
  },
  "missing_information": [],
  "evaluation_method": "DETERMINISTIC_RULE",
  "requires_human_review": false
}
```

---

# 12. Example UNKNOWN Assessment

```json
{
  "criterion_id": "INC-006",
  "criterion_type": "INCLUSION",
  "category": "KIDNEY_FUNCTION",
  "criterion_text": "Participants must have eGFR greater than 60 mL/min/1.73m2.",
  "status": "UNKNOWN",
  "reason": "No recent eGFR result is available in the patient profile.",
  "trial_evidence": "Participants must have eGFR greater than 60 mL/min/1.73m2.",
  "patient_evidence": null,
  "missing_information": [
    "Latest eGFR result"
  ],
  "evaluation_method": "DETERMINISTIC_RULE",
  "requires_human_review": false
}
```

---

# 13. Example Trial-Level Result

```json
{
  "patient_id": "DEMO-P001",
  "trial_id": "NCT12345678",
  "trial_title": "Type 2 Diabetes Treatment Study",
  "overall_status": "POSSIBLE_MATCH",
  "met_count": 8,
  "not_met_count": 0,
  "unknown_count": 2,
  "not_applicable_count": 1,
  "missing_information": [
    "Latest eGFR result",
    "Recent insulin-use history"
  ],
  "possible_exclusions": [],
  "verification_status": "APPROVED",
  "requires_human_review": true
}
```

---

# 14. Human-Readable Report

After structured assessment and verification, the application may generate a readable report.

Example:

```text
Clinical Trial Pre-Screening Report

Patient:
DEMO-P001

Trial:
NCT12345678

Preliminary Status:
POSSIBLE MATCH

Summary:
8 criteria met
0 criteria not met
2 criteria unknown
1 criterion not applicable

Missing Information:
- Latest eGFR result
- Recent insulin-use history

Verification:
Assessment passed automated verification.

Important:
This is a preliminary automated pre-screening result.
Final eligibility must be confirmed by the clinical-trial study team.
```

The readable report must be generated from the approved structured assessment.

The report generator must not silently change assessment statuses.

---

# 15. Output for Multiple Candidate Trials

Version 1 may evaluate up to three candidate trials.

The patient-level output may contain:

```text
Patient DEMO-P001

Trial 1
NCT001
POSSIBLE_MATCH

Trial 2
NCT002
UNLIKELY_MATCH

Trial 3
NCT003
INSUFFICIENT_INFORMATION
```

Each trial must retain its own criterion-level details.

---

# 16. Future Version 1.1 Output

Batch processing may later produce:

```text
50 patients
        ↓
Patient-Trial Assessments
        ↓
Review Queue
```

Possible batch fields:

* Patient ID
* Trial ID
* Overall status
* Number of unknown criteria
* Number of exclusions
* Verification status
* Review priority

Version 1 output models should be designed so they can later be stored and reused by Version 1.1.

---

# 17. Future Version 2 Output

The coordinator review application may reuse the structured output for:

* Dashboard metrics
* SQL queries
* Patient-level explanations
* Trial summaries
* RAG-based evidence explanations
* Cohort-level analytics

This is another reason Version 1 should return structured data rather than only natural-language responses.

---

# 18. Output Safety Rules

The system must follow these rules:

1. Never output `ELIGIBLE` as an automated final decision.
2. Never convert missing information into `MET`.
3. Every assessment must preserve trial evidence.
4. Every `MET` or `NOT_MET` result should identify patient evidence.
5. Conflicting information must be escalated.
6. Exclusion criteria must remain clearly identifiable.
7. Verification results must be preserved.
8. The final report must state that human review is required.
9. The report generator must not modify validated assessment data.
10. Structured data is the system of record; natural-language reports are derived views.

---

# 19. Output Success Criteria

The output layer is successful when:

* Every trial criterion has a status.
* Every status has a reason.
* Supporting evidence is retained.
* Missing information is clearly identified.
* Overall trial status is separate from final eligibility.
* Verification results are visible.
* Results can be stored in a database.
* Results can later support batch processing.
* Results can later support coordinator chat.
* Human review remains mandatory.
