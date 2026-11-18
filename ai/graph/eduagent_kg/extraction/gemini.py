from eduagent_kg.schemas.documents import TextbookSection
from eduagent_kg.schemas.llm import SectionExtractionDraft

from .prompt import build_extraction_prompt
from .provider import ModelOutputError, ProviderResult, TransientProviderError


class GeminiExtractionProvider:
    def __init__(self, *, api_key: str, model: str = "gemini-2.5-flash") -> None:
        if not api_key:
            raise ValueError("Gemini API key is required")
        try:
            from google import genai
            from google.genai import types
        except ImportError as exc:
            raise RuntimeError(
                "Google GenAI SDK is not installed; install the `gemini` project extra"
            ) from exc
        self._types = types
        self._client = genai.Client(api_key=api_key)
        self._model = model

    @property
    def provider_name(self) -> str:
        return "google-genai"

    @property
    def model_name(self) -> str:
        return self._model

    def extract(self, section: TextbookSection) -> ProviderResult:
        try:
            response = self._client.models.generate_content(
                model=self._model,
                contents=build_extraction_prompt(section),
                config=self._types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_json_schema=SectionExtractionDraft.model_json_schema(),
                    temperature=0,
                ),
            )
        except Exception as exc:
            if _is_transient(exc):
                raise TransientProviderError(str(exc)) from exc
            raise ModelOutputError(f"Gemini request failed: {exc}") from exc
        parsed = getattr(response, "parsed", None)
        raw_text = getattr(response, "text", None) or ""
        if parsed is None:
            raise ModelOutputError(
                "Gemini returned no parsed structured output (possibly refused)", raw_text=raw_text
            )
        try:
            validated = parsed if isinstance(parsed, SectionExtractionDraft) else SectionExtractionDraft.model_validate(parsed)
        except Exception as exc:
            raise ModelOutputError(
                f"Gemini structured output failed validation: {exc}", raw_text=raw_text
            ) from exc
        return ProviderResult(validated, raw_text, self.provider_name, self.model_name)


def _is_transient(exc: Exception) -> bool:
    status = getattr(exc, "status_code", None) or getattr(exc, "code", None)
    if status in {408, 409, 429, 500, 502, 503, 504}:
        return True
    name = type(exc).__name__.casefold()
    return any(token in name for token in ("timeout", "tempor", "rate", "unavailable"))
