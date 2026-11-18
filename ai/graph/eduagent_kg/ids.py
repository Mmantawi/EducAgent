import re
import unicodedata
from uuid import UUID, uuid5

from .schemas.enums import NodeType

CANONICAL_NAMESPACE = UUID("71ae47f0-112d-4f54-bf0e-5c8fa508e181")
SOURCE_NAMESPACE = UUID("2aee5a75-2262-4ead-b769-2913e9223764")
SECTION_NAMESPACE = UUID("6fb659d7-d88d-4f79-bf42-3ff80175e4f1")
RELATIONSHIP_NAMESPACE = UUID("e45b2af6-8a65-4efd-b8d9-cbece370accc")


def normalize_identity(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).casefold().strip()
    return re.sub(r"\s+", " ", value)


def make_canonical_id(
    node_type: NodeType, *, book_id: str, identity: str, namespace: str = "eduagent"
) -> str:
    """Create a stable semantic UUID, independent of extraction ordering."""
    key = "|".join(
        (namespace, node_type.value, normalize_identity(book_id), normalize_identity(identity))
    )
    return f"{node_type.value.lower()}:{uuid5(CANONICAL_NAMESPACE, key)}"


def make_source_ref_id(
    *, book_id: str, section_id: str, page_start: int, page_end: int, evidence: str | None
) -> str:
    key = "|".join(
        (
            normalize_identity(book_id),
            normalize_identity(section_id),
            str(page_start),
            str(page_end),
            normalize_identity(evidence or ""),
        )
    )
    return f"source:{uuid5(SOURCE_NAMESPACE, key)}"


def make_section_id(document_id: str, heading_path: list[str], occurrence: int = 1) -> str:
    """Derive a stable section ID from durable document identity and heading hierarchy."""
    path = "/".join(normalize_identity(item) for item in heading_path)
    key = f"{normalize_identity(document_id)}|{path}|{occurrence}"
    return f"sec:{uuid5(SECTION_NAMESPACE, key)}"


def make_relationship_id(relationship_type: str, source_id: str, target_id: str) -> str:
    key = "|".join((relationship_type, source_id, target_id))
    return f"rel:{uuid5(RELATIONSHIP_NAMESPACE, key)}"

