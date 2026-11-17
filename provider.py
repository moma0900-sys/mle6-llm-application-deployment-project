from dataclasses import dataclass
from typing import Protocol

import httpx

NORTHSTAR_SUPPORT_POLICY = """You are the Northstar support assistant.
Apply only these exercise policies and answer briefly in English.
- Duplicate-payment refunds require the receipt and both transaction references.
- For a locked account, verify the customer's identity before guiding them through
  the approved account reset process.
- For personal-data deletion requests, explain that support should refer the
  request to the privacy team for human review.
- Give guidance only. Never claim that you forwarded a request, contacted
  anyone, or completed an action. Do not promise a reply or a timeline.
- During an active incident, direct customers to the status page and share only
  confirmed information.
- For requests outside these policies, say that you cannot confirm the request
  from the approved policy. Do not make promises or invent policy details."""


@dataclass(frozen=True)
class GenerationResult:
    text: str
    usage_details: dict[str, int]


class Provider(Protocol):
    model: str

    async def generate(self, prompt: str) -> str | GenerationResult: ...


class DryProvider:
    model = "dry-northstar-v1"

    async def generate(self, prompt: str) -> str:
        if prompt == "What evidence is required for a duplicate-payment refund?":
            return "Please provide the receipt and both transaction references."

        return "I cannot confirm that from the approved policy."


class GroqProvider:
    def __init__(self, api_key: str, model: str) -> None:
        self.model = model
        self._api_key = api_key
        self.system_prompt = NORTHSTAR_SUPPORT_POLICY
        self.max_completion_tokens = 512

    async def generate(self, prompt: str) -> GenerationResult:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {self._api_key}"},
                json={
                    "model": self.model,
                    "messages": [
                        {"role": "system", "content": self.system_prompt},
                        {"role": "user", "content": prompt},
                    ],
                    "max_completion_tokens": self.max_completion_tokens,
                },
            )
            response.raise_for_status()

        data = response.json()
        text = data["choices"][0]["message"]["content"]
        if not isinstance(text, str) or not text.strip():
            raise ValueError("Groq returned no answer text.")

        usage = data["usage"]
        return GenerationResult(
            text=text.strip(),
            usage_details={
                "input": usage["prompt_tokens"],
                "output": usage["completion_tokens"],
                "total": usage["total_tokens"],
            },
        )
