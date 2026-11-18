from dataclasses import dataclass
from difflib import SequenceMatcher

from eduagent_kg.ids import make_canonical_id
from eduagent_kg.schemas.enums import NodeType, ReviewStatus
from eduagent_kg.schemas.extraction import ExtractedEntity
from eduagent_kg.schemas.graph import CanonicalEntity
from eduagent_kg.schemas.review import ReviewItem

from .normalization import identity_variants, normalize_text, terminology_key
from .semantic import SemanticCandidateProvider


@dataclass
class ResolutionResult:
    entities: list[CanonicalEntity]
    mention_to_canonical: dict[str, str]
    review_items: list[ReviewItem]
    confirmed_merges: int


class EntityResolver:
    def __init__(
        self, *, fuzzy_threshold: float = 0.88,
        semantic_provider: SemanticCandidateProvider | None = None,
    ) -> None:
        if not 0 <= fuzzy_threshold <= 1:
            raise ValueError("fuzzy_threshold must be between 0 and 1")
        self.fuzzy_threshold = fuzzy_threshold
        self.semantic_provider = semantic_provider

    def resolve(self, mentions: list[tuple[str, ExtractedEntity]]) -> ResolutionResult:
        canonicals: list[CanonicalEntity] = []
        variants_by_id: dict[str, set[str]] = {}
        mention_map: dict[str, str] = {}
        confirmed_merges = 0
        for mention_id, entity in mentions:
            variants = identity_variants(entity.name, entity.aliases)
            match = next(
                (
                    candidate for candidate in canonicals
                    if self._same_scope(candidate, entity)
                    and variants & variants_by_id[candidate.canonical_id]
                ),
                None,
            )
            if match is None:
                canonical_id = self._canonical_id(entity)
                match = CanonicalEntity(
                    canonical_id=canonical_id, node_type=entity.node_type,
                    name=entity.name.strip(), normalized_name=terminology_key(entity.name),
                    description=entity.description, aliases=sorted(set(entity.aliases)),
                    attributes=dict(entity.attributes), source_local_ids=[mention_id],
                    provenance=list(entity.provenance), grade=entity.extraction.grade,
                    subject=entity.extraction.subject,
                    original_language=entity.extraction.original_language,
                    review_status=ReviewStatus.UNREVIEWED,
                )
                canonicals.append(match)
                variants_by_id[canonical_id] = variants
            else:
                confirmed_merges += 1
                match.source_local_ids.append(mention_id)
                match.aliases = sorted(set(match.aliases + entity.aliases + [entity.name]))
                match.provenance = _unique_provenance(match.provenance + entity.provenance)
                variants_by_id[match.canonical_id].update(variants)
            mention_map[mention_id] = match.canonical_id

        review_items = self._fuzzy_candidates(canonicals)
        if self.semantic_provider:
            for item in self.semantic_provider.candidates(mentions):
                left = mention_map.get(item.left_mention_id)
                right = mention_map.get(item.right_mention_id)
                if left and right and left != right:
                    review_items.append(_merge_review_item(
                        left, right, "semantic_candidate", item.score, item.rationale
                    ))
        return ResolutionResult(canonicals, mention_map, _dedupe_reviews(review_items), confirmed_merges)

    def _same_scope(self, canonical: CanonicalEntity, entity: ExtractedEntity) -> bool:
        return (
            canonical.node_type == entity.node_type
            and normalize_text(canonical.subject) == normalize_text(entity.extraction.subject)
            and canonical.grade == entity.extraction.grade
        )

    def _canonical_id(self, entity: ExtractedEntity) -> str:
        if entity.node_type == NodeType.SOURCE_SECTION:
            identity = str(entity.attributes.get("section_id") or entity.name)
            scope = entity.provenance[0].document_id
        elif entity.node_type in {NodeType.BOOK, NodeType.CHAPTER, NodeType.LESSON}:
            identity = entity.name
            scope = entity.provenance[0].book_id
        elif entity.node_type in {NodeType.EXERCISE, NodeType.EXPERIMENT}:
            identity = f"{entity.provenance[0].section_id}|{terminology_key(entity.name)}"
            scope = entity.provenance[0].book_id
        else:
            identity = terminology_key(entity.name)
            scope = f"subject:{normalize_text(entity.extraction.subject)}:grade:{entity.extraction.grade}"
        return make_canonical_id(entity.node_type, book_id=scope, identity=identity)

    def _fuzzy_candidates(self, entities: list[CanonicalEntity]) -> list[ReviewItem]:
        items: list[ReviewItem] = []
        for index, left in enumerate(entities):
            for right in entities[index + 1:]:
                if (
                    left.node_type != right.node_type or left.subject != right.subject
                    or left.grade != right.grade
                ):
                    continue
                score = SequenceMatcher(None, left.normalized_name, right.normalized_name).ratio()
                if score >= self.fuzzy_threshold:
                    items.append(_merge_review_item(
                        left.canonical_id, right.canonical_id, "fuzzy_merge_candidate", score,
                        "Names are similar; similarity alone is insufficient to merge.",
                    ))
        return items


def _merge_review_item(left: str, right: str, category: str, score: float, reason: str) -> ReviewItem:
    pair = sorted((left, right))
    return ReviewItem(
        review_id=f"review:merge:{pair[0]}:{pair[1]}", category=category,
        target_id=f"{pair[0]}|{pair[1]}", reason=reason,
        payload={"left_canonical_id": pair[0], "right_canonical_id": pair[1], "score": score},
    )


def _unique_provenance(values):
    return list({item.source_ref_id: item for item in values}.values())


def _dedupe_reviews(items: list[ReviewItem]) -> list[ReviewItem]:
    return list({item.review_id: item for item in items}.values())
