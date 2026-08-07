# Questions and Answers

Add questions here as implementation reveals trade-offs. These initial answers
explain the roadmap decisions already made.

## Why use a wrapper instead of letting the internal application call OpenAI?

The wrapper keeps the OpenAI API key in one service and gives the internal
application a stable, deliberately smaller API contract. It also centralizes
controls such as authentication, rate limiting, retries, and logs.

## Why expose only a limited set of response-creation fields?

A limited contract is easier to validate, document, test, and evolve. The
wrapper can add a field when there is a real internal use case instead of
coupling clients to every upstream option.

## Why is Redis required?

Rate-limit counters, idempotency records, job state, and processed webhook
events must be shared by all API instances and survive an individual process
restart. In-memory state cannot provide that.

## Why do background responses need both Redis and webhooks?

Redis gives the internal application a durable job record to poll. Verified
webhooks allow the wrapper to update that record promptly when OpenAI reports
a terminal state.

## Why require an idempotency key for billable work?

Networks and clients retry. An idempotency key lets the wrapper recognize a
repeat of the same validated request and return the saved result instead of
creating another upstream request.

## Why use correlation IDs?

They connect the client response, structured logs, retries, background job
metadata, and errors, making a single request diagnosable without recording
sensitive prompts or credentials.
