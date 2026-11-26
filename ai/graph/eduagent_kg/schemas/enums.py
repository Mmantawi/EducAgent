from enum import StrEnum


class NodeType(StrEnum):
    BOOK = "Book"
    CHAPTER = "Chapter"
    LESSON = "Lesson"
    SOURCE_SECTION = "SourceSection"
    CONCEPT = "Concept"
    SKILL = "Skill"
    EXERCISE = "Exercise"
    EXPERIMENT = "Experiment"


class RelationshipType(StrEnum):
    PREREQUISITE_FOR = "PREREQUISITE_FOR"
    IS_A = "IS_A"
    PART_OF = "PART_OF"
    TEACHES = "TEACHES"
    ASSESSES = "ASSESSES"
    DEMONSTRATES = "DEMONSTRATES"
    SUPPORTED_BY = "SUPPORTED_BY"
    # Knowledge-to-knowledge links between concepts and skills.
    USES = "USES"
    COMPONENT_OF = "COMPONENT_OF"
    INVERSE_OF = "INVERSE_OF"
    CONTRASTS_WITH = "CONTRASTS_WITH"
    RELATED_TO = "RELATED_TO"


class ReviewStatus(StrEnum):
    UNREVIEWED = "unreviewed"
    CANDIDATE = "candidate"
    APPROVED = "approved"
    REJECTED = "rejected"


class ClaimDisposition(StrEnum):
    EXTRACTED = "extracted"
    INFERRED = "inferred"
    REVIEWED = "reviewed"


class ExtractionMethod(StrEnum):
    PARSER = "parser"
    LLM = "llm"
    RULE = "rule"
    HUMAN = "human"


class BlockType(StrEnum):
    HEADING = "heading"
    PARAGRAPH = "paragraph"
    LIST = "list"
    TABLE = "table"
    IMAGE = "image"
    EQUATION = "equation"
    EXERCISE = "exercise"
    EXPERIMENT = "experiment"


class DecisionType(StrEnum):
    APPROVE = "approve"
    REJECT = "reject"
    DEFER = "defer"
    EDIT = "edit"


class Severity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class IngestionStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    SUCCEEDED = "succeeded"
    FAILED = "failed"

