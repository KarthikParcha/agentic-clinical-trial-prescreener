# Clinical Trial Domain Glossary

## Purpose

This document contains only the clinical-trial terminology required to understand the Agentic Clinical Trial Pre-Screening Assistant.

Detailed terminology will be revisited during implementation.

## Core Terms

### Clinical Study

Research involving human participants.

### Interventional Study

A study in which participants are assigned to an intervention according to a study protocol.

Version 1 focuses on interventional studies.

### Observational Study

A study in which researchers observe participants without assigning the study intervention.

Observational studies are outside Version 1 scope.

### NCT ID

Unique identifier assigned to a study registered on ClinicalTrials.gov.

Example:

```text
NCT12345678
```

We will use the NCT ID as the primary external identifier for a trial.

### Recruitment Status

Indicates whether a study is currently recruiting participants.

Version 1 primarily searches:

```text
RECRUITING
```

### Eligibility Criteria

Requirements used to determine whether a person may participate in a clinical study.

Eligibility contains:

```text
Inclusion Criteria
+
Exclusion Criteria
```

### Inclusion Criteria

Requirements a participant must satisfy.

Example:

```text
Age between 18 and 65
HbA1c between 7% and 10%
Confirmed Type 2 Diabetes
```

### Exclusion Criteria

Conditions that may prevent participation.

Example:

```text
Pregnancy
Severe kidney disease
Recent cardiovascular event
Prohibited medication use
```

### Intervention

The treatment or action being evaluated by the study.

Examples:

* Drug
* Device
* Procedure
* Behavioral intervention
* Diet or exercise program

### Study Location

The facility and geographic location where the study is conducted.

Version 1 initially filters primarily by country.

### Sponsor

The organization or person responsible for initiating and managing the study.

### Investigator

A researcher involved in conducting the clinical study.

## Relationship to Our Application

```text
Patient
   ↓
Condition + Location
   ↓
Search RECRUITING
INTERVENTIONAL studies
   ↓
NCT IDs
   ↓
Eligibility Criteria
   ├── Inclusion
   └── Exclusion
   ↓
Patient-Criterion Evaluation
   ↓
Pre-Screening Assessment
```

## What I Need to Remember

```text
NCT ID          → Trial identifier

Recruiting      → Currently recruiting participants

Interventional  → Researchers assign an intervention

Inclusion       → Requirements for participation

Exclusion       → Reasons preventing participation

Eligibility     → Inclusion + Exclusion

Location        → Where the trial is conducted
```

Everything else can be revisited when needed.
