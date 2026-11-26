"""Conservative entity resolution and hierarchical graph merging."""

from .merger import HierarchicalGraphMerger
from .normalization import normalize_text, terminology_key
from .resolver import EntityResolver

__all__ = [
    "EntityResolver", "HierarchicalGraphMerger", "normalize_text", "terminology_key",
]
