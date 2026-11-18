from .schemas.enums import NodeType, RelationshipType

LEARNING_NODES = frozenset({NodeType.CONCEPT, NodeType.SKILL})
CONTENT_NODES = frozenset({NodeType.CONCEPT, NodeType.SKILL, NodeType.EXPERIMENT})
ALL_NODES = frozenset(NodeType)

# Each pair is (source types, target types). Direction is intentional.
RELATIONSHIP_RULES: dict[RelationshipType, tuple[frozenset[NodeType], frozenset[NodeType]]] = {
    RelationshipType.PREREQUISITE_FOR: (LEARNING_NODES, LEARNING_NODES),
    RelationshipType.IS_A: (frozenset({NodeType.CONCEPT, NodeType.SKILL}), frozenset({NodeType.CONCEPT, NodeType.SKILL})),
    RelationshipType.PART_OF: (
        frozenset({NodeType.CHAPTER, NodeType.LESSON, NodeType.SOURCE_SECTION, NodeType.EXERCISE, NodeType.EXPERIMENT}),
        frozenset({NodeType.BOOK, NodeType.CHAPTER, NodeType.LESSON, NodeType.SOURCE_SECTION}),
    ),
    RelationshipType.TEACHES: (frozenset({NodeType.LESSON, NodeType.SOURCE_SECTION}), LEARNING_NODES),
    RelationshipType.ASSESSES: (frozenset({NodeType.EXERCISE}), LEARNING_NODES),
    RelationshipType.DEMONSTRATES: (frozenset({NodeType.EXPERIMENT}), CONTENT_NODES),
    RelationshipType.SUPPORTED_BY: (ALL_NODES - {NodeType.SOURCE_SECTION}, frozenset({NodeType.SOURCE_SECTION})),
}


def relationship_is_allowed(
    relationship_type: RelationshipType, source_type: NodeType, target_type: NodeType
) -> bool:
    sources, targets = RELATIONSHIP_RULES[relationship_type]
    return source_type in sources and target_type in targets


def assert_relationship_allowed(
    relationship_type: RelationshipType, source_type: NodeType, target_type: NodeType
) -> None:
    if not relationship_is_allowed(relationship_type, source_type, target_type):
        raise ValueError(
            f"{relationship_type.value} does not allow {source_type.value} -> {target_type.value}"
        )

