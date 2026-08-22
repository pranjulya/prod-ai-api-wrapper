# Blockers and Phase 16 Implementation Plan

> **For agentic workers:** Execute task-by-task with tests first.

**Goal:** Short idempotency claims, no timeout double-bill, unauthenticated health, contract 422, collectable pytest, Docker Compose on Redis 7.

**Architecture:** Reuse `processing_ttl` for claims; keep timeout claims; exempt health and normalize webhook path; map 422; Compose API + Redis 7.

## Task 1: Claim TTL and timeout retain
## Task 2: Auth exemptions and validation_error
## Task 3: Pytest import
## Task 4: Docker, Compose, README
