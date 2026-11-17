"""Run the Northstar functional cases against a running API."""

import argparse
import json
from pathlib import Path
from typing import Any

import httpx

CASES_PATH = Path(__file__).resolve().parents[1] / "data/evaluation/cases.json"


def run_cases(url: str, expected_model: str) -> list[dict[str, Any]]:
    """Capture API responses and check the model, output contract, and cache."""
    cases = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    results = []
    with httpx.Client(base_url=url.rstrip("/"), timeout=15) as client:
        for case in cases:
            for attempt in range(1, case["repeat"] + 1):
                result: dict[str, Any] = {
                    "case_id": case["case_id"],
                    "attempt": attempt,
                    "expected_terms": case["expected_terms"],
                    "expected_cache_hit": attempt > 1,
                }
                try:
                    response = client.post("/generate", json={"prompt": case["prompt"]})
                except httpx.RequestError as exc:
                    result.update(passed=False, error=str(exc))
                else:
                    try:
                        body = response.json()
                    except ValueError:
                        body = {}
                    if not isinstance(body, dict):
                        body = {}

                    text = body.get("text")
                    trace_id = body.get("trace_id")
                    result.update(
                        status_code=response.status_code,
                        model=body.get("model"),
                        cache_hit=body.get("cache_hit"),
                        trace_id=trace_id,
                        answer=text,
                        passed=(
                            response.status_code == 200
                            and body.get("model") == expected_model
                            and body.get("cache_hit") is result["expected_cache_hit"]
                            and isinstance(trace_id, str)
                            and bool(trace_id.strip())
                            and isinstance(text, str)
                            and bool(text.strip())
                        ),
                    )
                    if response.status_code != 200:
                        result["error"] = response.text

                results.append(result)
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument(
        "--model", required=True, help="Expected model ID in the response."
    )
    parser.add_argument(
        "--output", required=True, type=Path, help="Path for JSON evidence."
    )
    args = parser.parse_args()

    results = run_cases(args.url, args.model)
    for result in results:
        status = "PASS" if result["passed"] else "FAIL"
        print(f"{result['case_id']} | attempt {result['attempt']} | {status}")
        print(
            f"  HTTP={result.get('status_code')} model={result.get('model')} "
            f"cache_hit={result.get('cache_hit')} "
            f"(expected {result['expected_cache_hit']}) trace_id={result.get('trace_id')}"
        )
        print("  Expected terms:", ", ".join(result["expected_terms"]))
        print("  Answer:", result.get("answer") or result.get("error", ""))

    evidence = {"url": args.url, "expected_model": args.model, "results": results}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(evidence, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    passed = sum(result["passed"] for result in results)
    print(f"Technical checks: {passed}/{len(results)} passed")
    print(f"Evidence saved to {args.output}")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
