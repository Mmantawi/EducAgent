# Contributing to EducAgent

This guide keeps teamwork predictable while the project is being designed and built. Update it when the team agrees on its languages, package managers, test tools, and release process.

## Before you start

1. Check existing issues and pull requests to avoid duplicate work.
2. Discuss changes that affect scope, architecture, data handling, or the agent design before implementation.
3. Make sure the issue has a clear outcome and acceptance criteria.
4. Never place credentials, access tokens, personal student data, or licensed material in the repository.

## Branches

Create branches from the latest `main` and keep them focused. Use one of these patterns:

- `feat/<issue-number>-short-name`
- `fix/<issue-number>-short-name`
- `docs/<issue-number>-short-name`
- `research/<issue-number>-short-name`
- `chore/<issue-number>-short-name`

Example: `feat/24-study-plan-api`

Do not commit directly to `main` except when the team explicitly agrees on an emergency repository fix.

## Commits

Write small commits with an imperative summary. A simple Conventional Commits style is recommended:

```text
feat: add study-goal validation
fix: prevent empty quiz submission
docs: record agent orchestration decision
test: cover invalid study-plan requests
```

A commit should not mix unrelated refactoring, formatting, and feature work.

## Code and documentation quality

- Follow the formatter and linter chosen for each component.
- Add or update tests for changed behaviour.
- Prefer clear names and small modules over clever abstractions.
- Document public interfaces, configuration, and non-obvious decisions.
- Keep prompts versioned and reviewable; record why important prompt changes were made.
- Use anonymised or synthetic test data unless the team has explicit approval for another source.
- Add dependency files and lockfiles once, using the package manager agreed by the team.

## Pull requests

Before opening a pull request:

- update from `main` according to the team's chosen policy;
- run the relevant formatter, linter, tests, and security checks;
- remove debug output and unrelated generated files;
- update documentation and `.env.example` when configuration changes;
- complete the pull request template and link the issue it addresses.

Pull requests should normally be small enough to review in one sitting. Draft pull requests are welcome for early feedback. At least one teammate should approve before merge, and the author should not approve their own change.

## Reviews

Review for correctness, understandable design, tests, privacy, security, and user impact. Be specific and constructive. Mark suggestions as blocking only when they affect correctness, agreed requirements, safety, or maintainability.

## Agent and data changes

Changes involving agents, prompts, retrieval, or model providers should state:

- the expected input and output;
- the model/provider assumptions and configuration;
- failure and fallback behaviour;
- privacy and safety implications;
- evaluation cases or evidence;
- expected cost or latency impact when relevant.

Large datasets, embeddings, model weights, and evaluation outputs should not be committed to Git. Document their source, license, storage location, schema, and reproduction steps.

## Reporting problems

Use the repository issue forms for ordinary bugs, features, research work, and tasks. Report sensitive security or privacy problems privately to the team or supervisor; do not put secrets or exploitable details in a public issue.
