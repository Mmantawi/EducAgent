from collections import defaultdict, deque

from eduagent_kg.schemas.documents import TextbookSection
from eduagent_kg.schemas.llm import SectionExtractionDraft

from .provider import ExtractionProviderError, ProviderResult


class MockExtractionProvider:
    """Deterministic provider supporting queued results and failures."""

    def __init__(self, responses: dict[str, list[SectionExtractionDraft | Exception]]) -> None:
        self._responses = defaultdict(deque, {key: deque(value) for key, value in responses.items()})
        self.calls: list[str] = []

    @property
    def provider_name(self) -> str:
        return "mock"

    @property
    def model_name(self) -> str:
        return "deterministic-v1"

    def extract(self, section: TextbookSection) -> ProviderResult:
        self.calls.append(section.section_id)
        if not self._responses[section.section_id]:
            raise ExtractionProviderError(f"No mock response configured for {section.section_id}")
        item = self._responses[section.section_id].popleft()
        if isinstance(item, Exception):
            raise item
        return ProviderResult(item, item.model_dump_json(), self.provider_name, self.model_name)
