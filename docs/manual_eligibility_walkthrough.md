# Manual Patient-to-Trial Eligibility Walkthrough

## Trial

NCT07438444

Population evaluated:

Type 2 Diabetes participants.

## Synthetic Patient

```text
Patient ID: DEMO-P001
Age: 48
Sex: Female
Country: India

Diagnosis: Type 2 Diabetes
Diagnosis Date: 2022-06-15

Insulin History: Never used insulin
HbA1c: 8.2%
BMI: 29.1 kg/m²

Type 1 Diabetes: No

Heart Attack Within 6 Months: No
Stroke Within 6 Months: No
Heart Failure Hospitalization Within 6 Months: Unknown

NYHA CHF Class: II

Morbid Obesity: No
Bariatric Surgery Planned: No
```

## Manual Assessment

| Criterion                                                  | Type      | Status  |
| ---------------------------------------------------------- | --------- | ------- |
| Type 2 Diabetes for at least 1 year                        | Inclusion | MET     |
| Insulin naive                                              | Inclusion | MET     |
| HbA1c between 7.5% and 10%                                 | Inclusion | MET     |
| BMI ≥23 kg/m²                                              | Inclusion | MET     |
| Type 1 Diabetes                                            | Exclusion | NOT_MET |
| Heart attack, stroke or HF hospitalization within 6 months | Exclusion | UNKNOWN |
| NYHA Class III/IV CHF                                      | Exclusion | NOT_MET |
| Morbid obesity with planned weight-loss procedure          | Exclusion | NOT_MET |

## Important Observation

Criterion status means whether the patient satisfies the criterion statement.

Therefore:

```text
INCLUSION + MET
→ Positive finding

INCLUSION + NOT_MET
→ Negative finding

EXCLUSION + MET
→ Exclusion triggered

EXCLUSION + NOT_MET
→ Exclusion not triggered
```

`UNKNOWN` means available patient evidence is insufficient to safely determine the result.

## Compound Criterion Example

```text
Heart attack within six months

OR

Stroke within six months

OR

Heart-failure hospitalization within six months
```

Patient evidence:

```text
False
OR
False
OR
Unknown
```

Result:

```text
UNKNOWN
```

Missing information must not be treated as evidence that the exclusion is absent.

## Safety Conclusion

The automated system must not return a final eligibility decision.

The patient has no currently known exclusion from the evaluated evidence, but one exclusion criterion contains missing information.

Human review remains required.
