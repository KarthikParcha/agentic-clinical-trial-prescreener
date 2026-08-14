"""Run the Version 1 trial search and print normalized candidate summaries."""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from clinical_trial_prescreener.domain.trial import ClinicalTrial
from clinical_trial_prescreener.infrastructure.clinicaltrials.client import (
    ClinicalTrialsClient,
)
from clinical_trial_prescreener.services.trial_search import (
    TrialSearchRequest,
    TrialSearchService,
)


async def main() -> None:
    """Search for Version 1 candidates and print concise summaries."""

    client = ClinicalTrialsClient()
    try:
        trials = await TrialSearchService(client).search(
            TrialSearchRequest(
                condition="Type 2 Diabetes",
                country="India",
                max_results=3,
            )
        )
    finally:
        await client.aclose()

    if not trials:
        print("No candidate trials found.")
        return

    for trial in trials:
        print_trial_summary(trial)


def print_trial_summary(trial: ClinicalTrial) -> None:
    """Print the normalized fields useful for a developer smoke check."""

    recruiting_india_locations = [
        location
        for location in trial.locations
        if location.country == "India" and location.status == "RECRUITING"
    ]
    interventions = ", ".join(intervention.name for intervention in trial.interventions)
    location_names = ", ".join(
        ", ".join(
            part for part in (location.facility, location.city, location.state) if part
        )
        or "Unnamed site"
        for location in recruiting_india_locations
    )

    print(f"NCT ID: {trial.trial_id}")
    print(f"Title: {trial.title}")
    print(f"Status: {trial.status.value}")
    print(f"Study type: {trial.study_type.value}")
    print(f"Conditions: {', '.join(trial.conditions) or 'None'}")
    print(f"Interventions: {interventions or 'None'}")
    print(f"Recruiting India locations: {location_names or 'None'}")
    print(f"Eligibility text available: {'Yes' if trial.eligibility_text else 'No'}")
    print()


if __name__ == "__main__":
    asyncio.run(main())
