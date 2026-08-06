# Manual Clinical Trial Pre-Screening Workflow

## 1. Purpose

This document describes how a Clinical Research Coordinator may manually perform preliminary clinical-trial screening before using an automated assistant.

Understanding the manual process helps identify:

* Which steps should remain human-controlled
* Which steps can use deterministic software
* Which steps require external tools
* Which steps may require language-model reasoning
* Which steps may benefit from agentic decision-making

The application will support this workflow but will not make the final clinical-trial eligibility decision.

---

## 2. High-Level Manual Workflow

```text
Receive Patient Profile
        ↓
Validate Basic Information
        ↓
Define Trial Search Requirements
        ↓
Search ClinicalTrials.gov
        ↓
Review and Filter Candidate Trials
        ↓
Read Trial Eligibility Criteria
        ↓
Separate Inclusion and Exclusion Criteria
        ↓
Compare Each Criterion with Patient Data
        ↓
Identify Missing Information
        ↓
Prepare Preliminary Assessment
        ↓
Verify Findings
        ↓
Send for Human Review
```

---

## 3. Step 1 — Receive Patient Profile

### Input

Available patient information may include:

* Age
* Sex
* Location
* Diagnosis
* Diagnosis duration
* BMI
* HbA1c
* Current medications
* Previous treatments
* Medical history
* Kidney-function results
* Liver-function results
* Pregnancy status
* Previous clinical-trial participation

### Manual Action

The coordinator reviews the patient profile and determines whether enough basic information is available to begin trial searching.

### Output

A patient profile ready for preliminary trial search.

### Possible Problems

* Required fields are missing
* Units are unclear
* Laboratory values are outdated
* Medication history is incomplete
* Patient information is contradictory

### Future Implementation

```text
Primary approach:
Pydantic validation and deterministic Python rules

Human involvement:
Required when information is contradictory or unclear
```

---

## 4. Step 2 — Validate Basic Patient Information

### Input

Raw patient profile.

### Manual Action

The coordinator confirms:

* Age is available
* Diagnosis is known
* Location is known
* Required numeric values use valid units
* Dates are understandable
* The information appears internally consistent

### Output

Validated patient profile or a list of missing and invalid fields.

### Possible Problems

* Age and date of birth do not match
* BMI is outside a realistic range
* Laboratory units are missing
* Diagnosis duration is unavailable
* Conflicting medication information exists

### Future Implementation

```text
Deterministic Python
+
Schema validation
+
Human review for contradictions
```

This step should not require an autonomous agent.

---

## 5. Step 3 — Define Trial Search Requirements

### Input

Validated patient profile.

### Manual Action

The coordinator determines the initial search criteria:

* Medical condition
* Country or location
* Recruitment status
* Study type
* Age
* Sex
* Maximum number of candidate trials

### Output

A structured trial-search request.

### Possible Problems

* Search is too broad
* Search is too restrictive
* Location preference is unclear
* Too many irrelevant trials are returned
* No trials are found

### Future Implementation

Version 1 will initially use deterministic search parameters.

Later, a Coordinator Agent may decide whether the search should be broadened or narrowed.

---

## 6. Step 4 — Search ClinicalTrials.gov

### Input

Structured trial-search request.

### Manual Action

The coordinator searches ClinicalTrials.gov and reviews returned study records.

### Output

A list of potentially relevant clinical trials.

### Possible Problems

* No results
* Too many results
* Trial status is not recruiting
* Trial location is unsuitable
* Trial condition is only loosely related
* API or network failure

### Future Implementation

```text
ClinicalTrials.gov API tool
+
Deterministic filters
```

The API client is a tool, not an agent.

---

## 7. Step 5 — Review and Filter Candidate Trials

### Input

Trial-search results.

### Manual Action

The coordinator checks:

* Recruitment status
* Study type
* Condition
* Age range
* Sex restrictions
* Country and site locations
* Trial purpose
* Availability of eligibility information

### Output

A smaller set of candidate trials selected for detailed analysis.

### Possible Problems

