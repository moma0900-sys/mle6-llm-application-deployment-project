import asyncio
from concurrent.futures import ThreadPoolExecutor

from fastapi.testclient import TestClient

import app as api


def test_provider_error_returns_502(monkeypatch):
    class FailingProvider:
        model = "test-model"

        async def generate(self, prompt: str) -> str:
            raise RuntimeError("Test provider error")

    monkeypatch.setattr(api, "provider", FailingProvider())
    monkeypatch.setattr(api, "model_provider", "dry")

    with TestClient(api.app) as client:
        response = client.post("/generate", json={"prompt": "Test prompt"})

    assert response.status_code == 502


def test_provider_timeout_returns_504(monkeypatch):
    class SlowProvider:
        model = "test-model"

        async def generate(self, prompt: str) -> str:
            await asyncio.sleep(1)
            return "Late answer"

    monkeypatch.setattr(api, "provider", SlowProvider())
    monkeypatch.setattr(api, "model_provider", "dry")
    monkeypatch.setattr(api, "PROVIDER_TIMEOUT_SECONDS", 0.01)

    with TestClient(api.app) as client:
        response = client.post("/generate", json={"prompt": "Test prompt"})

    assert response.status_code == 504


def test_repeated_prompt_calls_provider_once(monkeypatch):
    class CountingProvider:
        model = "test-model"

        def __init__(self) -> None:
            self.calls = 0

        async def generate(self, prompt: str) -> str:
            self.calls += 1
            return "Test answer"

    provider = CountingProvider()
    monkeypatch.setattr(api, "provider", provider)
    monkeypatch.setattr(api, "model_provider", "dry")
    monkeypatch.setattr(api, "cache", {})

    payload = {"prompt": "Test prompt"}

    with TestClient(api.app) as client:
        first = client.post("/generate", json=payload)
        second = client.post("/generate", json=payload)

    assert first.status_code == second.status_code == 200
    assert first.json()["cache_hit"] is False
    assert second.json()["cache_hit"] is True
    assert provider.calls == 1


def test_at_most_two_provider_calls_run_at_once(monkeypatch):
    class SlowProvider:
        model = "test-model"

        def __init__(self) -> None:
            self.active_calls = 0
            self.peak_calls = 0

        async def generate(self, prompt: str) -> str:
            self.active_calls += 1
            self.peak_calls = max(self.peak_calls, self.active_calls)
            try:
                await asyncio.sleep(0.1)
                return "Test answer"
            finally:
                self.active_calls -= 1

    provider = SlowProvider()
    monkeypatch.setattr(api, "provider", provider)
    monkeypatch.setattr(api, "model_provider", "dry")
    monkeypatch.setattr(api, "cache", {})
    monkeypatch.setattr(api, "MAX_CONCURRENT_PROVIDER_CALLS", 2)

    with TestClient(api.app) as client:
        def send(prompt: str):
            return client.post("/generate", json={"prompt": prompt})

        with ThreadPoolExecutor(max_workers=3) as pool:
            responses = list(pool.map(send, ["Prompt A", "Prompt B", "Prompt C"]))

    assert [response.status_code for response in responses] == [200, 200, 200]
    assert provider.peak_calls == 2