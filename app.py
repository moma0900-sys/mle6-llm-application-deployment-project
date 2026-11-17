import asyncio
import hashlib
import json
import os
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from provider import DryProvider, Provider

provider: Provider = DryProvider()
PROVIDER_TIMEOUT_SECONDS = 5.0
MAX_CONCURRENT_PROVIDER_CALLS = 2
CACHE_TTL_SECONDS = 60.0
cache: dict[str, tuple[float, str]] = {}

model_provider = os.getenv("MODEL_PROVIDER", "dry")



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
    if model_provider != "dry":
        raise HTTPException(
            status_code=503,
            detail="Only the dry provider is available at this stage.",
        )

    return {"status": "ready", "provider": model_provider}


class GenerateRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    prompt: str = Field(min_length=1)


class GenerateResponse(BaseModel):
    text: str
    model: str
    cache_hit: bool


@app.post("/generate", response_model=GenerateResponse)
async def generate(request: GenerateRequest,http_request: Request) -> GenerateResponse:
    if model_provider != "dry":
        raise HTTPException(status_code=503, detail="Dry provider is required.")
    
    key_data = json.dumps([provider.model, request.prompt])
    key = hashlib.sha256(key_data.encode("utf-8")).hexdigest()

    entry = cache.get(key)
    if entry is not None:
        expires_at, cached_text = entry
        if time.monotonic() < expires_at:
            return GenerateResponse(
                text=cached_text,
                model=provider.model,
                cache_hit=True,
            )
        del cache[key]

    try:
        async with asyncio.timeout(PROVIDER_TIMEOUT_SECONDS):
            async with http_request.app.state.provider_slots:
                text = await provider.generate(request.prompt)
    except TimeoutError as exc:
        raise HTTPException(
            status_code=504,
            detail="Generation timed out.",
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail="Provider failed to generate an answer.",
        ) from exc
    
    cache[key] = (time.monotonic() + CACHE_TTL_SECONDS, text)
    return GenerateResponse(text=text, model=provider.model, cache_hit=False)