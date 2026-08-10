# Clinical Trial Search Strategy

## Version 1 Goal

Find a small set of relevant candidate trials for detailed patient eligibility evaluation.

## Initial Search Constraints

```text
Condition:
Type 2 Diabetes

Study Type:
INTERVENTIONAL

Overall Status:
RECRUITING

Location:
Recruiting site in India
```

## Search Flow

```text
Patient Condition + Country
        ↓
ClinicalTrials.gov Search
        ↓
Relevant Candidate Trials
        ↓
Eligibility Evaluation
```

Search identifies candidate trials.

Search does not determine patient eligibility.

## Version 1 Search Expression

Conceptually:

```text
Type 2 Diabetes

AND

StudyType = INTERVENTIONAL

AND

OverallStatus = RECRUITING

AND

Location:
    Country = India
    Site Status = RECRUITING
```

## Location Rule

Overall study recruitment status and site recruitment status are different concepts.

A study may be recruiting globally while an India site is not recruiting.

Therefore, Version 1 should prefer trials with a recruiting site in India.

## Search vs Eligibility

### Search Filters

Use:

```text
Condition
Study type
Recruitment status
Country/site availability
```

### Eligibility Evaluation

Evaluate later:

```text
Age
Sex
BMI
HbA1c
Kidney function
Medication use
Pregnancy
Medical history
Treatment history
Other trial-specific criteria
```

Do not attempt to encode all eligibility criteria into the initial search query.

## Search Broadening

Version 1 initially uses deterministic search behavior.

If no trials are found, later versions may allow the Coordinator Agent to make controlled decisions such as:

```text
Retry
Broaden search
Ask for information
Stop
Escalate
```

## Engineering Boundary

```text
Coordinator Agent
      ↓
decides whether search is needed/retried

ClinicalTrials Search Tool
      ↓
executes the actual deterministic API request
```

The search API itself is a tool, not an autonomous agent.
