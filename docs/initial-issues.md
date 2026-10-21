# Initial GitHub issue backlog

These are draft issues to create after the repository is published. Create them in the suggested order, assign owners during planning, and adjust wording to match the approved project proposal.

## Suggested labels

`priority:critical`, `priority:high`, `priority:medium`, `area:product`, `area:architecture`, `area:frontend`, `area:backend`, `area:ai`, `area:data`, `area:research`, `area:devops`, `documentation`, `decision`, `blocked`, `good-first-issue`

## Foundation milestone

### 1. Define the problem statement and target users

**Labels:** `area:product`, `priority:critical`, `decision`

**Outcome:** One approved problem statement identifies primary users, their main pain point, the project value, and explicit non-goals.

**Acceptance criteria:**

- [ ] Primary and secondary users are named.
- [ ] The core educational problem is supported by initial evidence.
- [ ] Project goals, non-goals, and constraints are documented.
- [ ] The supervisor and team approve the statement.

### 2. Define the MVP and success metrics

**Labels:** `area:product`, `priority:critical`, `decision`

**Depends on:** Issue 1

**Acceptance criteria:**

- [ ] The primary end-to-end user journey is written.
- [ ] Must-have and later features are separated.
- [ ] Measurable product, model, and research success criteria are recorded.
- [ ] Risks and scope exclusions are explicit.

### 3. Select and document the technology stack

**Labels:** `area:architecture`, `priority:critical`, `decision`

**Depends on:** Issue 2

**Acceptance criteria:**

- [ ] Frontend, backend, database, AI provider, test tools, and hosting options are compared.
- [ ] Selection criteria include team skills, cost, privacy, latency, and deployment limits.
- [ ] The decision is recorded in `docs/architecture/`.
- [ ] README setup instructions are updated.

### 4. Create the system architecture and agent boundaries

**Labels:** `area:architecture`, `area:ai`, `priority:critical`

**Depends on:** Issues 2 and 3

**Acceptance criteria:**

- [ ] A context and container diagram is committed.
- [ ] Each proposed agent has a responsibility, inputs, outputs, tools, and failure behaviour.
- [ ] Data flow, trust boundaries, and human-control points are shown.
- [ ] Major alternatives and tradeoffs are documented.

### 5. Define privacy, security, and responsible-AI requirements

**Labels:** `area:architecture`, `area:data`, `area:ai`, `priority:critical`

**Acceptance criteria:**

- [ ] Collected data and its purpose, retention, and access rules are listed.
- [ ] Threats including prompt injection, harmful output, leakage, and over-reliance are assessed.
- [ ] Consent, deletion, source attribution, and escalation requirements are defined.
- [ ] A private vulnerability-reporting route is chosen and the placeholder issue link is replaced.

### 6. Design the data model and API contracts

**Labels:** `area:backend`, `area:data`, `priority:high`

**Depends on:** Issue 4

**Acceptance criteria:**

- [ ] Core entities and relationships are documented.
- [ ] Initial API requests, responses, validation, and error formats are specified.
- [ ] Personal and derived data fields are clearly identified.
- [ ] Example payloads contain only synthetic data.

### 7. Create wireframes for the primary user journey

**Labels:** `area:frontend`, `area:product`, `priority:high`

**Depends on:** Issue 2

**Acceptance criteria:**

- [ ] Onboarding, goal setting, learning interaction, practice, and progress states are covered.
- [ ] Loading, empty, error, and unsafe-response states are included.
- [ ] Accessibility and mobile behaviour are considered.
- [ ] Wireframes receive team feedback before implementation.

### 8. Define the evaluation plan and baseline

**Labels:** `area:research`, `area:ai`, `priority:critical`

**Depends on:** Issues 1, 2, and 4

**Acceptance criteria:**

- [ ] Research questions and hypotheses are documented.
- [ ] Offline and user-facing metrics are defined.
- [ ] A baseline for comparison is selected.
- [ ] Test cases cover correctness, usefulness, hallucination, safety, cost, and latency.
- [ ] Ethical review or supervisor approval needs are identified.

### 9. Bootstrap the selected application projects

**Labels:** `area:frontend`, `area:backend`, `priority:high`

**Depends on:** Issues 3 and 4

**Acceptance criteria:**

- [ ] Each approved application can be installed and run locally.
- [ ] Formatting, linting, type checking, and tests have documented commands.
- [ ] Configuration is represented safely in `.env.example`.
- [ ] README instructions work from a clean clone.

### 10. Add continuous integration and repository protections

**Labels:** `area:devops`, `priority:high`

**Depends on:** Issue 9

**Acceptance criteria:**

- [ ] Pull requests run formatting, linting, tests, and secret scanning.
- [ ] Required checks and review rules for `main` are documented.
- [ ] Workflows use least-privilege permissions and no production secrets.
- [ ] Dependency update and vulnerability-review policies are defined.

## First vertical-slice milestone

### 11. Implement the primary learning journey as a thin vertical slice

**Labels:** `area:frontend`, `area:backend`, `area:ai`, `priority:critical`

**Depends on:** Issues 4, 6, 7, 8, 9, and 10

**Acceptance criteria:**

- [ ] A user can complete the agreed primary journey end to end with synthetic data.
- [ ] Agent outputs are validated and failures have a safe fallback.
- [ ] The journey has automated and documented manual tests.
- [ ] Relevant evaluation signals can be captured without storing unnecessary personal data.

### 12. Run and document the first evaluation

**Labels:** `area:research`, `area:ai`, `priority:high`

**Depends on:** Issues 8 and 11

**Acceptance criteria:**

- [ ] The approved evaluation dataset or protocol is used.
- [ ] Results are reproducible and stored without sensitive raw data.
- [ ] Limitations, failures, cost, and latency are reported.
- [ ] Findings produce specific follow-up issues and inform the graduation report.
