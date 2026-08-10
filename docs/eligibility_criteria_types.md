# Eligibility Criteria Types

## Purpose

Version 1 eligibility criteria are not evaluated using one universal approach.

Criteria should first be extracted from ClinicalTrials.gov text and classified according to the type of reasoning required.

## High-Level Flow

```text
Eligibility Criteria Text
        ↓
Criteria Extraction
        ↓
Structured Criteria
        ↓
Evaluation Strategy
        │
        ├── Deterministic Python
        ├── LLM-Assisted Evaluation
        └── Human Review
```

## Criterion Types

### Numeric

Examples:

```text
Age >= 18
BMI < 35
HbA1c between 7% and 10%
eGFR > 60
```

Preferred evaluation:

```text
Deterministic Python
```

### Boolean / Categorical

Examples:

```text
Pregnant
Currently taking insulin
Current smoker
Diagnosis of Type 2 Diabetes
```

Preferred evaluation:

```text
Deterministic Python
```

when reliable structured patient information exists.

### Temporal

Examples:

```text
No cardiovascular event in previous 6 months
No investigational medication in previous 90 days
Stable therapy for at least 12 weeks
```

Preferred evaluation:

```text
Extract date rule
        ↓
Python performs date calculation
```

Ambiguous terms such as:

```text
recent
long-term
significant duration
```

must not be assigned invented numerical meanings.

### Semantic

Examples:

```text
Severe mental illness
Clinically significant cardiovascular disease
Uncontrolled medical condition
Significant dementia
```

These may require:

```text
LLM-assisted interpretation
+
verification
+
human review when uncertain
```

## Extraction vs Evaluation

Extraction answers:

```text
What does the trial criterion require?
```

Evaluation answers:

```text
Does the patient satisfy that criterion?
```

These are separate responsibilities.

```text
Trial text
   ↓
Criteria Extractor
   ↓
Structured criterion
   ↓
Evaluator
   ↓
MET / NOT_MET / UNKNOWN / NOT_APPLICABLE
```

## Deterministic Rule Principle

When a criterion can reliably become:

```text
FIELD
+
OPERATOR
+
VALUE
```

prefer deterministic code.

Example:

```text
field = hba1c
operator = >
value = 8.0
unit = %
```

The LLM may extract this structure.

Python should perform the actual numeric comparison.

## Missing Evidence Principle

If required patient information is unavailable:

```text
UNKNOWN
```

Do not infer that the criterion is satisfied.

```text
No evidence
!=
Evidence of absence
```

## Compound Criteria

A single trial bullet may contain multiple requirements.

Example:

```text
Type 2 Diabetes with HbA1c > 8%
```

may contain:

```text
Diagnosis = Type 2 Diabetes
AND
HbA1c > 8%
```

The criteria extractor must eventually preserve these logical relationships.

## Version 1 Evaluation Strategy

```text
Numeric
→ Python

Simple categorical
→ Python

Date calculations
→ Python

Complex language
→ LLM-assisted

Missing or ambiguous evidence
→ UNKNOWN / HUMAN_REVIEW_REQUIRED
```
