from .schemas.enums import NodeType, RelationshipType

LEARNING_NODES = frozenset({NodeType.CONCEPT, NodeType.SKILL})
# Node types the LLM extracts into the knowledge graph. Exercises are kept out on purpose:
# they belong in a separate question bank that links to skills by canonical_id.
KNOWLEDGE_NODE_TYPES = LEARNING_NODES
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
    RelationshipType.USES: (LEARNING_NODES, LEARNING_NODES),
    RelationshipType.COMPONENT_OF: (LEARNING_NODES, LEARNING_NODES),
    RelationshipType.INVERSE_OF: (LEARNING_NODES, LEARNING_NODES),
    RelationshipType.CONTRASTS_WITH: (LEARNING_NODES, LEARNING_NODES),
    RelationshipType.RELATED_TO: (LEARNING_NODES, LEARNING_NODES),
}

# Links built from the parsed textbook layout by rules; the model never emits them.
STRUCTURAL_RELATIONSHIPS = frozenset({RelationshipType.PART_OF, RelationshipType.SUPPORTED_BY})
# Undirected links: stored once, with endpoints in a canonical order.
SYMMETRIC_RELATIONSHIPS = frozenset({
    RelationshipType.INVERSE_OF, RelationshipType.CONTRASTS_WITH, RelationshipType.RELATED_TO,
})
# Directed links that must never form a cycle.
ACYCLIC_RELATIONSHIPS = frozenset({
    RelationshipType.PREREQUISITE_FOR, RelationshipType.IS_A, RelationshipType.COMPONENT_OF,
})
# What each knowledge-to-knowledge link means; used in prompts and documentation.
RELATIONSHIP_MEANINGS: dict[RelationshipType, str] = {
    RelationshipType.PREREQUISITE_FOR: "A must be learned before B (A -> B).",
    RelationshipType.IS_A: "A is a kind of B (Second IS_A Unit of time).",
    RelationshipType.COMPONENT_OF: "A is a part, step or element of B (Dividend COMPONENT_OF Division; "
                                   "Regroup tens COMPONENT_OF Vertical subtraction).",
    RelationshipType.USES: "A applies or involves B (Divide with a remainder USES Remainder; "
                           "Commutative property USES Multiplicand).",
    RelationshipType.INVERSE_OF: "A undoes B (Multiplication INVERSE_OF Division). Undirected.",
    RelationshipType.CONTRASTS_WITH: "A and B are easily confused or compared (Remainder CONTRASTS_WITH "
                                     "Quotient). Undirected.",
    RelationshipType.RELATED_TO: "Any other meaningful link; the description must say what it is. "
                                 "Use only when no type above fits. Undirected.",
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

