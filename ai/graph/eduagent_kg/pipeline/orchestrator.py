import json
import logging
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
from uuid import NAMESPACE_URL, uuid5

from eduagent_kg.extraction.runner import ExtractionRunner
from eduagent_kg.ingestion import IngestionService
from eduagent_kg.parsing import DocumentParser
from eduagent_kg.resolution.merger import HierarchicalGraphMerger, load_fragments
from eduagent_kg.schemas.documents import StructuredTextbook
from eduagent_kg.schemas.enums import ReviewStatus
from eduagent_kg.schemas.extraction_run import ExtractionRunReport
from eduagent_kg.schemas.pipeline import (
    PipelineBookInput, PipelineRunManifest, StageRecord, StageStatus,
)
from eduagent_kg.schemas.review import ReviewDecision, ReviewItem
from eduagent_kg.validation import GraphValidator, apply_review_decisions

LOGGER = logging.getLogger(__name__)


class PipelineOrchestrator:
    def __init__(
        self,
        *,
        parser_factory: Callable[[PipelineBookInput], DocumentParser],
        provider_factory: Callable[[StructuredTextbook], object],
        output_root: Path,
        graph_store=None,
        max_concurrency: int = 2,
        rate_limit_per_minute: int = 30,
        max_retries: int = 3,
    ) -> None:
        self.parser_factory = parser_factory
        self.provider_factory = provider_factory
        self.output_root = output_root
        self.graph_store = graph_store
        self.max_concurrency = max_concurrency
        self.rate_limit_per_minute = rate_limit_per_minute
        self.max_retries = max_retries

    def run(
        self,
        inputs: list[PipelineBookInput],
        *,
        decisions: list[ReviewDecision] | None = None,
        auto_import: bool = False,
        rerun_stages: set[str] | None = None,
    ) -> PipelineRunManifest:
        if not inputs:
            raise ValueError("At least one textbook input is required")
        rerun_stages = rerun_stages or set()
        run_id = f"pipeline:{uuid5(NAMESPACE_URL, '|'.join(sorted(item.document_id for item in inputs)))}"
        run_dir = self.output_root / _safe(run_id)
        manifest_path = run_dir / "pipeline-manifest.json"
        if manifest_path.is_file():
            manifest = PipelineRunManifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
            manifest.inputs = inputs
            manifest.completed_at = None
        else:
            manifest = PipelineRunManifest(run_id=run_id, inputs=inputs)
        manifest.status = StageStatus.RUNNING
        _write_model(manifest_path, manifest)

        datasets = []
        extraction_partial = False
        for book in inputs:
            parsed_stage = f"parsing:{book.document_id}"
            textbook_path = run_dir / "ingestions" / _safe(book.document_id) / "sections" / "textbook.json"
            try:
                self._start_stage(manifest, parsed_stage, manifest_path)
                if (
                    "parsing" not in rerun_stages and textbook_path.is_file()
                    and self._stage_status(manifest, parsed_stage) == StageStatus.RUNNING
                ):
                    textbook = StructuredTextbook.model_validate_json(textbook_path.read_text(encoding="utf-8"))
                    reused = True
                else:
                    result = IngestionService(
                        self.parser_factory(book), run_dir / "ingestions"
                    ).ingest(
                        Path(book.pdf_path), document_id=book.document_id, book_id=book.book_id,
                        title=book.title, grade=book.grade, subject=book.subject,
                        original_language=book.original_language, edition=book.edition,
                        force="parsing" in rerun_stages,
                    )
                    textbook = result.structured_textbook
                    reused = result.reused
                self._finish_stage(
                    manifest, parsed_stage, StageStatus.SUCCEEDED, manifest_path,
                    artifacts=[str(textbook_path)], message="reused" if reused else "parsed",
                )
            except Exception as exc:
                self._finish_stage(
                    manifest, parsed_stage, StageStatus.FAILED, manifest_path, message=str(exc)
                )
                return self._finish_run(manifest, StageStatus.FAILED, manifest_path)

            extraction_stage = f"extraction:{book.document_id}"
            try:
                self._start_stage(manifest, extraction_stage, manifest_path)
                report = ExtractionRunner(
                    self.provider_factory(textbook), run_dir / "extractions",
                    max_concurrency=self.max_concurrency,
                    rate_limit_per_minute=self.rate_limit_per_minute,
                    max_retries=self.max_retries,
                    backoff_seconds=0 if self.rate_limit_per_minute <= 0 else 1,
                ).run(
                    textbook_path, section_ids=set(book.section_ids) if book.section_ids else None,
                    force="extraction" in rerun_stages,
                )
                status = StageStatus.PARTIAL if report.failed else StageStatus.SUCCEEDED
                extraction_partial |= report.failed > 0
                fragment_dir = run_dir / "extractions" / _safe(book.document_id) / "fragments"
                fragments = load_fragments(fragment_dir)
                self._finish_stage(
                    manifest, extraction_stage, status, manifest_path,
                    artifacts=[str(fragment_dir), str(fragment_dir.parent / "run-report.json")],
                    message=f"{report.succeeded} succeeded, {report.failed} failed",
                )
                datasets.append((fragments, textbook))
            except Exception as exc:
                self._finish_stage(
                    manifest, extraction_stage, StageStatus.FAILED, manifest_path, message=str(exc)
                )
                extraction_partial = True

        if not datasets:
            return self._finish_run(manifest, StageStatus.FAILED, manifest_path)

        canonical_dir = run_dir / "canonical"
        graph_path = canonical_dir / "canonical-graph.json"
        queue_path = canonical_dir / "review-queue.json"
        report_path = canonical_dir / "validation-report.json"
        stats_path = canonical_dir / "merge-statistics.json"
        try:
            self._start_stage(manifest, "merge", manifest_path)
            graph, queue, stats = HierarchicalGraphMerger().merge_many(datasets)
            self._finish_stage(
                manifest, "merge", StageStatus.SUCCEEDED, manifest_path,
                artifacts=[str(graph_path), str(queue_path)],
            )
            self._start_stage(manifest, "validation", manifest_path)
            validation = GraphValidator().validate(graph)
            for issue in validation.issues:
                queue.items.append(ReviewItem(
                    review_id=f"review:validation:{issue.code}:{issue.target_id or 'graph'}",
                    category="validation_failure", target_id=issue.target_id or graph.graph_id,
                    reason=issue.message, payload=issue.model_dump(mode="json"),
                ))
            validation_status = StageStatus.SUCCEEDED if validation.is_valid else StageStatus.FAILED
            self._finish_stage(
                manifest, "validation", validation_status, manifest_path,
                artifacts=[str(report_path)],
            )
        except Exception as exc:
            self._finish_stage(manifest, "merge", StageStatus.FAILED, manifest_path, message=str(exc))
            return self._finish_run(manifest, StageStatus.FAILED, manifest_path)

        self._start_stage(manifest, "review", manifest_path)
        if decisions:
            graph, queue = apply_review_decisions(graph, queue, decisions)
            validation = GraphValidator().validate(graph)
        pending = [item for item in queue.items if item.status == ReviewStatus.CANDIDATE]
        review_status = StageStatus.AWAITING_REVIEW if pending else StageStatus.SUCCEEDED
        self._finish_stage(
            manifest, "review", review_status, manifest_path,
            artifacts=[str(queue_path)], message=f"{len(pending)} pending review items",
        )
        stats = stats.model_copy(update={
            "pending_reviews": len(pending),
            "approved_relationships": sum(
                edge.review_status == ReviewStatus.APPROVED for edge in graph.relationships
            ),
            "rejected_relationships": sum(
                edge.review_status == ReviewStatus.REJECTED for edge in graph.candidate_relationships
            ),
        })
        _write_model(graph_path, graph)
        _write_model(queue_path, queue)
        _write_model(report_path, validation)
        _write_model(stats_path, stats)

        import_stage = "import"
        if not auto_import:
            self._set_stage(
                manifest, import_stage, StageStatus.SKIPPED, manifest_path,
                message="Import was not requested.", artifacts=[],
            )
            final = StageStatus.AWAITING_REVIEW if pending else StageStatus.PARTIAL
            return self._finish_run(manifest, final, manifest_path)
        if pending or not validation.is_valid:
            message = "Import blocked by pending review." if pending else "Import blocked by validation failures."
            self._set_stage(
                manifest, import_stage, StageStatus.SKIPPED, manifest_path, message=message, artifacts=[]
            )
            final = StageStatus.AWAITING_REVIEW if pending else StageStatus.FAILED
            return self._finish_run(manifest, final, manifest_path)
        if self.graph_store is None:
            self._set_stage(
                manifest, import_stage, StageStatus.SKIPPED, manifest_path,
                message="Neo4j graph store is not configured.", artifacts=[],
            )
            return self._finish_run(manifest, StageStatus.PARTIAL, manifest_path)
        try:
            self._start_stage(manifest, import_stage, manifest_path)
            import_stats = self.graph_store.import_graph(graph)
            import_path = canonical_dir / "import-statistics.json"
            _write_model(import_path, import_stats)
            self._finish_stage(
                manifest, import_stage, StageStatus.SUCCEEDED, manifest_path,
                artifacts=[str(import_path)],
            )
        except Exception as exc:
            self._finish_stage(
                manifest, import_stage, StageStatus.FAILED, manifest_path, message=str(exc)
            )
            return self._finish_run(manifest, StageStatus.FAILED, manifest_path)
        final = StageStatus.PARTIAL if extraction_partial else StageStatus.SUCCEEDED
        return self._finish_run(manifest, final, manifest_path)

    def _start_stage(self, manifest, name, path):
        record = self._record(manifest, name)
        record.status = StageStatus.RUNNING
        record.started_at = datetime.now(timezone.utc)
        record.completed_at = None
        record.attempts += 1
        LOGGER.info("pipeline_stage_started", extra={"run_id": manifest.run_id, "stage": name})
        _write_model(path, manifest)

    def _finish_stage(self, manifest, name, status, path, *, artifacts=None, message=None):
        record = self._record(manifest, name)
        record.status = status
        record.completed_at = datetime.now(timezone.utc)
        record.artifacts = artifacts or record.artifacts
        record.message = message
        LOGGER.info(
            "pipeline_stage_finished",
            extra={"run_id": manifest.run_id, "stage": name, "status": status.value},
        )
        _write_model(path, manifest)

    def _set_stage(self, manifest, name, status, path, *, message, artifacts):
        record = self._record(manifest, name)
        record.status = status
        record.started_at = record.started_at or datetime.now(timezone.utc)
        record.completed_at = datetime.now(timezone.utc)
        record.message = message
        record.artifacts = artifacts
        _write_model(path, manifest)

    def _record(self, manifest, name):
        for record in manifest.stages:
            if record.stage == name:
                return record
        record = StageRecord(stage=name)
        manifest.stages.append(record)
        return record

    def _stage_status(self, manifest, name):
        return self._record(manifest, name).status

    def _finish_run(self, manifest, status, path):
        manifest.status = status
        manifest.completed_at = datetime.now(timezone.utc)
        _write_model(path, manifest)
        return manifest


def _safe(value: str) -> str:
    return "".join(char if char.isalnum() or char in "-_." else "_" for char in value)


def _write_model(path: Path, model) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent, text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(model.model_dump_json(indent=2) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise
