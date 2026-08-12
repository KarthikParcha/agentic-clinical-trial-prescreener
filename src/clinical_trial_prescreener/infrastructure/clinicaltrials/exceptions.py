"""ClinicalTrials.gov client exceptions."""


class ClinicalTrialsClientError(RuntimeError):
    """Raised when ClinicalTrials.gov cannot provide a usable response."""
