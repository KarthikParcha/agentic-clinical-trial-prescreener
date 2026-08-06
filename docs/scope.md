# Project Scope

## 1. Project Name

**Agentic Clinical Trial Pre-Screening Assistant**

---

## 2. Purpose

The application assists a Clinical Research Coordinator with preliminary clinical-trial screening.

It searches for relevant trials, compares available synthetic patient information with trial eligibility criteria, identifies missing information, verifies the assessment, and produces an evidence-backed report for human review.

The system does not make a final clinical-trial eligibility decision.

---

# 3. Product Version Strategy

The project will be delivered incrementally.

```text
Version 1.0
Single-patient pre-screening workflow

        ↓

Version 1.1
Batch patient assessment and persistence

        ↓

Version 2.0
Coordinator dashboard and conversational review assistant
```

Each version must be stable before the next version begins.

---

# 4. Version 1.0 Objective

Version 1.0 will:

> Accept one synthetic Type 2 Diabetes patient profile, search for a limited number of recruiting clinical trials, evaluate the patient against each trial’s eligibility criteria, verify the conclusions, and generate a human-reviewable pre-screening report.

---

# 5. Version 1.0 High-Level Flow

```text
One Synthetic Patient
        ↓
Validate Patient Profile
        ↓
Create Trial Search Request
        ↓
Search ClinicalTrials.gov
        ↓
Select Up to Three Candidate Trials
        ↓
Extract Structured Eligibility Criteria
        ↓
Evaluate Patient Against Criteria
        ↓
Classify Criteria
        ↓
Identify Missing Information
        ↓
Verification Agent Reviews Results
        ↓
Generate Pre-Screening Report
        ↓
Human Review
```

---

# 6. Version 1.0 In Scope

## Patient Scope

* One synthetic patient per workflow execution
* Type 2 Diabetes diagnosis
* Structured patient profile
* No real patient-identifying information
* Patient fields relevant to Version 1 criteria

Possible patient fields include:

* Patient ID
* Age
* Sex
* Country
* Diagnosis
* Diagnosis duration
* BMI
* HbA1c
* Current medications
* Previous treatments
* Medical history
* Kidney-function information
* Liver-function information
* Pregnancy status
* Previous clinical-trial participation

---

## Trial Scope

* ClinicalTrials.gov as the trial-data source
* Recruiting studies
* Interventional studies
* Type 2 Diabetes trials
* Country-based filtering
* Maximum of three candidate trials during normal execution
* Maximum of five candidate trials during controlled evaluation
* Trial details fetched by NCT ID
* Inclusion and exclusion eligibility criteria

---

## Assessment Scope

Each eligibility criterion will receive one status:

```text
MET
NOT_MET
UNKNOWN
NOT_APPLICABLE
```

Each assessment should contain:

* Criterion identifier
* Criterion type
* Original trial criterion
* Assessment status
* Reason
* Trial evidence
* Patient evidence
* Missing information
* Verification status

---

## Agent Scope

Version 1.0 will contain two meaningful agents.

### Coordinator Agent

Responsibilities may include:

* Decide the next workflow action
* Determine whether trial search should continue
* Decide whether missing information must be requested
* Route assessments for verification
* Enforce stopping and retry limits
* Escalate unresolved cases to human review

### Verification Agent

Responsibilities may include:

* Check that conclusions have evidence
* Detect unsupported assumptions
* Detect overlooked exclusion criteria
* Correct unsafe assessments
* Request reevaluation
* Escalate ambiguous results

---

## Tool and Workflow Scope

The following are tools, functions, or controlled workflow nodes rather than autonomous agents:

* Patient-profile validation
* ClinicalTrials.gov API client
* Trial-response normalization
* Criteria extraction
* Age calculation
* Date calculations
* BMI comparison
* HbA1c comparison
* Unit conversion
* Deterministic rule evaluation
* Report formatting
* Audit logging

---

## Interface Scope

Version 1.0 may use:

* Command-line execution, or
* A minimal local interface

A full coordinator dashboard and conversational interface are not required for Version 1.0.

---

## Evaluation Scope

Version 1.0 evaluation will use:

* Three to five synthetic patient profiles
* Five to ten selected clinical trials
* A manually labelled set of important eligibility criteria
* Retrieval and search evaluation
* Criteria-extraction evaluation
* Criterion-assessment evaluation
* Verification evaluation
* End-to-end failure analysis

The public demonstration may use one predefined synthetic patient.

---

# 7. Version 1.0 Out of Scope

Version 1.0 will not include:

* Real patient data
* Personally identifiable information
* Protected health information
* Hospital-system integration
* Electronic health-record integration
* FHIR integration
* Laboratory-system integration
* Automatic clinical-trial enrolment
* Automatic trial-site contact
* Medical diagnosis
* Treatment recommendations
* Final eligibility decisions
* Every medical condition
* Oncology trials
* Genomic or biomarker interpretation
* Complex clinical-note processing
* Production authentication
* Role-based access control
* A full public multi-user application
* Processing hundreds or thousands of patients
* Autonomous medical decision-making

These are deliberately excluded to keep Version 1 safe, testable, and achievable.

---

