import asyncio
import hashlib
import json
import logging
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from httpx import TimeoutException
from langfuse import get_client
from pydantic import BaseModel, ConfigDict, Field

from provider import DryProvider, GenerationResult, GroqProvider, Provider

PROVIDER_TIMEOUT_SECONDS = 5.0
MAX_CONCURRENT_PROVIDER_CALLS = 2
CACHE_TTL_SECONDS = 60.0
cache: dict[str, tuple[float, str]] = {}

load_dotenv()
logger = logging.getLogger(__name__)

model_provider = os.getenv("MODEL_PROVIDER", "dry")
provider: Provider | None
if model_provider == "dry":
    provider = DryProvider()
elif model_provider == "groq" and (api_key := os.getenv("GROQ_API_KEY")):
    provider = GroqProvider(api_key, os.getenv("GROQ_MODEL") or "openai/gpt-oss-20b")
else:
    provider = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.provider_slots = asyncio.Semaphore(MAX_CONCURRENT_PROVIDER_CALLS)
    yield


app = FastAPI(title="Northstar Support Assistant", lifespan=lifespan)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "healthy"}


@app.get("/ready")
def ready() -> dict[str, str]:
    if provider is None:
        raise HTTPException(
            status_code=503, detail="The configured model provider is unavailable."
        )
    return {"status": "ready", "provider": model_provider}


class GenerateRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    prompt: str = Field(min_length=1)


class GenerateResponse(BaseModel):
    text: str
    model: str
    cache_hit: bool
    trace_id: str


@app.post("/generate", response_model=GenerateResponse)
async def generate(request: GenerateRequest, http_request: Request) -> GenerateResponse:
    active_provider = provider
    if active_provider is None:
        raise HTTPException(
            status_code=503, detail="The configured model provider is unavailable."
        )
    model = active_provider.model
    trace_id = uuid4().hex
    started_at = time.perf_counter()

    key_fields: list[str | int] = [model_provider, model, request.prompt]
    if isinstance(active_provider, GroqProvider):
        key_fields.extend(
            [active_provider.system_prompt, active_provider.max_completion_tokens]
        )
    key_data = json.dumps(key_fields)
    key = hashlib.sha256(key_data.encode("utf-8")).hexdigest()
    preparation_ms = (time.perf_counter() - started_at) * 1_000

    entry = cache.get(key)
    if entry is not None:
        expires_at, cached_text = entry
        if time.monotonic() < expires_at:
            record_trace(
                trace_id,
                True,
                (time.perf_counter() - started_at) * 1_000,
                model=model,
                preparation_ms=preparation_ms,
            )
            return GenerateResponse(
                text=cached_text, model=model, cache_hit=True, trace_id=trace_id
            )
        del cache[key]

    provider_started = False
    try:
        async with asyncio.timeout(PROVIDER_TIMEOUT_SECONDS):
            async with http_request.app.state.provider_slots:
                provider_started = True
                result = await active_provider.generate(request.prompt)
    except (TimeoutError, TimeoutException) as exc:
        record_trace(
            trace_id,
            False,
            (time.perf_counter() - started_at) * 1_000,
            model=model,
            preparation_ms=preparation_ms,
            status_code=504,
            provider_started=provider_started,
        )
        raise HTTPException(status_code=504, detail="Generation timed out.") from exc
    except Exception as exc:
        record_trace(
            trace_id,
            False,
            (time.perf_counter() - started_at) * 1_000,
            model=model,
            preparation_ms=preparation_ms,
            status_code=502,
            provider_started=provider_started,
        )
        raise HTTPException(
            status_code=502, detail="Provider failed to generate an answer."
        ) from exc

    if isinstance(result, GenerationResult):
        text = result.text
        usage_details = result.usage_details
    else:
        text = result
        usage_details = None

    cache[key] = (time.monotonic() + CACHE_TTL_SECONDS, text)
    record_trace(
        trace_id,
        False,
        (time.perf_counter() - started_at) * 1_000,
        model=model,
        preparation_ms=preparation_ms,
        usage_details=usage_details,
    )
    return GenerateResponse(text=text, model=model, cache_hit=False, trace_id=trace_id)


def record_trace(
    trace_id: str,
    cache_hit: bool,
    latency_ms: float,
    *,
    model: str,
    preparation_ms: float,
    status_code: int = 200,
    provider_started: bool = True,
    usage_details: dict[str, int] | None = None,
) -> None:
    stages = ["prepare-request", "cache-lookup"]
    if not cache_hit and provider_started:
        stages.append("llm-generation")
        if model_provider == "dry":
            usage_details = {"input": 0, "output": 0, "total": 0}

    trace = {
        "trace_id": trace_id,
        "name": "support-request",
        "model": model,
        "cache_hit": cache_hit,
        "latency_ms": round(latency_ms, 2),
        "preparation_ms": round(preparation_ms, 3),
        "stages": stages,
        "status_code": status_code,
        "usage_details": usage_details,
    }

    if os.getenv("TRACE_SINK", "jsonl") == "langfuse":
        try:
            langfuse = get_client()
            with langfuse.start_as_current_observation(
                name="support-request",
                as_type="span",
                trace_context={"trace_id": trace_id},
                level="ERROR" if status_code >= 500 else "DEFAULT",
                metadata={
                    "cache_hit": cache_hit,
                    "status_code": status_code,
                    "request_latency_ms": round(latency_ms, 2),
                },
            ):
                with langfuse.start_as_current_observation(
                    name="prepare-request",
                    as_type="span",
                    metadata={"duration_ms": round(preparation_ms, 3)},
                ):
                    pass

                with langfuse.start_as_current_observation(
                    name="cache-lookup",
                    as_type="span",
                    metadata={"cache_hit": cache_hit},
                ):
                    pass

                if "llm-generation" in stages:
                    with langfuse.start_as_current_observation(
                        name="llm-generation",
                        as_type="generation",
                        model=model,
                        level="ERROR" if status_code >= 500 else "DEFAULT",
                        usage_details=usage_details,
                        cost_details={"total": 0.0}
                        if model_provider == "dry"
                        else None,
                    ):
                        pass
        except Exception:
            logger.exception("Could not record Langfuse observations")

    path = Path("reports/generated/local-traces.jsonl")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as file:
        file.write(json.dumps(trace) + "\n")
