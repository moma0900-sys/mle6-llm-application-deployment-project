from typing import Protocol


class Provider(Protocol):
    model: str

    async def generate(self, prompt: str) -> str:
        ...


class DryProvider:
    model = "dry-northstar-v1"

    async def generate(self, prompt: str) -> str:
        if prompt == "What evidence is required for a duplicate-payment refund?":
            return "Please provide the receipt and both transaction references."

        return "I cannot confirm that from the approved policy."