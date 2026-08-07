import json
import asyncio

import httpx
import pytest

from app.domain.models import ContextSnapshot
from app.services.assistant import OpenAIResponsesProvider, ProviderError


def context() -> ContextSnapshot:
    return ContextSnapshot.model_validate(
        {
            "product": "tyche",
            "page": {"type": "resume", "id": "resume-1", "label": "Product résumé"},
            "selection": {
                "type": "resume_bullet",
                "ids": ["bullet-1"],
                "label": "Selected résumé bullet",
                "excerpt": "Managed the product roadmap.",
            },
            "authorised_resources": [
                {"id": "resume-1", "type": "resume", "label": "Product résumé"}
            ],
            "snapshot_version": "resume-v1",
            "created_by": "test-user",
            "workspace_id": "workspace-1",
        }
    )


def test_openai_provider_validates_and_maps_structured_result() -> None:
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        model_result = {
            "content": "A stronger version based only on the selected bullet.",
            "cited_evidence_ids": ["selection:bullet-1", "made-up-id"],
            "proposal": {
                "title": "Update selected résumé bullet",
                "summary": "Clarifies ownership.",
                "suggested": "Led product roadmap prioritisation.",
            },
        }
        return httpx.Response(
            200,
            json={
                "output": [
                    {
                        "type": "message",
                        "content": [{"type": "output_text", "text": json.dumps(model_result)}],
                    }
                ]
            },
        )

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = OpenAIResponsesProvider("test-key", client=client)
            return await provider.respond("Make this stronger", context())

    result = asyncio.run(run())

    assert captured["store"] is False
    assert captured["text"]["format"]["strict"] is True
    assert captured["safety_identifier"] != "test-user"
    assert [item.id for item in result.evidence] == ["selection:bullet-1"]
    assert result.proposals[0].diff.original == "Managed the product roadmap."


def test_openai_provider_rejects_unstructured_output() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"output": [{"type": "message", "content": [{"type": "output_text", "text": "not-json"}]}]},
        )

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = OpenAIResponsesProvider("test-key", client=client)
            await provider.respond("Make this stronger", context())

    with pytest.raises(ProviderError):
        asyncio.run(run())
