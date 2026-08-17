# Redis Failure After Provider Acceptance

## Goal

Prevent an idempotent client retry from creating a second OpenAI response when Redis fails after OpenAI has already accepted or completed the first request.

## Scope

The change covers synchronous and background response creation in `app/api/responses.py`, job cleanup in `app/services/jobs.py`, and focused regression tests. It does not add a durable recovery queue or change behavior for Redis failures that occur before the OpenAI request starts.

## Design

Before the OpenAI call, Redis remains authoritative. Claim or job-creation failures return `503`, and provider failures release the claim and any pending job as they do today.

After the OpenAI call succeeds, the provider result is authoritative. A Redis failure must not release the idempotency claim or return an error that invites the client to repeat the provider call:

- Synchronous creation returns the normalized provider response even when storing the completed idempotency record fails.
- Background creation returns the accepted job response even when persisting the provider response ID or completed idempotency record fails.
- These post-provider Redis failures are still logged as Redis failures for operational visibility.
- The retained in-progress claim prevents the same idempotency key from reaching OpenAI again while its TTL remains active. A later retry may receive `idempotency_in_progress`; avoiding a duplicate provider charge takes precedence over replay availability during the Redis incident.

Background persistence continues to save the job and OpenAI-response reverse index together through `update_job_with_response_id` before storing the idempotency replay response.

## Cleanup Invariant

When a background job must be abandoned before provider acceptance, job cleanup removes the job and, when present, its `wrapper:openai-response-job:*` reverse index in one Redis transaction. The cleanup operation derives the reverse-index key from the stored job record and issues both deletions through one transactional pipeline.

No post-provider failure path deletes the idempotency claim.

## Error Handling

- Redis failure before provider acceptance: return `503` and release the claim/pending job.
- Provider timeout or retryable provider error: retain existing HTTP mapping and release pre-provider state.
- Redis failure after provider acceptance: log the failure and return the already-available success/accepted response.
- Cleanup Redis failure remains suppressed because the original upstream failure determines the client response.

## Tests

Regression tests inject Redis failures only after the fake OpenAI client succeeds:

1. Synchronous storage failure returns `200`, retains the claim, and a retry does not make a second provider call.
2. Background provider-ID persistence failure returns `202`, retains the claim, and a retry does not make a second provider call.
3. Background idempotency-store failure after provider-ID persistence returns `202`, preserves the job and reverse index, and a retry does not make a second provider call.
4. Job deletion removes both the job key and reverse-index key through one pipeline.

Existing response, background, idempotency, job, and upstream-error tests remain green.
