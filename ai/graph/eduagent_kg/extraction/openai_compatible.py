"""Extraction through any OpenAI-compatible chat endpoint.

Works with a llama.cpp or vLLM server (local, Kaggle, rented GPU), Ollama, and hosted
providers such as OpenRouter, so the same pipeline runs wherever the model lives.
"""

import json
import logging
import re

from pydantic import ValidationError

from eduagent_kg.ontology import KNOWLEDGE_NODE_TYPES
from eduagent_kg.schemas.documents import TextbookSection
from eduagent_kg.schemas.llm import DraftEntity, DraftRelationship, SectionExtractionDraft

from .prompt import GLEANING_PROMPT, SECTION_RELATIONSHIP_TYPES, build_extraction_prompt
from .provider import (
    ExtractionProvider, ModelOutputError, ProviderResult, TransientProviderError,
)

LOGGER = logging.getLogger(__name__)
THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)
FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$")


class OpenAICompatibleExtractionProvider(ExtractionProvider):
    def __init__(
        self, *, base_url: str, model: str, api_key: str | None = None,
        max_tokens: int = 6000, temperature: float = 0.0, timeout: float = 300.0,
        structured_output: bool = True, disable_thinking: bool = True, gleanings: int = 1,
    ) -> None:
        try:
            from openai import OpenAI
        except ImportError as exc:  # pragma: no cover - depends on the environment
            raise RuntimeError("The `openai` package is required for this provider") from exc
        self._client = OpenAI(
            base_url=base_url, api_key=api_key or "not-needed", timeout=timeout, max_retries=0,
        )
        self._model = model
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.structured_output = structured_output
        self.disable_thinking = disable_thinking
        if gleanings < 0:
            raise ValueError("gleanings must be >= 0")
        self.gleanings = gleanings

    @property
    def provider_name(self) -> str:
        return "openai-compatible"

    @property
    def model_name(self) -> str:
        return self._model

    def extract(self, section: TextbookSection) -> ProviderResult:
        """One extraction call, then up to ``gleanings`` "what did you miss?" rounds (GraphRAG A.2)."""
        messages = [
            {"role": "system", "content": "You return only JSON that matches the requested schema."},
            {"role": "user", "content": build_extraction_prompt(section)},
        ]
        raw_text = self._chat(messages, allow_truncated=False)
        warnings: list[str] = []
        draft = parse_draft(raw_text, warnings)
        raw_rounds = [raw_text]
        for round_number in range(1, self.gleanings + 1):
            messages += [
                {"role": "assistant", "content": raw_text},
                {"role": "user", "content": GLEANING_PROMPT},
            ]
            round_warnings: list[str] = []
            try:
                raw_text = self._chat(messages, allow_truncated=False)
                extra = parse_draft(raw_text, round_warnings)
            except ModelOutputError as exc:
                warnings.append(f"Gleaning round {round_number} discarded: {exc}")
                break
            warnings.extend(f"Gleaning round {round_number}: {w}" for w in round_warnings)
            raw_rounds.append(raw_text)
            added = merge_drafts(draft, extra)
            if not added:
                break  # the model reports nothing missing
        return ProviderResult(
            draft, "\n\n".join(raw_rounds), self.provider_name, self._model, tuple(warnings)
        )

    def _chat(self, messages: list[dict], *, allow_truncated: bool) -> str:
        from openai import APIConnectionError, APIStatusError, APITimeoutError

        kwargs: dict = {}
        if self.structured_output:
            kwargs["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": "SectionExtractionDraft",
                    "schema": draft_json_schema(),
                },
            }
        if self.disable_thinking:
            # Qwen3-style models: skip the hidden reasoning that otherwise eats the output budget.
            kwargs["extra_body"] = {"chat_template_kwargs": {"enable_thinking": False}}
        try:
            response = self._client.chat.completions.create(
                model=self._model,
                messages=messages,
                max_tokens=self.max_tokens,
                temperature=self.temperature,
                **kwargs,
            )
        except (APIConnectionError, APITimeoutError) as exc:
            raise TransientProviderError(f"Model server unreachable: {exc}") from exc
        except APIStatusError as exc:
            if exc.status_code in (408, 409, 429) or exc.status_code >= 500:
                raise TransientProviderError(f"Model server error {exc.status_code}") from exc
            raise ModelOutputError(f"Model request rejected ({exc.status_code}): {exc}") from exc

        choice = response.choices[0]
        raw_text = choice.message.content or ""
        if choice.finish_reason == "length" and not allow_truncated:
            raise ModelOutputError(
                f"Output hit max_tokens={self.max_tokens} and was cut off", raw_text=raw_text
            )
        return raw_text


