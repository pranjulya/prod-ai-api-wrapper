# Learning Path

Follow the roadmap in order; each phase adds one operational concern to a
working service.

1. **Project setup** — establish Git, Python metadata, and secret-safe local
   configuration.
2. **Learning foundation** — define the purpose, vocabulary, and decisions.
3. **API contract** — document the endpoints, supported fields, headers, and
   error shape before behavior exists.
4. **FastAPI application (complete)** — start the service, validate basic
   startup configuration, and add a dependency-free liveness endpoint.
5. **Configuration (complete)** — load environment settings, validate secrets and operational limits at startup, and keep secret values out of errors.
6. **Authentication and correlation (complete)** — require the internal bearer
   key and trace every response with a correlation ID.
7. **Redis integration and readiness (complete)** — create and close shared
   Redis clients, check readiness with `PING`, and keep liveness independent.
8. **Rate limiting (complete)** — enforce a shared atomic Redis fixed-window
   request limit across service instances.
9. **Synchronous responses (complete)** — forward a deliberately smaller
   request contract through the official OpenAI SDK and normalize the result.
10. **Upstream failures** — translate timeouts and provider errors into stable
    wrapper errors.
11. **Idempotency** — make client retries safe from duplicate billable work.
12. **Background creation** — create durable jobs and return quickly.
13. **Job status** — let clients poll job state safely.
14. **Webhooks** — verify OpenAI events and update job state exactly once.
15. **Observability** — add structured logs and correlation-aware events.
16. **Testing** — automate unit, integration, and contract checks.
17. **Local operations** — complete Docker Compose and smoke-test workflows.

## Vocabulary

- **Wrapper**: the internal service between the application and OpenAI.
- **Correlation ID**: an identifier used to trace one request across logs and
  responses.
- **Idempotency key**: a client-supplied key that makes a retry return the
  original result instead of creating duplicate work.
- **Rate limit**: a bound on requests accepted in a time window.
- **TTL**: time to live; Redis removes the key after this duration.
- **Background response**: an upstream response that completes after the
  initial HTTP request.
- **Webhook**: an HTTP event sent by OpenAI to report an asynchronous update.
- **Readiness**: whether this instance has the dependencies needed to serve
  requests correctly.
