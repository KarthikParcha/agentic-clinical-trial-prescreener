"""Small asynchronous adapter for Groq chat completions."""

from groq import APIError, AsyncGroq

from clinical_trial_prescreener.config import GroqSettings


class GroqClientError(RuntimeError):
    """Raised when Groq cannot return usable generated content."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        error_code: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.error_code = error_code

    @property
    def is_json_generation_failure(self) -> bool:
        """Whether Groq rejected JSON-mode generation before returning content."""

        return self.status_code == 400 and self.error_code == "json_validate_failed"


class GroqClient:
    """Generate JSON-mode content without exposing Groq response objects."""

    def __init__(
        self,
        settings: GroqSettings | None = None,
        client: AsyncGroq | None = None,
    ) -> None:
        self._settings = settings or GroqSettings()  # type: ignore[call-arg]
        self._client = client or AsyncGroq(
            api_key=self._settings.api_key.get_secret_value()
        )

    async def generate(self, *, system_prompt: str, user_prompt: str) -> str:
        """Return one deterministic JSON-object-mode completion as text."""

        try:
            response = await self._client.chat.completions.create(
                model=self._settings.llm_model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0,
                response_format={"type": "json_object"},
            )
        except APIError as error:
            status_code, error_code = _error_metadata(error)
            raise GroqClientError(
                "Groq request failed",
                status_code=status_code,
                error_code=error_code,
            ) from error

        if not response.choices:
            raise GroqClientError("Groq returned no completion choices")
        content = response.choices[0].message.content
        if not isinstance(content, str) or not content.strip():
            raise GroqClientError("Groq returned no generated content")
        return content

    async def aclose(self) -> None:
        """Close the underlying asynchronous Groq client."""

        await self._client.close()


def _error_metadata(error: APIError) -> tuple[int | None, str | None]:
    """Extract safe transport metadata without retaining provider response text."""

    status_code = getattr(error, "status_code", None)
    body = getattr(error, "body", None)
    details = body.get("error") if isinstance(body, dict) else None
    error_code = details.get("code") if isinstance(details, dict) else None
    return (
        status_code if isinstance(status_code, int) else None,
        error_code if isinstance(error_code, str) else None,
    )
