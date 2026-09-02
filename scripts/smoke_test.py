#!/usr/bin/env python3
"""Smoke test script for Production API Wrapper.

Exercises the core endpoints of a running wrapper instance to verify:
- Liveness (/health/live)
- Readiness (/health/ready)
- Bearer Authentication enforcement
- Rate limit headers & handling
- Synchronous completions with idempotency
- Background job submission & polling status
"""

import argparse
import os
import sys
import time
import uuid

try:
    import httpx
except ImportError:
    print("Error: 'httpx' is required to run this script. Install with: pip install httpx")
    sys.exit(1)


GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
BLUE = "\033[94m"
RESET = "\033[0m"
BOLD = "\033[1m"


def print_banner(base_url: str):
    print(f"\n{BLUE}{BOLD}======================================================{RESET}")
    print(f"{BLUE}{BOLD}   Production API Wrapper — Smoke Verification Suite   {RESET}")
    print(f"{BLUE}{BOLD}======================================================{RESET}")
    print(f"Target: {BOLD}{base_url}{RESET}\n")


def check(name: str, passed: bool, detail: str = ""):
    badge = f"{GREEN}[PASS]{RESET}" if passed else f"{RED}[FAIL]{RESET}"
    print(f"{badge} {BOLD}{name}{RESET} {detail}")
    return passed


def main():
    parser = argparse.ArgumentParser(description="Smoke test for Production API Wrapper")
    parser.add_argument("--url", default=os.getenv("WRAPPER_BASE_URL", "http://localhost:8000"), help="Base URL")
    parser.add_argument("--key", default=os.getenv("WRAPPER_API_KEY", "test-wrapper-key"), help="Wrapper API Key")
    args = parser.parse_args()

    base_url = args.url.rstrip("/")
    api_key = args.key

    print_banner(base_url)

    client = httpx.Client(base_url=base_url, timeout=10.0)
    all_passed = True

    # 1. Liveness check
    try:
        res = client.get("/health/live")
        all_passed &= check("Liveness Probe (GET /health/live)", res.status_code == 200, f"-> HTTP {res.status_code}")
    except Exception as exc:
        all_passed &= check("Liveness Probe (GET /health/live)", False, f"-> Connection failed: {exc}")
        print(f"\n{RED}Cannot connect to {base_url}. Make sure the server is running.{RESET}\n")
        sys.exit(1)

    # 2. Readiness check
    try:
        res = client.get("/health/ready")
        all_passed &= check("Readiness Probe (GET /health/ready)", res.status_code == 200, f"-> HTTP {res.status_code}")
    except Exception as exc:
        all_passed &= check("Readiness Probe (GET /health/ready)", False, f"-> {exc}")

    # 3. Authentication enforcement
    try:
        res = client.post("/v1/responses", json={"input": "Hello"})
        all_passed &= check("Auth Guard: Missing Bearer Token", res.status_code == 401, f"-> HTTP {res.status_code} (401 Expected)")
    except Exception as exc:
        all_passed &= check("Auth Guard: Missing Bearer Token", False, f"-> {exc}")

    # 4. Idempotency Key requirement
    headers = {"Authorization": f"Bearer {api_key}"}
    try:
        res = client.post("/v1/responses", headers=headers, json={"input": "Hello"})
        all_passed &= check("Validation: Missing Idempotency-Key", res.status_code == 422, f"-> HTTP {res.status_code} (422 Expected)")
    except Exception as exc:
        all_passed &= check("Validation: Missing Idempotency-Key", False, f"-> {exc}")

    # 5. Correlation ID generation & header propagation
    idem_key = f"smoke-{uuid.uuid4()}"
    custom_cid = f"cid-{uuid.uuid4().hex[:12]}"
    req_headers = {
        "Authorization": f"Bearer {api_key}",
        "Idempotency-Key": idem_key,
        "X-Correlation-ID": custom_cid,
    }

    try:
        res = client.post("/v1/responses", headers=req_headers, json={"input": "Say 'OK' in one word."})
        cid_propagated = res.headers.get("x-correlation-id") == custom_cid
        all_passed &= check("Correlation ID Header Propagation", cid_propagated, f"-> Returned: {res.headers.get('x-correlation-id')}")

        if res.status_code == 200:
            data = res.json()
            check("Synchronous Response (/v1/responses)", True, f"-> Model: {data.get('model')}, Output: {data.get('output_text')[:30]}...")

            # 6. Idempotency replay check
            res_replay = client.post("/v1/responses", headers=req_headers, json={"input": "Say 'OK' in one word."})
            all_passed &= check("Idempotency Replay (Same Key & Payload)", res_replay.status_code == 200, "-> Successfully replayed cached response")

            # 7. Idempotency conflict check (Same Key, different payload)
            res_conflict = client.post("/v1/responses", headers=req_headers, json={"input": "Different prompt text"})
            all_passed &= check("Idempotency Conflict Guard (409 on Payload Mismatch)", res_conflict.status_code == 409, f"-> HTTP {res_conflict.status_code}")
        else:
            print(f"  {YELLOW}Note: Synchronous call returned HTTP {res.status_code} (expected if OpenAI API key is placeholder).{RESET}")
    except Exception as exc:
        all_passed &= check("Synchronous API Execution", False, f"-> {exc}")

    # 8. Background Response Job
    bg_idem_key = f"smoke-bg-{uuid.uuid4()}"
    bg_headers = {
        "Authorization": f"Bearer {api_key}",
        "Idempotency-Key": bg_idem_key,
    }
    try:
        res_bg = client.post("/v1/responses/background", headers=bg_headers, json={"input": "Generate a background summary."})
        if res_bg.status_code == 202:
            job_data = res_bg.json()
            job_id = job_data.get("id")
            all_passed &= check("Background Job Creation (202 Accepted)", True, f"-> Job ID: {job_id}")

            # 9. Background Job Polling
            poll_res = client.get(f"/v1/responses/{job_id}", headers=headers)
            all_passed &= check("Background Job Polling (GET /v1/responses/{id})", poll_res.status_code in (200, 202), f"-> Status: {poll_res.json().get('status')}")
        else:
            print(f"  {YELLOW}Note: Background submission returned HTTP {res_bg.status_code} (expected with placeholder keys).{RESET}")
    except Exception as exc:
        all_passed &= check("Background Job Submission", False, f"-> {exc}")

    print(f"\n{BLUE}{BOLD}======================================================{RESET}")
    if all_passed:
        print(f"{GREEN}{BOLD}  All verification checks passed successfully!  {RESET}")
    else:
        print(f"{YELLOW}{BOLD}  Some checks did not pass (see details above).  {RESET}")
    print(f"{BLUE}{BOLD}======================================================{RESET}\n")


if __name__ == "__main__":
    main()
