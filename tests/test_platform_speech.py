"""Current SDK request serialization only; no live narration-quality claim."""
import base64
import json

from google import genai
from google.genai import types
import httpx

from server.providers.gemini_tts import call_tts_with_retry


def test_platform_speech_keeps_directions_out_of_verbatim_transcript():
    requests, admitted = [], []
    def respond(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, json={"id": "fixture-audio", "status": "completed", "steps": [{"type": "model_output", "content": [{"type": "audio", "data": base64.b64encode(b"fixture-not-real-audio").decode(), "mime_type": "audio/wav"}]}]})
    with genai.Client(api_key="fixture-not-a-key", http_options=types.HttpOptions(client_args={"transport": httpx.MockTransport(respond)})) as client:
        result = call_tts_with_retry(client, "fixture-model", "Add two to the total.", "Kore", metadata_style=True, admit=lambda: admitted.append(True))
    content = requests[0]["input"][0]["content"][0]
    assert content["text"] == "Add two to the total."
    assert content["annotations"][0]["type"] == "speech_metadata"
    assert requests[0]["response_format"] == {"type": "audio"}
    assert result.output_audio and len(admitted) == 1
