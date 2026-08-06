# System Input Specification

## 1. Purpose

This document defines the information accepted by Version 1.0 of the Agentic Clinical Trial Pre-Screening Assistant.

The system accepts:

1. A synthetic patient profile
2. Trial search preferences

The patient profile is validated before trial searching or eligibility evaluation begins.

Version 1.0 will use synthetic patient data only.

---

# 2. Input Flow

```text
Synthetic Patient Data
        ↓
Schema Validation
        ↓
Data Normalization
        ↓
Missing-Information Detection
        ↓
Validated Patient Profile
        ↓
Trial Search Request
```

---

# 3. Required Patient Fields

The following fields are required to begin the Version 1 workflow.

| Field            | Type    | Example         | Validation                                   |
| ---------------- | ------- | --------------- | -------------------------------------------- |
| patient_id       | String  | DEMO-P001       | Must not be empty                            |
| age              | Integer | 48              | Must be greater than 0                       |
| sex              | Enum    | FEMALE          | Must use an allowed value                    |
| country          | String  | India           | Must not be empty                            |
| condition        | String  | Type 2 Diabetes | Version 1 supports Type 2 Diabetes           |
| consent_for_demo | Boolean | true            | Must be true for the synthetic demonstration |

These fields allow the system to validate the patient and create the initial trial-search request.

---

# 4. Optional Patient Fields

Optional fields may be needed when evaluating a particular trial.

A missing optional field must not stop the initial trial search.

If a trial criterion requires a missing field, the criterion must be classified as:

```text
UNKNOWN
```

---

## 4.1 Diagnosis Information

| Field                    | Type    | Example    | Notes                                 |
| ------------------------ | ------- | ---------- | ------------------------------------- |
| diagnosis_date           | Date    | 2021-04-10 | Optional                              |
| diagnosis_duration_years | Decimal | 5.3        | May be calculated from diagnosis date |
| diagnosis_status         | String  | Confirmed  | Optional for Version 1                |

The application should not ask an LLM to calculate diagnosis duration when it can be calculated using Python.

---

## 4.2 Physical Measurements

| Field  | Type    | Example | Unit  |
| ------ | ------- | ------- | ----- |
| height | Decimal | 170     | cm    |
| weight | Decimal | 84      | kg    |
| bmi    | Decimal | 29.1    | kg/m² |

BMI may either be:

* Supplied directly, or
* Calculated from height and weight

When both are present, the system may validate whether they are consistent.

---

## 4.3 Laboratory Results

Laboratory values should not be represented as unstructured sentences.

Each laboratory result should include:

| Field           | Type    | Example    |
| --------------- | ------- | ---------- |
| test_name       | String  | HbA1c      |
| value           | Decimal | 8.2        |
| unit            | String  | %          |
| measured_date   | Date    | 2026-07-15 |
| reference_range | String  | Optional   |

Initial laboratory tests may include:

* HbA1c
* eGFR
* Serum creatinine
* ALT
* AST

Version 1 does not need to support every laboratory test.

---

## 4.4 Medication Information

Each medication record may contain:

| Field           | Type   | Example     |
| --------------- | ------ | ----------- |
| medication_name | String | Metformin   |
| status          | Enum   | CURRENT     |
| start_date      | Date   | 2024-01-10  |
| end_date        | Date   | Optional    |
| dosage          | String | 500 mg      |
| frequency       | String | Twice daily |

Possible medication statuses:

```text
CURRENT
PREVIOUS
DISCONTINUED
UNKNOWN
```

Version 1 may initially evaluate only a limited set of medication-related criteria.

---

## 4.5 Medical History

Medical history may contain structured conditions such as:

| Field          | Type   | Example      |
| -------------- | ------ | ------------ |
| condition_name | String | Hypertension |
| status         | Enum   | ACTIVE       |
| diagnosis_date | Date   | Optional     |
| resolved_date  | Date   | Optional     |
| notes          | String | Optional     |

Possible statuses:

```text
ACTIVE
RESOLVED
UNKNOWN
```

The system must not assume that an unlisted medical condition is absent.

For example:

```text
No kidney disease present in the input
```

does not automatically mean:

```text
Patient has no kidney disease
```

It may mean the information was not provided.

---

## 4.6 Pregnancy Information

Possible fields:

| Field                | Type | Example           |
| -------------------- | ---- | ----------------- |
| pregnancy_status     | Enum | NOT_PREGNANT      |
| breastfeeding_status | Enum | NOT_BREASTFEEDING |
| pregnancy_test_date  | Date | Optional          |

Allowed pregnancy statuses may include:

```text
PREGNANT
NOT_PREGNANT
NOT_APPLICABLE
UNKNOWN
```

