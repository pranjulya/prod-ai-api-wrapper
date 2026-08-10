# Phase 5 Authentication and Correlation Design

## Scope

Protect internal routes with the configured static bearer key and attach one
safe correlation identifier to every request and error.

## Design

Two HTTP middlewares are registered with correlation handling outermost.
Correlation handling accepts `X-Correlation-ID` only when it matches
`^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$`; otherwise it returns `400` with
`invalid_correlation_id`. When absent, it generates a UUID4. It writes the ID
to request state, the `X-Correlation-ID` response header, error bodies, and
safe request-completion logs.

Authentication applies to every route except the exact `/webhooks/openai`
path. It requires `Authorization: Bearer <WRAPPER_API_KEY>` and compares the
credential using `hmac.compare_digest`. Missing, malformed, or incorrect
credentials return `401` with the standard error shape and never log the
authorization header or configured key.

## Testing

Tests cover missing, malformed, and incorrect bearer credentials; successful
authenticated access; generated and client-supplied correlation IDs; malformed
correlation IDs; error/header correlation consistency; and absence of the
wrapper key from captured logs.

## Deliberate Deferrals

JWTs, multiple internal clients, webhook signature verification, structured
JSON logging, and background-job metadata are outside this phase.