def merge_drafts(base: SectionExtractionDraft, extra: SectionExtractionDraft) -> int:
    """Add gleaned items to ``base``; returns how many new items were added."""
    names = {(e.node_type, e.name.strip().casefold()): e.local_id for e in base.entities}
    ids = {e.local_id for e in base.entities}
    renamed: dict[str, str] = {}
    added = 0
    for entity in extra.entities:
        key = (entity.node_type, entity.name.strip().casefold())
        if key in names:  # the model repeated a node it already gave
            renamed[entity.local_id] = names[key]
            continue
        local_id = entity.local_id
        while local_id in ids:
            local_id += "_2"
        renamed[entity.local_id] = local_id
        base.entities.append(entity.model_copy(update={"local_id": local_id}))
        names[key] = local_id
        ids.add(local_id)
        added += 1
    existing = {(r.relationship_type, r.source_local_id, r.target_local_id) for r in base.relationships}
    rel_ids = {r.local_id for r in base.relationships}
    for relationship in extra.relationships:
        source = renamed.get(relationship.source_local_id, relationship.source_local_id)
        target = renamed.get(relationship.target_local_id, relationship.target_local_id)
        key = (relationship.relationship_type, source, target)
        if key in existing or source == target:
            continue
        local_id = relationship.local_id
        while local_id in rel_ids:
            local_id += "_2"
        base.relationships.append(relationship.model_copy(update={
            "local_id": local_id, "source_local_id": source, "target_local_id": target,
        }))
        existing.add(key)
        rel_ids.add(local_id)
        added += 1
    return added


def draft_json_schema() -> dict:
    """The response schema sent to the server, narrowed to the node types the graph keeps."""
    schema = SectionExtractionDraft.model_json_schema()
    allowed = sorted(node_type.value for node_type in KNOWLEDGE_NODE_TYPES)
    defs = schema["$defs"]
    # Every field the model must fill in is REQUIRED: with constrained decoding, an optional
    # field is one the model may silently skip (the first Kaggle run skipped `entities`).
    entity = defs["DraftEntity"]["properties"]
    entity["node_type"] = {"type": "string", "enum": allowed}
    entity["description"] = {"type": "string"}
    defs["DraftEntity"]["required"] = ["local_id", "node_type", "name", "description", "evidence_text"]
    relationship = defs["DraftRelationship"]["properties"]
    relationship["description"] = {"type": "string"}
    relationship["strength"] = {"type": "integer", "minimum": 1, "maximum": 10}
    # Use "" when a field does not apply (no quote for an inferred link, no rationale for a quoted one).
    relationship["evidence_text"] = {"type": "string"}
    relationship["rationale"] = {"type": "string"}
    defs["DraftRelationship"]["required"] = [
        "local_id", "relationship_type", "source_local_id", "target_local_id",
        "description", "strength", "inferred", "evidence_text", "rationale",
    ]
    defs["RelationshipType"]["enum"] = [kind.value for kind in SECTION_RELATIONSHIP_TYPES]
    schema["required"] = ["entities", "relationships"]
    return schema


def _normalize_relationship(item: dict, warnings: list[str]) -> dict:
    item = dict(item)
    for key in ("evidence_text", "rationale", "description"):
        if isinstance(item.get(key), str) and not item[key].strip():
            item[key] = None
    if not item.get("inferred") and not item.get("evidence_text") and item.get("rationale"):
        item["inferred"] = True
        warnings.append(f"Relationship {item.get('local_id')} had a rationale but no quote; kept as inferred")
    return item


def _first_error(exc: ValidationError) -> str:
    error = exc.errors()[0]
    location = ".".join(str(part) for part in error.get("loc", ())) or "item"
    return f"{location}: {error.get('msg')}"


def parse_draft(raw_text: str, warnings: list[str] | None = None) -> SectionExtractionDraft:
    """Parse model JSON, keeping every valid item and dropping only the invalid ones.

    Each dropped item is described in ``warnings`` (when given) so it ends up in the fragment.
    """
    warnings = warnings if warnings is not None else []
    text = FENCE_RE.sub("", THINK_RE.sub("", raw_text).strip()).strip()
    if not text:
        raise ModelOutputError("Model returned an empty response", raw_text=raw_text)
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ModelOutputError(f"Model output is not valid JSON: {exc}", raw_text=raw_text) from exc
    if not isinstance(payload, dict):
        raise ModelOutputError("Model output is not a JSON object", raw_text=raw_text)
    if "entities" not in payload:
        warnings.append("Model output has no `entities` list")
    entities, relationships = [], []
    for item in payload.get("entities") or []:
        try:
            entities.append(DraftEntity.model_validate(item))
        except ValidationError as exc:
            local_id = item.get("local_id") if isinstance(item, dict) else None
            warnings.append(f"Dropped entity {local_id}: {_first_error(exc)}")
    for item in payload.get("relationships") or []:
        if not isinstance(item, dict):
            warnings.append("Dropped relationship: not a JSON object")
            continue
        try:
            relationships.append(DraftRelationship.model_validate(_normalize_relationship(item, warnings)))
        except ValidationError as exc:
            warnings.append(f"Dropped relationship {item.get('local_id')}: {_first_error(exc)}")
    if warnings:
        LOGGER.info("Model output issues: %s", "; ".join(warnings))
    return SectionExtractionDraft(entities=entities, relationships=relationships)
