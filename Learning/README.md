# Learning Guide

This project builds a production-style FastAPI wrapper between an internal
application and the OpenAI Responses API. The wrapper keeps the OpenAI API key
private while adding the operational controls an internal service needs:
authentication, validation, rate limiting, idempotency, background jobs,
verified webhooks, consistent errors, and observable request handling.

## What this project proves

- An internal application can use AI without holding the OpenAI API key.
- A small, explicit API contract is safer to operate than forwarding every
  upstream option.
- Redis can coordinate state shared by multiple API instances.
- Background work needs durable job state and verified event delivery.
- Reliable services make retries safe, failures predictable, and requests
  traceable.

## Prerequisites

- Python basics: virtual environments, packages, type hints, and async code.
- HTTP basics: methods, status codes, headers, JSON, and bearer tokens.
- Docker Compose basics for running local services.
- Basic Redis concepts: keys, TTLs, and atomic operations.

## Learning objectives

By the end, you can explain and implement a FastAPI service that validates an
internal request, safely calls an upstream AI API, stores shared state in
Redis, and exposes synchronous and background response workflows.

Read [the learning path](learning-path.md) in order. Record design questions
and answers in [questions and answers](questions-and-answers.md) as each phase
adds a new concern.
