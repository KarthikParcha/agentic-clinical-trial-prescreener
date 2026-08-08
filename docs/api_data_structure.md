# ClinicalTrials.gov API Data Structure

## Purpose

This document records the high-level ClinicalTrials.gov study fields required by Version 1.0.

Detailed API fields will be revisited during implementation.

## High-Level Structure

```text
ClinicalTrials.gov Study
        ↓
protocolSection
        │
        ├── identificationModule
        ├── statusModule
        ├── conditionsModule
        ├── designModule
        ├── armsInterventionsModule
        ├── eligibilityModule
        └── contactsLocationsModule
```

## Fields Important to Version 1

### Identification

```text
identificationModule

→ NCT ID
→ Brief title
→ Official title
```

Purpose:

Identify the trial uniquely.

### Status

```text
statusModule

→ Overall recruitment status
```

Version 1 primarily searches:

```text
RECRUITING
```

### Conditions

```text
conditionsModule

→ Conditions
```

Used to identify trials related to Type 2 Diabetes.

### Study Design

```text
designModule

→ Study type
→ Phase
```

Version 1 primarily uses:

```text
INTERVENTIONAL
```

### Interventions

```text
armsInterventionsModule

→ Intervention type
→ Intervention name
→ Intervention description
```

Provides information about the treatment or intervention being studied.

### Eligibility

```text
eligibilityModule

→ Minimum age
→ Maximum age
→ Sex
→ Eligibility criteria
```

This is the most important module for patient pre-screening.

The eligibility criteria text must later be converted into individual structured inclusion and exclusion criteria.

### Locations

```text
contactsLocationsModule

→ Facility
→ Site recruitment status
→ City
→ State
→ Country
```

Used to determine whether the study has an appropriate recruiting location.

## Application Boundary

The rest of the application should not depend directly on ClinicalTrials.gov JSON.

Use:

```text
ClinicalTrials.gov JSON
        ↓
Trial Normalizer
        ↓
Internal Trial Model
        ↓
Application
```

The internal model may eventually contain:

```text
trial_id
title
status
study_type
conditions
phase
interventions
minimum_age
maximum_age
sex
eligibility_text
locations
```

Detailed field mappings will be created when the API client and normalizer are implemented.

## What I Need to Remember

```text
Identification → Which trial?

Status         → Is it recruiting?

Condition      → What disease?

Design         → Interventional or observational?

Intervention   → What is being studied?

Eligibility    → Who can participate?

Location       → Where can they participate?
```

Eligibility is the most important module for the pre-screening workflow.
