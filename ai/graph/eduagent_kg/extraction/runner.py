import hashlib
import json
import logging
import os
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

from eduagent_kg.schemas.documents import StructuredTextbook, TextbookSection
from eduagent_kg.schemas.extraction import GraphFragment
from eduagent_kg.schemas.extraction_run import ExtractionRunReport, SectionExtractionResult
from eduagent_kg.schemas.llm import SectionExtractionDraft

from .assembler import GraphFragmentAssembler
from .prompt import PROMPT_VERSION, build_extraction_prompt
from .provider import ExtractionProvider, TransientProviderError

LOGGER = logging.getLogger(__name__)


class RateLimiter:
    def __init__(self, calls_per_minute: int) -> None:
        self.interval = 0 if calls_per_minute <= 0 else 60.0 / calls_per_minute
        self._lock = threading.Lock()
        self._next = 0.0

    def wait(self) -> None:
        if self.interval == 0:
            return
        with self._lock:
            now = time.monotonic()
            delay = max(0.0, self._next - now)
            self._next = max(now, self._next) + self.interval
        if delay:
            time.sleep(delay)


class ExtractionRunner:
    def __init__(
        self, provider: ExtractionProvider, output_root: Path, *, max_concurrency: int = 2,
        rate_limit_per_minute: int = 30, max_retries: int = 3,
        backoff_seconds: float = 1.0, sleeper=time.sleep,
    ) -> None:
        if max_concurrency < 1:
            raise ValueError("max_concurrency must be at least 1")
        self.provider = provider
        self.output_root = output_root
        self.max_concurrency = max_concurrency
        self.max_retries = max_retries
        self.backoff_seconds = backoff_seconds
        self.sleeper = sleeper
        self.limiter = RateLimiter(rate_limit_per_minute)
        self.assembler = GraphFragmentAssembler()

    def run(
        self, textbook_path: Path, *, max_sections: int | None = None,
        section_ids: set[str] | None = None, force: bool = False,
    ) -> ExtractionRunReport:
        textbook = StructuredTextbook.model_validate_json(textbook_path.read_text(encoding="utf-8"))
        sections = [
            section for section in textbook.sections
            if section_ids is None or section.section_id in section_ids
        ]
        sections = sections[:max_sections] if max_sections is not None else sections
        root = self.output_root / _safe(textbook.document_id)
        report = ExtractionRunReport(
            document_id=textbook.document_id,
            provider=self.provider.provider_name,
            model=self.provider.model_name,
        )
        results: dict[str, SectionExtractionResult] = {}
        with ThreadPoolExecutor(max_workers=self.max_concurrency) as pool:
            futures = {
                pool.submit(self._process_section, section, root, force): section.section_id
                for section in sections
            }
            for future in as_completed(futures):
                section_id = futures[future]
                try:
                    results[section_id] = future.result()
                except Exception as exc:
                    LOGGER.exception("Unexpected extraction failure for %s", section_id)
                    results[section_id] = SectionExtractionResult(
                        section_id=section_id, status="failed", attempts=0, error=str(exc)
                    )
        report.results = [results[section.section_id] for section in sections]
        report.completed_at = datetime.now(timezone.utc)
        _write_json(root / "run-report.json", report.model_dump(mode="json"))
        return report

    def _process_section(self, section: TextbookSection, root: Path, force: bool) -> SectionExtractionResult:
        cache_key = _cache_key(section, self.provider.provider_name, self.provider.model_name)
        fragment_path = root / "fragments" / f"{_safe(section.section_id)}.json"
        raw_path = root / "raw" / f"{_safe(section.section_id)}.json"
        cache_path = root / "cache" / f"{_safe(section.section_id)}.json"
        error_path = root / "errors" / f"{_safe(section.section_id)}.json"
        if not force and fragment_path.is_file() and cache_path.is_file():
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            if cached.get("cache_key") == cache_key:
                GraphFragment.model_validate_json(fragment_path.read_text(encoding="utf-8"))
                return SectionExtractionResult(
                    section_id=section.section_id, status="succeeded", attempts=0, cached=True,
                    fragment_path=str(fragment_path), raw_response_path=str(raw_path),
                )
        if not force and raw_path.is_file():
            try:
                raw_payload = json.loads(raw_path.read_text(encoding="utf-8"))
                # Reuse a saved model answer only if the same prompt/model/section produced it;
                # otherwise a prompt fix would silently keep serving the old answer.
                if isinstance(raw_payload.get("parsed"), dict) and raw_payload.get("cache_key") == cache_key:
                    draft = SectionExtractionDraft.model_validate(raw_payload["parsed"])
                    fragment = self.assembler.assemble(
                        section, draft, provider=self.provider.provider_name,
                        model=self.provider.model_name,
                        extra_warnings=raw_payload.get("parse_warnings") or (),
                    )
                    _write_json(fragment_path, fragment.model_dump(mode="json"))
                    _write_json(cache_path, {
                        "cache_key": cache_key, "prompt_version": PROMPT_VERSION,
                    })
                    if error_path.exists():
                        error_path.unlink()
                    return SectionExtractionResult(
                        section_id=section.section_id, status="succeeded", attempts=0,
                        cached=True, fragment_path=str(fragment_path),
                        raw_response_path=str(raw_path),
                    )
            except Exception:
                LOGGER.debug(
                    "Cached raw output remains invalid for %s", section.section_id,
                    exc_info=True,
                )

        attempts = 0
        try:
            while True:
                attempts += 1
                try:
                    self.limiter.wait()
                    provider_result = self.provider.extract(section)
                    break
                except TransientProviderError:
                    if attempts > self.max_retries:
                        raise
                    delay = self.backoff_seconds * (2 ** (attempts - 1))
                    LOGGER.warning(
                        "Transient extraction failure for %s; retrying in %.2fs",
                        section.section_id, delay,
                    )
                    self.sleeper(delay)
            _write_json(raw_path, {
                "section_id": section.section_id, "provider": provider_result.provider,
                "model": provider_result.model, "raw_text": provider_result.raw_text,
                "parsed": provider_result.parsed.model_dump(mode="json"),
                "parse_warnings": list(provider_result.warnings), "cache_key": cache_key,
            })
            fragment = self.assembler.assemble(
                section, provider_result.parsed,
                provider=provider_result.provider, model=provider_result.model,
                extra_warnings=provider_result.warnings,
            )
            _write_json(fragment_path, fragment.model_dump(mode="json"))
            _write_json(cache_path, {"cache_key": cache_key, "prompt_version": PROMPT_VERSION})
            if error_path.exists():
                error_path.unlink()
            return SectionExtractionResult(
                section_id=section.section_id, status="succeeded", attempts=attempts,
                fragment_path=str(fragment_path), raw_response_path=str(raw_path),
            )
        except Exception as exc:
            LOGGER.error("Section extraction failed for %s: %s", section.section_id, exc)
            raw_text = getattr(exc, "raw_text", None)
            if raw_text is not None and not raw_path.exists():
                _write_json(raw_path, {
                    "section_id": section.section_id, "provider": self.provider.provider_name,
                    "model": self.provider.model_name, "raw_text": raw_text,
                    "validation_error": str(exc),
                })
            _write_json(error_path, {
                "section_id": section.section_id, "attempts": attempts,
                "error_type": type(exc).__name__, "error": str(exc),
            })
            return SectionExtractionResult(
                section_id=section.section_id, status="failed", attempts=attempts,
                raw_response_path=str(raw_path) if raw_path.exists() else None,
                error_path=str(error_path), error=str(exc),
            )


def _cache_key(section: TextbookSection, provider: str, model: str) -> str:
    payload = "|".join((
        section.model_dump_json(), provider, model, PROMPT_VERSION,
        hashlib.sha256(build_extraction_prompt(section).encode("utf-8")).hexdigest(),
    ))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _safe(value: str) -> str:
    safe = "".join(char if char.isalnum() or char in "-_." else "_" for char in value)
    if not safe or safe in {".", ".."}:
        raise ValueError("identifier cannot be converted to a safe path")
    return safe


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent, text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise
