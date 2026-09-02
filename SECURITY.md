# Security Policy

## Reporting a Vulnerability

Security is a core design pillar of this production API wrapper. If you believe you have found a security vulnerability, please do **not** open a public issue.

Instead, please report security vulnerabilities responsibly by emailing the maintainer or opening a private GitHub Security Advisory.

Please include:
- A description of the vulnerability.
- Steps to reproduce or proof-of-concept.
- Potential impact.

We will acknowledge receipt of your report within 48 hours and work on a resolution promptly.

---

## Security Architecture & Design Principles

This service adheres to the following security guarantees:

1. **Zero Secret Leakage:**
   - OpenAI API keys, internal bearer tokens, and webhook secrets are never logged, echoed in HTTP response bodies, or returned in error payloads.
   - Structured JSON logging uses strict field allowlists.

2. **Payload & Prompt Isolation:**
   - Client prompts and upstream LLM completions are excluded from logs by default to avoid sensitive data / PII leakage into log ingestion platforms.

3. **Cryptographic Webhook Verification:**
   - Webhook ingress strictly verifies raw HMAC-SHA256 signatures (`webhook-signature`, `webhook-timestamp`, `webhook-id`) prior to parsing or updating state.
   - Webhook request bodies are capped at 1 MiB to prevent memory exhaustion / DoS attacks.

4. **Model Allowlisting:**
   - Clients cannot request arbitrary models. All requested models are validated against the strict `OPENAI_ALLOWED_MODELS` environment variable.

5. **Principle of Least Privilege:**
   - Production Docker containers run as a dedicated, non-root user (`appuser` UID 1000).
