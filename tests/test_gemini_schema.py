"""Inspect actual SDK request bodies without making a live Gemini call."""

import json

import httpx
import pytest
from google import genai
from google.genai import types
from pydantic import ValidationError

from server.generator import generate_script


def lesson_reply(extra_field=False):
    visual = {
        "kind": "tree", "caption": "The root has two children.",
        "nodes": [{"id": "root", "label": "10", "color": "ink"},
                  {"id": "left", "label": "5", "color": "red"},
                  {"id": "right", "label": "15", "color": "red"}],
        "edges": [{"source": "root", "target": "left"},
                  {"source": "root", "target": "right"}],
    }
    if extra_field:
        visual["python"] = "This is untrusted extra data."
    scene = {
        "title": "A red-black tree", "bullets": ["The root is black"], "visual": visual,
        "narration": "A red-black tree keeps its search paths balanced by assigning a color to each node. "
                     "In this example the root is black and both children are red. "
                     "Smaller values appear on the left, and larger values appear on the right.",
    }
    return {"title": "Understanding red-black trees", "scenes": [scene] * 3}


def schema_keys(value):
    if isinstance(value, dict):
        for key, child in value.items():
            yield key
            yield from schema_keys(child)
    elif isinstance(value, list):
        for child in value:
            yield from schema_keys(child)


@pytest.mark.parametrize("case", ["valid", "extra-field", "wrong-count", "long-label"])
def test_outgoing_schema_is_supported_and_replies_stay_strict(case):
    requests = []

    def respond(request):
        body = json.loads(request.content)
        requests.append(body)
        assert "responseSchema" not in body["generationConfig"]
        schema = body["generationConfig"]["responseJsonSchema"]
        # The real Developer API rejected these nested fields, even though
        # the SDK accepted our Pydantic model before serializing the request.
        assert not {"additionalProperties", "additional_properties", "maxLength", "minLength", "maxItems", "minItems", "default"}.intersection(schema_keys(schema))
        assert "title" in schema["properties"]  # Do not strip actual data fields as schema metadata.
        scenes = schema["properties"]["scenes"]
        scene = schema["$defs"][scenes["items"]["$ref"].rsplit("/", 1)[1]]
        assert "visual" in scene["required"]
        visual = schema["$defs"][scene["properties"]["visual"]["$ref"].rsplit("/", 1)[1]]
        assert visual["properties"]["kind"]["enum"] == ["process", "cycle", "tree", "plot"]
        reply = lesson_reply(extra_field=case == "extra-field")
        if case == "wrong-count":
            reply["scenes"] = reply["scenes"][:2]
        elif case == "long-label":
            reply["scenes"][0]["visual"]["nodes"][0]["label"] = "x" * 29
        return httpx.Response(200, json={"candidates": [{
            "content": {"role": "model", "parts": [{"text": json.dumps(reply)}]},
            "finishReason": "STOP",
        }]})

    with genai.Client(api_key="offline-test-key", http_options=types.HttpOptions(
        client_args={"transport": httpx.MockTransport(respond)},
    )) as client:
        if case != "valid":
            with pytest.raises(ValidationError):
                generate_script(client, "Explain red-black trees", "gemini-test-model")
        else:
            lesson = generate_script(client, "Explain red-black trees", "gemini-test-model")
            assert len(lesson.scenes) == 3
            assert lesson.scenes[0].visual.kind == "tree"
    assert len(requests) == 1
