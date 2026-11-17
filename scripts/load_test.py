# python scripts/load_test.py --url "$URL" --validate
"""Run a small asynchronous load probe against a deployed endpoint."""

import argparse
import asyncio
import json
import math
import statistics
import time
from pathlib import Path

import httpx

LOAD_PROFILE = Path(__file__).resolve().parents[1] / "data/operations/load_profile.json"


def positive_int(value: str) -> int:
    """Parse a strictly positive command-line integer."""
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("value must be greater than zero")
    return parsed


async def send(client: httpx.AsyncClient, url: str, prompt: str) -> tuple[int, float]:
    """Send one request and return status plus elapsed milliseconds."""
    started = time.perf_counter()
    try:
        response = await client.post(
            f"{url.rstrip('/')}/generate", json={"prompt": prompt}
        )
        status = response.status_code
    except httpx.RequestError:
        status = 0  # A transport failure is still a failed load-test request.
    return status, (time.perf_counter() - started) * 1000


async def run(url: str, requests: int, concurrency: int) -> tuple[float, float]:
    """Print the measured metrics and return p95 latency and the error rate."""
    semaphore = asyncio.Semaphore(concurrency)

    async def bounded(index: int, client: httpx.AsyncClient) -> tuple[int, float]:
        async with semaphore:
            return await send(client, url, f"Explain deployment check {index % 3}.")

    started = time.perf_counter()
    async with httpx.AsyncClient(timeout=60) as client:
        results = await asyncio.gather(*(bounded(i, client) for i in range(requests)))
    elapsed = time.perf_counter() - started
    latencies = sorted(latency for _, latency in results)
    p95_index = math.ceil(len(latencies) * 0.95) - 1
    p95_latency_ms = latencies[p95_index]
    errors = sum(not 200 <= status < 300 for status, _ in results)
    error_rate = errors / requests
    print(f"requests={requests} concurrency={concurrency}")
    print(f"throughput_rps={requests / elapsed:.2f}")
    print(f"successful_requests={requests - errors}")
    print(f"successful_throughput_rps={(requests - errors) / elapsed:.2f}")
    print(f"mean_latency_ms={statistics.mean(latencies):.2f}")
    print(f"p95_latency_ms={p95_latency_ms:.2f}")
    print(f"error_rate={error_rate:.2%}")
    return p95_latency_ms, error_rate


def validate_targets(
    p95_latency_ms: float, error_rate: float, objectives: dict[str, float]
) -> int:
    """Check the two objectives measured by the load probe."""
    max_p95_ms = objectives["p95_latency_ms"]
    max_error_rate = objectives["max_error_rate"]
    latency_passed = p95_latency_ms <= max_p95_ms
    error_rate_passed = error_rate <= max_error_rate
    print(
        f"p95_latency_target={'PASS' if latency_passed else 'FAIL'} (limit={max_p95_ms:g} ms)"
    )
    print(
        f"error_rate_target={'PASS' if error_rate_passed else 'FAIL'} (limit={max_error_rate:.2%})"
    )
    return 0 if latency_passed and error_rate_passed else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Probe an LLM service endpoint.")
    parser.add_argument("--url", default="http://localhost:8000")
    parser.add_argument("--requests", type=positive_int)
    parser.add_argument("--concurrency", type=positive_int)
    parser.add_argument(
        "--validate",
        action="store_true",
        help="Use the load profile and check its targets.",
    )
    args = parser.parse_args()

    if not args.validate:
        asyncio.run(run(args.url, args.requests or 20, args.concurrency or 4))
        return 0

    profile = json.loads(LOAD_PROFILE.read_text(encoding="utf-8"))
    requests = profile["requests"]
    concurrency = profile["concurrency"]
    if args.requests not in (None, requests) or args.concurrency not in (
        None,
        concurrency,
    ):
        parser.error(
            f"--validate requires {requests} requests and concurrency {concurrency}."
        )

    print(f"url={args.url}")
    p95_latency_ms, error_rate = asyncio.run(run(args.url, requests, concurrency))
    return validate_targets(p95_latency_ms, error_rate, profile["service_objectives"])


if __name__ == "__main__":
    raise SystemExit(main())
