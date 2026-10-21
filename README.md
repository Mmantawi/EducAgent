# EducAgent

> An AI-powered adaptive tutoring platform for Egyptian primary-school mathematics and social studies, with initial technical work focused on Grades 2–3 mathematics.

EducAgent is a graduation project designed to support students through interactive, curriculum-grounded learning sessions. It combines curriculum retrieval, educational agents, knowledge tracing, adaptive tutoring, and speech interaction while giving teachers and parents visibility into student progress.

> **Project status:** Architecture and research phase. The MVP boundaries and final implementation choices still require team approval.

## Intended users

- **Students** take interactive lessons, answer questions, receive scaffolded help, and follow an adaptive learning path.
- **Teachers and parents** review learning progress, skill mastery, session activity, and areas that need attention.
- **Administrators** manage curriculum content and trigger the ingestion pipeline that extracts skills, builds curriculum representations, and prepares retrieval data.

## Planned learning loop

1. An administrator uploads approved Egyptian mathematics curriculum material.
2. The ingestion pipeline extracts content and skills, builds a curriculum or knowledge representation, and creates searchable embeddings.
3. A student starts a text or voice learning session.
4. The tutoring system retrieves grounded curriculum context and guides the student without immediately revealing answers.
5. Evaluation and knowledge-tracing components update the estimated skill state.
6. The system chooses whether to continue, review, remediate, or reassess.
7. Teachers and parents see appropriate progress summaries.

The detailed flow and current assumptions are documented in [the system architecture](docs/architecture/system-overview.md).

## Repository structure

```text
EducAgent/
├── apps/                    # Student, teacher/parent, and admin applications
├── backend/
│   ├── api/                 # HTTP routes, controllers, and transport concerns
│   ├── core/                # Configuration, security, logging, and shared backend setup
│   ├── models/              # Persistence and domain models
│   ├── schemas/             # Validated request, response, and event contracts
│   ├── services/            # Application use cases and integrations
│   └── tests/               # Backend unit, integration, and contract tests
├── ai/                      # Agents, prompts, retrieval, knowledge tracing, and evaluation
├── docs/
│   ├── architecture/        # System diagrams and architecture decisions
│   ├── research/            # Synthesis, citations, and approved research sources
│   └── initial-issues.md    # Draft GitHub launch backlog
├── scripts/                 # Repeatable setup, validation, and maintenance tools
├── .github/
│   ├── workflows/           # Continuous-integration configuration
│   ├── ISSUE_TEMPLATE/      # Structured issue forms
│   └── pull_request_template.md
├── .gitignore
├── .env.example
├── README.md
└── CONTRIBUTING.md
```

## Research and architecture material

- [System architecture overview](docs/architecture/system-overview.md)
- [Architecture presentation](docs/architecture/educagent-two-stage-architecture.pptx)
- [Six-paper research synthesis](docs/research/educagent-six-paper-research-synthesis.docx)
- [Research source index](docs/research/README.md)

Five paper PDFs recovered from the project history are stored under `docs/research/papers/` for internal academic use in this private repository. Review their redistribution rights before changing the repository to public or sharing copies outside the team.

## Getting started

The runnable setup commands will be added after the team finalises the technology stack. Until then:

1. Clone the repository.
2. Copy `.env.example` to `.env`.
3. Pick or create a GitHub issue before making a change.
4. Create a focused branch from `main`.
5. Follow [CONTRIBUTING.md](CONTRIBUTING.md) when committing and opening a pull request.

Never commit API keys, private student data, or generated model files. Do not make included research PDFs public without confirming redistribution permission.

## Team workflow

- Keep `main` in a reviewable state.
- Track work in GitHub issues and link it from pull requests.
- Require at least one teammate review before merge.
- Record architecture decisions and research evidence under `docs/`.
- Keep large datasets, embeddings, model weights, and generated outputs outside Git.

## License

No software license has been selected yet. Until the team and supervisor choose one, treat the repository as all rights reserved.

## Suggested GitHub description

AI-powered adaptive tutoring platform for Egyptian primary-school mathematics and social studies, using curriculum-grounded agents, knowledge tracing, and personalised learning.

**Suggested topics:** `education`, `ai-agents`, `knowledge-tracing`, `personalized-learning`, `egypt`, `graduation-project`