* Trial appears relevant from the title but is not relevant after review
* Trial has no suitable local site
* Trial record is incomplete
* Trial status changed
* Too many trials remain

### Future Implementation

```text
Deterministic filtering
+
Potential Coordinator Agent decision
```

The agent may later decide whether to:

* Keep the candidates
* Apply additional filters
* Broaden the search
* Stop because no suitable studies were found

---

## 8. Step 6 — Read Trial Eligibility Criteria

### Input

Selected trial record.

### Manual Action

The coordinator reads the eligibility section, which may contain long free-text inclusion and exclusion criteria.

### Output

Eligibility text ready for structured analysis.

### Possible Problems

* Inclusion and exclusion criteria are mixed
* Criteria contain multiple rules in one sentence
* Medical language is ambiguous
* Important details are embedded in paragraphs
* Negation is difficult to interpret

### Future Implementation

```text
LLM-based structured extraction node
```

This is a fixed transformation:

```text
Eligibility text
→ Structured individual criteria
```

Therefore, it should begin as a workflow node rather than an autonomous agent.

---

## 9. Step 7 — Separate Inclusion and Exclusion Criteria

### Input

Raw eligibility text.

### Manual Action

The coordinator identifies:

* Inclusion criteria
* Exclusion criteria
* Criterion categories
* Numeric thresholds
* Date windows
* Required patient facts

### Output

A structured list of individual criteria.

Example:

```text
INC-001
Type: Inclusion
Category: Age
Criterion: Participant must be between 18 and 65 years old.

EXC-001
Type: Exclusion
Category: Medication
Criterion: Current insulin treatment is not permitted.
```

### Possible Problems

* Exclusion criterion classified as inclusion
* Multiple conditions incorrectly combined
* Criterion is duplicated
* Criterion is invented
* Original source wording is lost

### Future Implementation

```text
Structured LLM output
+
Schema validation
+
Original evidence preservation
```

---

## 10. Step 8 — Compare Each Criterion with Patient Data

### Input

* Structured eligibility criterion
* Validated patient profile

### Manual Action

The coordinator compares the criterion with the relevant patient information.

### Output

One of the following statuses:

```text
MET
NOT_MET
UNKNOWN
NOT_APPLICABLE
```

### Example 1 — Deterministic Criterion

```text
Criterion:
Age between 18 and 65

Patient:
Age 48

Result:
MET
```

### Example 2 — Missing Information

```text
Criterion:
eGFR greater than 60 mL/min

Patient:
No eGFR value available

Result:
UNKNOWN
```

### Example 3 — Exclusion Criterion

```text
Criterion:
Current insulin treatment is excluded

Patient:
Currently using insulin

Result:
Exclusion criterion MET
```

This may cause the overall pre-screening status to become an unlikely match, subject to human review.

### Possible Problems

* Missing data treated as `MET`
* Wrong patient field used
* Units compared incorrectly
* Date windows calculated incorrectly
* Negation misunderstood
* Exclusion status interpreted incorrectly

### Future Implementation

```text
Simple numeric and factual criteria:
Deterministic Python

Complex semantic criteria:
LLM-assisted evaluator

Final result:
Human review required
```

---

## 11. Step 9 — Identify Missing Information

### Input

Criteria classified as `UNKNOWN`.

### Manual Action

The coordinator determines what additional patient information is required.

### Output

A focused missing-information list.

Example:

```text
Missing Information

- Latest eGFR result
- Six-month insulin-use history
- Pregnancy status
- Recent cardiovascular-event history
```

### Possible Problems

* Asking for information unrelated to the trial
* Asking vague questions
* Requesting too many fields
* Failing to identify a critical missing field

### Future Implementation

```text
Rule-based missing-field detection
+
Coordinator Agent decision for targeted follow-up questions
```

---

## 12. Step 10 — Prepare Preliminary Assessment

### Input

All criterion-level assessments.

### Manual Action

The coordinator summarizes:

* Criteria met
* Criteria not met
* Unknown criteria
* Possible exclusion criteria
* Missing information
* Supporting evidence

### Output

A preliminary patient-trial assessment.

### Possible Overall Statuses

