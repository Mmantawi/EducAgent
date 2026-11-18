# Knowledge graph AI component

This package provides the curriculum knowledge graph used by EducAgent's RAG,
tutoring, and evaluator agents.

## Contents

- `eduagent_kg/ingestion` and `eduagent_kg/parsing` turn textbook PDFs into structured sections.
- `eduagent_kg/extraction` creates typed concepts, skills, exercises, and relationships.
- `eduagent_kg/resolution` merges mentions into stable canonical graph entities.
- `eduagent_kg/validation` checks graph integrity and applies human review decisions.
- `eduagent_kg/storage` imports approved graph data into Neo4j.
- `eduagent_kg/queries` retrieves concepts, prerequisites, exercises, and source references.
- `eduagent_kg/pipeline` orchestrates the full multi-stage workflow.
- `eduagent_kg/schemas` defines the contracts shared between stages and agents.

The RAG agent should use approved graph context together with retrieved textbook
passages. Candidate, unreviewed, and rejected relationships must not be presented
as verified facts.

This is the graph engine copied from the standalone graph project. Integration
adapters that connect it to the rest of EducAgent should be added alongside this
package, without changing the core pipeline contracts.
