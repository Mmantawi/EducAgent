# AI system

This directory owns the AI-specific parts of EducAgent:

- curriculum ingestion and skill extraction;
- retrieval and grounding;
- tutoring-agent orchestration and prompt versions;
- knowledge tracing and learner-state estimation;
- answer and pedagogy evaluation;
- adaptive lesson-policy decisions;
- speech-model adapters when they belong to the AI layer;
- offline evaluation datasets, fixtures, and runners.

Keep model-provider integrations behind interfaces. Every behavioural change should describe expected inputs and outputs, safe failure behaviour, evaluation evidence, privacy impact, and expected latency or cost.