```text
POSSIBLE_MATCH

UNLIKELY_MATCH

INSUFFICIENT_INFORMATION

HUMAN_REVIEW_REQUIRED
```

The overall status is not a final eligibility decision.

### Future Implementation

```text
Deterministic aggregation rules
+
Structured report generation
```

The report generator should format approved data but should not change assessment statuses.

---

## 13. Step 11 — Verify the Preliminary Assessment

### Input

* Trial criteria
* Patient data
* Preliminary criterion assessments
* Supporting evidence

### Manual Action

A second reviewer checks:

* Whether every conclusion has evidence
* Whether the correct patient field was used
* Whether missing information was handled safely
* Whether exclusion criteria were considered
* Whether dates and numeric values were compared correctly
* Whether unsupported assumptions were introduced

### Output

Verified, corrected, or escalated assessment.

### Possible Problems

* Reviewer repeats the same mistake
* Unsupported conclusion remains unnoticed
* Correct result is unnecessarily rejected
* Contradictory evidence is not detected

### Future Implementation

```text
Deterministic verification rules
+
Verification Agent
+
Human escalation
```

The Verification Agent is meaningful because it may:

* Approve
* Correct
* Request reevaluation
* Escalate
* Stop the workflow

---

## 14. Step 12 — Human Review and Final Decision

### Input

Verified pre-screening report.

### Manual Action

A qualified clinician, investigator, or clinical-trial study team reviews the report and performs the official screening process.

### Output

A human-controlled decision about whether the patient should proceed to further trial screening.

### Future Implementation

```text
Human-in-the-loop checkpoint
```

This step must never be fully automated in Version 1.

---

## 15. Workflow Classification

| Workflow Step                 | Best Initial Implementation     |
| ----------------------------- | ------------------------------- |
| Patient validation            | Pydantic and Python             |
| Age calculation               | Python                          |
| Numeric range comparison      | Python                          |
| Date-window calculation       | Python                          |
| Trial search                  | ClinicalTrials.gov API tool     |
| Location filtering            | Python                          |
| Criteria extraction           | LLM workflow node               |
| Simple eligibility evaluation | Python                          |
| Complex semantic evaluation   | LLM workflow node               |
| Search adjustment             | Coordinator Agent               |
| Missing-information decision  | Coordinator Agent               |
| Verification                  | Rules plus Verification Agent   |
| Report formatting             | Deterministic code or small LLM |
| Final eligibility decision    | Human                           |

---

## 16. Agent Candidates Identified from the Workflow

### Coordinator Agent

Potential responsibilities:

* Decide the next workflow step
* Broaden or narrow trial search
* Decide whether missing information should be requested
* Decide whether evaluation can continue
* Stop after maximum iterations
* Route the case to verification or human review

### Verification Agent

Potential responsibilities:

* Review unsupported conclusions
* Detect missing evidence
* Detect overlooked exclusions
* Correct unsafe classifications
* Request reevaluation
* Escalate ambiguous cases to a human

### Components That Are Not Agents

The following should initially remain tools, functions, or workflow nodes:

* ClinicalTrials.gov API client
* Patient validator
* Trial normalizer
* Age calculator
* Unit converter
* Date calculator
* Criteria extractor
* Numeric evaluator
* Report formatter

---

## 17. Final Workflow

```text
Synthetic Patient Profile
        ↓
Validate Patient Data
        ↓
Create Trial Search Request
        ↓
Search ClinicalTrials.gov
        ↓
Filter Candidate Trials
        ↓
Extract Structured Criteria
        ↓
Evaluate Deterministic Criteria
        ↓
Evaluate Complex Criteria
        ↓
Identify Missing Information
        ↓
Coordinator Decides Next Action
        ↓
Verification Agent Reviews Results
        ↓
Generate Pre-Screening Report
        ↓
Human Review
```

---

## 18. Main Engineering Principle

```text
Deterministic rules should use Python.

External information should use tools and APIs.

Fixed language transformations should use controlled LLM nodes.

Dynamic workflow decisions may use agents.

Final medical decisions must remain with humans.
```
