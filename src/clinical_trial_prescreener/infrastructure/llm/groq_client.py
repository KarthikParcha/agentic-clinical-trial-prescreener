"""Small asynchronous adapter for Groq chat completions."""

from groq import APIError, AsyncGroq

from clinical_trial_prescreener.config import GroqSettings


class GroqClientError(RuntimeError):
    """Raised when Groq cannot return usable generated content."""


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
            raise GroqClientError("Groq request failed") from error

        if not response.choices:
            raise GroqClientError("Groq returned no completion choices")
        content = response.choices[0].message.content
        if not isinstance(content, str) or not content.strip():
            raise GroqClientError("Groq returned no generated content")
        return content

    async def aclose(self) -> None:
        """Close the underlying asynchronous Groq client."""

        await self._client.close()
