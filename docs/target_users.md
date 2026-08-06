# Target Users and User Needs

## 1. Primary User

The primary user of the Agentic Clinical Trial Pre-Screening Assistant is a:

**Clinical Research Coordinator**

A Clinical Research Coordinator may help identify potential clinical-trial participants, review study requirements, collect relevant information, and coordinate the screening process with clinicians and study teams.

The application supports the coordinator during preliminary screening. It does not replace the coordinator, clinician, investigator, or clinical-trial study team.

---

## 2. Secondary Users

Secondary users may include:

* Clinicians
* Research nurses
* Clinical-trial matching teams
* Study coordinators
* Research support staff
* Trial recruitment teams

These users may review the generated pre-screening report, provide missing information, and confirm whether further screening is appropriate.

---

## 3. User Goal

The user wants to identify potentially relevant clinical trials and understand how the available patient information compares with each trial’s eligibility criteria.

The user needs to know:

* Which trials may be relevant
* Which inclusion criteria are satisfied
* Which inclusion criteria are not satisfied
* Which exclusion criteria may apply
* Which criteria cannot be evaluated
* What patient information is missing
* What evidence supports each assessment
* Which findings require human review

---

## 4. Current Manual Process

A Clinical Research Coordinator may currently perform the following work:

1. Receive a patient profile.
2. Search ClinicalTrials.gov using the patient’s condition and location.
3. Filter for recruiting interventional studies.
4. Open several individual trial records.
5. Read the trial summary.
6. Read the inclusion criteria.
7. Read the exclusion criteria.
8. Compare each criterion with the available patient information.
9. Identify criteria that appear to be satisfied.
10. Identify criteria that appear not to be satisfied.
11. Identify patient information that is unavailable.
12. Document the preliminary findings.
13. Share the findings with a clinician or study team.
14. Confirm final eligibility through the official trial-screening process.

---

## 5. User Pain Points

### Time-Consuming Review

Trial eligibility sections may be long and contain many individual requirements.

Reviewing several trials for one patient may require reading and comparing a large amount of information.

### Complex Eligibility Language

Criteria may involve:

* Numeric ranges
* Medical terminology
* Previous treatments
* Current medications
* Laboratory results
* Date windows
* Diagnosis history
* Exclusion conditions
* Conditional requirements

### Missing Patient Information

The available patient profile may not contain every value required by the trial.

For example:

* eGFR
* Liver-function results
* Previous medication history
* Pregnancy status
* Recent hospitalizations
* Previous trial participation

Missing information must be identified clearly.

### Risk of Unsupported Assumptions

A user may accidentally interpret missing information as evidence that a criterion is satisfied.

The application must prevent this by classifying insufficient information as:

```text
UNKNOWN
```

### Risk of Missing Exclusion Criteria

A patient may satisfy several inclusion criteria but still meet an exclusion criterion.

The system must evaluate both inclusion and exclusion criteria.

### Difficult Documentation

The user needs to record:

* The criterion
* The assessment status
* The reason
* Trial evidence
* Patient evidence
* Missing information

Preparing this manually can be repetitive.

---

## 6. How the Application Helps

The application will assist the user by:

1. Searching for relevant recruiting trials.
2. Retrieving a limited list of candidate trials.
3. Extracting individual inclusion and exclusion criteria.
4. Comparing criteria with the synthetic patient profile.
5. Classifying each criterion as:

   * `MET`
   * `NOT_MET`
   * `UNKNOWN`
   * `NOT_APPLICABLE`
6. Identifying missing patient information.
7. Attaching trial evidence and patient evidence.
8. Verifying preliminary conclusions.
9. Generating a structured pre-screening report.
10. Requiring human review.

---

## 7. What the Application Will Not Do

The application will not:

* Make a final clinical-trial eligibility decision
* Diagnose a patient
* Recommend medical treatment
* Replace a clinician
* Replace the clinical-trial investigator
* Enrol a patient automatically
* Contact clinical-trial sites automatically
* Use real patient data during Version 1 development
* Assume that missing information satisfies a criterion

---

## 8. Expected User Outcome

After using the application, the user should receive a report containing:

```text
Patient Summary

Candidate Trial

Trial Recruitment Status

Criterion-by-Criterion Assessment

MET Criteria

NOT_MET Criteria

UNKNOWN Criteria

Possible Exclusion Criteria

Missing Patient Information

Trial Evidence

Patient Evidence

Verification Findings

Human Review Required
```

The report should help the user decide whether the patient should proceed to further human-led screening.

---

## 9. Example User Story

> As a Clinical Research Coordinator, I want to compare a synthetic Type 2 Diabetes patient profile against the eligibility criteria of recruiting clinical trials so that I can quickly identify possible matches, unmet criteria, and missing information before sending the case for human review.

---

## 10. Primary User Journey

```text
Coordinator receives patient profile
        ↓
Coordinator starts pre-screening
        ↓
System searches candidate trials
        ↓
System evaluates eligibility criteria
        ↓
System identifies missing information
        ↓
System verifies the assessment
        ↓
Coordinator reviews the report
        ↓
Clinician or study team performs final screening
```

---

## 11. User-Centred Success Criteria

The application is useful to the target user when:

* Relevant trials can be found quickly.
* Every assessment is linked to evidence.
* Missing information is clearly visible.
* Inclusion and exclusion criteria are evaluated separately.
* Unsupported conclusions are detected.
* The report is easy to review.
* The application never claims final eligibility.
* The user remains responsible for the final decision.