# 8. Version 1.1 — Batch Assessment

Version 1.1 may add support for multiple synthetic patients.

## Proposed Flow

```text
Patient Cohort
        ↓
Validate Patients
        ↓
Reuse Cached Trial Records
        ↓
Reuse Extracted Eligibility Criteria
        ↓
Evaluate Each Patient-Trial Combination
        ↓
Verify Results
        ↓
Store Structured Assessments
        ↓
Create Human Review Queue
```

## Version 1.1 Features

* Process 5–50 synthetic patients
* Batch-processing workflow
* Database persistence
* Reusable extracted trial criteria
* Assessment-status filtering
* Human-review queue
* Batch execution summary
* Processing and token-usage metrics

## Important Design Principle

Trial criteria must be extracted once and reused.

Bad design:

```text
Extract the same trial criteria separately for all 50 patients
```

Preferred design:

```text
Extract trial criteria once
        ↓
Store structured criteria
        ↓
Reuse for all patients
```

---

# 9. Version 2.0 — Coordinator Review Experience

Version 2.0 may introduce:

* Coordinator dashboard
* Patient and trial filters
* Assessment review screen
* Cohort-level summaries
* Conversational review assistant
* SQL-based exact queries
* Direct assessment retrieval
* RAG over trial text and approved reports

---

## Coordinator Chat Routing

```text
Coordinator Question
        ↓
Question Router
        │
        ├── Exact count, filter, or list
        │       ↓
        │     SQL Tool
        │
        ├── Known patient or trial ID
        │       ↓
        │     Direct Database Fetch
        │
        ├── Trial-text explanation
        │       ↓
        │     RAG Retrieval
        │
        └── Combined analytical question
                ↓
          SQL + RAG + LLM
```

Examples:

| Question                                  | Mechanism                        |
| ----------------------------------------- | -------------------------------- |
| How many patients are possible matches?   | SQL                              |
| Which patients are missing eGFR?          | SQL                              |
| Why was patient P-017 excluded?           | Direct assessment retrieval      |
| What does trial NCT123 say about insulin? | RAG                              |
| Summarize common exclusion reasons        | SQL aggregation plus LLM summary |

RAG will support review and explanation. It will not replace the structured eligibility-evaluation engine.

---

# 10. Data Storage Boundaries

## Relational Database

Structured information should be stored in a relational database:

* Patients
* Trials
* Eligibility criteria
* Criterion assessments
* Patient-trial assessments
* Verification results
* Missing information
* Audit logs

Version 1 may begin with SQLite.

---

## Vector Database

A vector database may later store approved unstructured content such as:

* Trial eligibility text
* Trial descriptions
* Protocol documents
* Approved report narratives
* Coordinator notes

A vector database should not be the primary source for exact values such as:

* Patient age
* BMI
* HbA1c
* Trial ID
* Assessment status
* Counts
* Missing fields

---

# 11. Safety Boundaries

The system must always follow these rules:

1. Missing patient information must not be treated as `MET`.
2. Every assessment must contain supporting evidence.
3. Inclusion and exclusion criteria must be handled separately.
4. Numeric and date calculations should use deterministic logic.
5. Agent iteration counts must be limited.
6. Unresolved contradictions must be escalated.
7. Final eligibility must remain a human decision.
8. Only synthetic patient data will be used in Version 1.
9. Reports must clearly state that they are preliminary.
10. The system must never provide treatment advice.

---

# 12. Version 1.0 Completion Criteria

Version 1.0 is complete when the system can:

* Accept a valid synthetic patient profile.
* Reject or report invalid patient data.
* Search ClinicalTrials.gov.
* Retrieve recruiting Type 2 Diabetes trials.
* Select a limited candidate set.
* Extract inclusion and exclusion criteria.
* Evaluate deterministic criteria correctly.
* Use controlled LLM evaluation for unresolved semantic criteria.
* Mark missing information as `UNKNOWN`.
* Attach patient and trial evidence.
* Verify preliminary results.
* Detect unsupported conclusions.
* Produce a structured pre-screening report.
* Route the result for human review.
* Complete the golden-dataset evaluation.
* Document known failures and limitations.
* Run from a clean development environment.
* Be published as Version 1.0 on GitHub.

---

# 13. Scope-Creep Rules

A new feature should not be added to Version 1 unless it is necessary to complete the core patient-to-report workflow.

Before adding any feature, ask:

```text
Does this feature help one synthetic patient receive
a correct, verified, evidence-backed pre-screening report?
```

If the answer is no, move it to a future-enhancements list.

Examples to postpone:

* Chat interface
* Batch processing
* FHIR
* Multiple diseases
* Mobile application
* More agents
* Complex frontend
* Cloud-scale infrastructure
* Real patient records

---

# 14. Scope Summary

```text
Version 1.0
One synthetic patient
Type 2 Diabetes
Up to three trials
Two meaningful agents
Verified report
Human review

Version 1.1
Multiple synthetic patients
Batch processing
Database persistence
Review queue

Version 2.0
Dashboard
Coordinator chat
SQL tools
Direct record retrieval
RAG explanations
```

The project will complete Version 1.0 before beginning Version 1.1 or Version 2.0.