Missing pregnancy information must remain `UNKNOWN` when a trial requires it.

---

## 4.7 Previous Clinical-Trial Participation

| Field                     | Type            | Example  |
| ------------------------- | --------------- | -------- |
| currently_in_trial        | Boolean or null | false    |
| previous_trial_id         | String          | Optional |
| participation_end_date    | Date            | Optional |
| investigational_drug_date | Date            | Optional |

A missing value must not automatically be treated as `false`.

---

# 5. Trial Search Input

The system will create a structured trial-search request.

| Field                 | Type    | Default         | Notes                       |
| --------------------- | ------- | --------------- | --------------------------- |
| condition             | String  | Type 2 Diabetes | Required                    |
| country               | String  | Patient country | Required                    |
| recruitment_status    | Enum    | RECRUITING      | Version 1 default           |
| study_type            | Enum    | INTERVENTIONAL  | Version 1 default           |
| maximum_results       | Integer | 3               | Maximum 5 during evaluation |
| include_remote_trials | Boolean | false           | Future option               |

Example:

```json
{
  "condition": "Type 2 Diabetes",
  "country": "India",
  "recruitment_status": "RECRUITING",
  "study_type": "INTERVENTIONAL",
  "maximum_results": 3
}
```

---

# 6. Example Synthetic Patient Input

```json
{
  "patient_id": "DEMO-P001",
  "age": 48,
  "sex": "FEMALE",
  "country": "India",
  "condition": "Type 2 Diabetes",
  "consent_for_demo": true,
  "diagnosis_date": "2021-04-10",
  "diagnosis_duration_years": 5.3,
  "height": {
    "value": 170,
    "unit": "cm"
  },
  "weight": {
    "value": 84,
    "unit": "kg"
  },
  "bmi": {
    "value": 29.1,
    "unit": "kg/m2"
  },
  "laboratory_results": [
    {
      "test_name": "HbA1c",
      "value": 8.2,
      "unit": "%",
      "measured_date": "2026-07-15"
    }
  ],
  "medications": [
    {
      "medication_name": "Metformin",
      "status": "CURRENT",
      "start_date": "2024-01-10",
      "dosage": "500 mg",
      "frequency": "Twice daily"
    }
  ],
  "medical_history": [
    {
      "condition_name": "Hypertension",
      "status": "ACTIVE"
    }
  ],
  "pregnancy_status": "UNKNOWN",
  "currently_in_trial": null
}
```

---

# 7. Missing-Information Rules

The system must distinguish between:

```text
False
Zero
Not applicable
Unknown
Not provided
```

These values must not be treated as equivalent.

Example:

```text
currently_in_trial = false
```

means the patient is confirmed not to be participating in another trial.

```text
currently_in_trial = null
```

means the information is unavailable.

When required information is unavailable:

```text
Criterion status = UNKNOWN
```

---

# 8. Validation Rules

Version 1 should validate at least the following:

* Patient ID is present
* Age is greater than zero
* Country is present
* Condition is Type 2 Diabetes
* Maximum trial results are between 1 and 5
* Numeric values contain valid units
* Laboratory results contain measurement dates when available
* Medication start dates are not after end dates
* Future dates are rejected where inappropriate
* Enum fields use approved values
* Missing values remain explicitly missing
* No real patient-identifying information is used

---

# 9. Normalization Rules

The system should normalize:

* Sex values into a controlled enum
* Country names into a consistent format
* Medication names where practical
* Laboratory test names
* Units
* Dates
* Boolean and unknown values

Example:

```text
Female
female
F
```

should be converted into one internal value:

```text
FEMALE
```

Normalization must occur before eligibility evaluation.

---

# 10. What the LLM Should Not Do

The LLM should not be responsible for:

* Calculating age
* Calculating BMI
* Converting dates
* Comparing numeric ranges
* Deciding whether required fields are present
* Guessing missing medical information
* Correcting invalid patient data silently

These responsibilities belong to deterministic validation and Python utilities.

---

# 11. Version 1 Input Boundary

Version 1 accepts:

```text
One synthetic patient profile
+
One trial-search request
```

Version 1 does not accept:

* Real patient records
* Medical documents
* Scanned reports
* Hospital files
* FHIR resources
* Free-form clinical notes
* Batch uploads
* Fifty-patient files

Batch patient input belongs to Version 1.1.

---

# 12. Input Success Criteria

The input layer is successful when:

* A valid synthetic patient profile is accepted.
* Invalid required values are rejected.
* Optional missing values remain explicit.
* Units and dates are preserved.
* Search parameters can be created from the validated profile.
* No medical assumptions are introduced.
* Missing data can later produce an `UNKNOWN` assessment.
