#!/usr/bin/env python3
"""
scripts/test_llm_client.py
Smoke test for GPUStack integration.
Run: python scripts/test_llm_client.py
"""
import json
import sys

from llm_client import generate

from config import GPUSTACK_MODEL_ORCHESTRATOR, GPUSTACK_MODEL_TEXT


def main():
    errors = []

    # Test 1: GPUSTACK_MODEL_TEXT responds
    print(f"[1/4] Testing GPUSTACK_MODEL_TEXT={GPUSTACK_MODEL_TEXT}…")
    try:
        out = generate(
            'Say "Hello from Qwen" in exactly those words. No other text.',
            max_tokens=32,
        )
        print(f"    Response: {out[:100]}")
    except Exception as e:
        errors.append(f"GPUSTACK_MODEL_TEXT failed: {e}")
        print(f"    ERROR: {e}")

    # Test 2: GPUSTACK_MODEL_ORCHESTRATOR responds
    print(f"\n[2/4] Testing GPUSTACK_MODEL_ORCHESTRATOR={GPUSTACK_MODEL_ORCHESTRATOR}…")
    try:
        out2 = generate(
            'Say "Hello from MiniMax" in exactly those words. No other text.',
            model=GPUSTACK_MODEL_ORCHESTRATOR,
            max_tokens=32,
        )
        print(f"    Response: {out2[:100]}")
    except Exception as e:
        errors.append(f"GPUSTACK_MODEL_ORCHESTRATOR failed: {e}")
        print(f"    ERROR: {e}")

    # Test 3: JSON output parses
    print("\n[3/4] Testing JSON output from GPUSTACK_MODEL_TEXT…")
    try:
        out3 = generate(
            'Return valid JSON: [{"king": "Baldwin I", "years": "1100-1118"}]',
            max_tokens=256,
        )
        data = json.loads(out3.strip())
        print(f"    Parsed: {len(data)} item(s) — {data}")
    except json.JSONDecodeError as e:
        errors.append(f"JSON parse error: {e}")
        print(f"    JSON ERROR: {e}")
        print(f"    Raw: {out3[:200]}")

    # Test 4: Credentials check (not 401/403)
    print("\n[4/4] Checking credentials (not 401/403)…")
    try:
        generate("Reply OK", max_tokens=8)
        print("    Credentials OK")
    except Exception as e:
        err = str(e)
        if "401" in err or "403" in err:
            errors.append(f"Auth error: {err}")
            print(f"    AUTH ERROR: {err}")
        else:
            print(f"    Non-auth error (may be OK): {err[:100]}")

    print()
    if errors:
        print(f"FAILURES: {len(errors)}")
        for e in errors:
            print(f"  - {e}")
        sys.exit(1)
    else:
        print("All 4 tests passed.")


if __name__ == "__main__":
    main()
