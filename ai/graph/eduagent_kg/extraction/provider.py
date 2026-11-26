from abc import ABC, abstractmethod
from dataclasses import dataclass

from eduagent_kg.schemas.documents import TextbookSection
from eduagent_kg.schemas.llm import SectionExtractionDraft


class ExtractionProviderError(RuntimeError):
    """Base provider failure."""


class TransientProviderError(ExtractionProviderError):
    """A retryable network, quota, or service failure."""


class ModelOutputError(ExtractionProviderError):
    """The model refused or failed to provide schema-valid output."""

    def __init__(self, message: str, *, raw_text: str | None = None) -> None:
        super().__init__(message)
        self.raw_text = raw_text


@dataclass(frozen=True)
class ProviderResult:
    parsed: SectionExtractionDraft
    raw_text: str
    provider: str
    model: str
    warnings: tuple[str, ...] = ()  # items dropped while parsing the model output, and why


class ExtractionProvider(ABC):
    @property
    @abstractmethod
    def provider_name(self) -> str: ...

    @property
    @abstractmethod
    def model_name(self) -> str: ...

    @abstractmethod
    def extract(self, section: TextbookSection) -> ProviderResult: ...
