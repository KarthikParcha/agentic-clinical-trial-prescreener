# Agentic Clinical Trial Pre-Screening Assistant

## 1. Business Problem

Clinical research coordinators and healthcare professionals spend significant time searching for suitable clinical trials and manually comparing patient information with complex trial eligibility criteria.

Clinical-trial records may contain long inclusion and exclusion sections involving:

* Age
* Diagnosis
* Laboratory values
* Medical history
* Current and previous medications
* Treatment history
* Pregnancy status
* Geographic location
* Previous clinical-trial participation

Manual pre-screening is time-consuming and can be difficult because patient information may be missing, eligibility criteria may be ambiguous, and exclusion criteria may be overlooked.

---

## 2. Target User

The primary user is a:

**Clinical Research Coordinator**

The secondary users may include:

* Clinicians
* Clinical-trial matching teams
* Research support staff

---

## 3. Current Manual Workflow

A clinical research coordinator currently performs the following steps:

1. Receives a patient profile.
2. Searches ClinicalTrials.gov using the patient’s condition and location.
3. Filters for recruiting interventional studies.
4. Opens individual clinical-trial records.
5. Reads the inclusion criteria.
6. Reads the exclusion criteria.
7. Compares every criterion with the available patient information.
8. Identifies criteria that are satisfied.
9. Identifies criteria that are not satisfied.
10. Identifies patient information that is missing.
11. Documents the preliminary findings.
12. Sends the result for clinician or trial-team review.

---

## 4. Version 1 Objective

Version 1 will accept a synthetic Type 2 Diabetes patient profile and a preferred location.

The system will:

1. Search for relevant recruiting clinical trials.
2. Retrieve a limited number of candidate trials.
3. Extract individual inclusion and exclusion criteria.
4. Compare each criterion with the patient profile.
5. Classify every criterion.
6. Identify missing patient information.
7. Verify the preliminary assessment.
8. Generate an evidence-backed pre-screening report.
9. Require human review before any final decision.

---

## 5. Criterion Statuses

Every eligibility criterion must receive one of the following statuses:

### MET

The available patient information clearly satisfies the criterion.

### NOT_MET

The available patient information clearly does not satisfy the criterion.

### UNKNOWN

The patient profile does not contain enough information to evaluate the criterion.

### NOT_APPLICABLE

The criterion does not apply to the patient or the current assessment.

Missing information must never be treated as `MET`.

---

## 6. High-Level System Flow

```text
Synthetic Patient Profile
        ↓
Validate Patient Information
        ↓
Search ClinicalTrials.gov
        ↓
Retrieve Candidate Trials
        ↓
Extract Eligibility Criteria
        ↓
Evaluate Criteria Against Patient Data
        ↓
Identify Missing Information
        ↓
Verify the Assessment
        ↓
Generate Pre-Screening Report
        ↓
Human Review
```

---

## 7. Example

### Patient Information

```text
Age: 48
Condition: Type 2 Diabetes
HbA1c: 8.2%
BMI: 29
Current Medication: Metformin
Country: India
```

### Trial Criterion

```text
Participants must be between 18 and 65 years old.
```

### Assessment

```text
Status: MET

Reason:
The patient is 48 years old and falls within the required age range.

Trial Evidence:
Participants must be between 18 and 65 years old.

Patient Evidence:
Patient age is 48.
```

### Missing-Information Example

Trial criterion:

```text
Participants must have an eGFR greater than 60 mL/min.
```

The patient profile does not contain an eGFR value.

Correct assessment:

```text
Status: UNKNOWN

Reason:
Kidney-function information is not available.

Missing Information:
Latest eGFR laboratory result.
```

---

## 8. In Scope for Version 1

* Synthetic patient profiles only
* Type 2 Diabetes
* Recruiting interventional clinical trials
* ClinicalTrials.gov as the trial-data source
* Country-based location filtering
* A maximum of five candidate trials
* Inclusion criteria
* Exclusion criteria
* Structured eligibility assessment
* Missing-information identification
* Verification
* Human review

---

## 9. Out of Scope for Version 1

* Real patient information
* Electronic health-record integration
* FHIR integration
* Final clinical-trial eligibility decisions
* Medical diagnosis
* Treatment recommendations
* Automatic enrolment
* Contacting clinical-trial sites
* Supporting every disease
* Complex oncology criteria
* Autonomous medical decision-making

---

## 10. Safety Boundary

The application is a:

**Clinical Trial Pre-Screening Assistant**

It is not a final eligibility-decision system.

The application must always communicate:

```text
This automated result is intended for preliminary screening only.
Final eligibility must be confirmed by qualified medical professionals
and the clinical-trial study team.
```

---

## 11. Success Definition

Version 1 will be considered successful when it can:

* Accept a validated synthetic patient profile.
* Find relevant recruiting Type 2 Diabetes trials.
* Extract inclusion and exclusion criteria.
* Evaluate supported numeric and factual criteria.
* Mark missing information as `UNKNOWN`.
* Attach trial evidence and patient evidence to assessments.
* Detect unsupported conclusions during verification.
* Produce a readable pre-screening report.
* Avoid making a final eligibility claim.

---

## 12. One-Sentence Problem Statement

> Given a synthetic Type 2 Diabetes patient profile and a preferred location, find relevant recruiting clinical trials, compare the available patient information against each trial’s eligibility criteria, identify met, unmet, and unknown criteria, and generate an evidence-backed pre-screening report for human review.
