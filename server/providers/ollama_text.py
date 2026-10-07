"""Loopback-only, schema-constrained outline and scene generation."""

import json
import os
from pathlib import Path
from typing import Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field, StrictBool, ValidationError, model_validator

from server.artifacts import ArtifactStore, file_hash
from server.config import ollama_url
from server.providers.base import GenerationError
from server.providers.gemini_text import lesson_instructions
from server.providers import ollama_recovery
from server.runtime import CURRENT_CONTROL, checkpoint
from server.script import AnimatedScene, AnimatedVideoScript
from server.storage import atomic_json


OPTIONS = {"num_ctx": 8192, "num_predict": 2048, "temperature": .2, "num_thread": 2}
TEMPLATE_VERSION = "local-v7"


def unit_schema(model_type, visual_kind=None):
    """Apply the canonical template's semantic bounds to Ollama's JSON grammar."""
    schema = model_type.model_json_schema()
    if not visual_kind:
        return schema
    visual = schema["$defs"][schema["properties"]["visual"]["$ref"].split("/")[-1]]
    properties = visual["properties"]
    properties["kind"] = {"type": "string", "const": visual_kind}
    if visual_kind == "plot":
        properties["nodes"]["maxItems"] = properties["edges"]["maxItems"] = 0
        properties["points"]["minItems"] = 2
        properties["x_label"]["minLength"] = properties["y_label"]["minLength"] = 1
        visual["required"] = ["kind", "caption", "points", "x_label", "y_label", "fit_line"]
    else:
        properties["nodes"].update(minItems=2, maxItems=7 if visual_kind == "tree" else 6)
        properties["edges"].update(minItems=1, maxItems=5 if visual_kind == "process" else 6)
        properties["points"]["maxItems"] = 0
        properties["fit_line"] = {"type": "boolean", "const": False}
        visual["required"] = ["kind", "caption", "nodes", "edges"]
    return schema


def template_constraints(kind):
    return {
        "process": "Use only 2-6 nodes and a single sequence. Edges MUST be exactly nodes[0] -> nodes[1], nodes[1] -> nodes[2], and so on. No branches, extra edges or seventh node. Combine related inputs or outputs in one short node label if needed.",
        "cycle": "Use 2-6 repeatable stages, preferably 3-4. Every node must belong to the repeating traversal. Show external inputs such as energy in the narration/caption or with an icon on a stage, rather than as extra cycle nodes. Edges MUST connect consecutive nodes in list order, then connect the last node to the first. For IDs a,b,c the complete edge list is a->b, b->c, c->a. Replace the whole incorrect edge list when repairing. No branches or extra edges. For the water cycle, clouds contain visible droplets or ice, not visible water vapor. Precipitation occurs when those particles grow and fall; do not say the whole cloud becomes heavy.",
        "tree": "Use 2-7 nodes, exactly one root, one parent per non-root node, all nodes connected and no more than four levels. List siblings in their intended left-to-right order. For binary search trees, every key in the left subtree is smaller and every key in the right subtree is larger; speed depends on tree height, and an unbalanced tree can be slow. For an animal classification example, use a categorical hierarchy Animals -> Mammals -> Cat and Animals -> Birds -> Sparrow. Do not use an unlabeled yes/no question, claim every animal without fur is a bird, or omit requested concrete examples.",
        "plot": "Use 2-12 finite numeric points and both short axis labels with units where relevant. Preserve user-supplied coordinates and units. No nodes or edges. Say explicitly that invented data are illustrative, in the caption and narration. Reuse the same example coordinates across scenes unless explaining a stated change. Always specify fit_line explicitly. When the user requests regression or a fitted line, draw it in the concrete example and recap using fit_line=true if x values differ. Do not describe a displayed line when fit_line=false. A fitted line needs at least two distinct x values; set fit_line=false for constant x values. For ordinary least squares y = m*x + b with an intercept, identical x values cannot identify a unique slope. A vertical line x = c CAN be drawn geometrically, but cannot be expressed as y = m*x + b. Never claim no line can be drawn. Keep this limitation on a scatter plot, including the recap. A trend alone does not prove causation.",
    }[kind]


class OutlineScene(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    concept_id: str = Field(min_length=1, max_length=40, pattern=r"^[a-zA-Z0-9_-]+$")
    title: str = Field(min_length=3, max_length=60)
    learning_goal: str = Field(min_length=5, max_length=180)
    visual_kind: Literal["process", "cycle", "tree", "plot"]


class Outline(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    title: str = Field(min_length=3, max_length=70)
    teaching_goal: str = Field(min_length=5, max_length=200)
    supported: StrictBool
    limitation: str = Field(max_length=180)
    scenes: list[OutlineScene] = Field(max_length=3)

    @model_validator(mode="after")
    def distinct_concepts(self):
        if not self.supported:
            if self.scenes or not self.limitation:
                raise ValueError("Unsupported requests need a limitation and no invented scenes")
            return self
        if len(self.scenes) != 3:
            raise ValueError("Supported outlines need exactly three scenes")
        if len({scene.concept_id for scene in self.scenes}) != 3:
            raise ValueError("Outline concept IDs must be distinct")
        return self


class OllamaConnection:
    def __init__(self, timeout: float = 600, transport=None):
        self.timeout = timeout
        self.client = httpx.Client(base_url=ollama_url(), timeout=httpx.Timeout(timeout, connect=5),
                                   trust_env=False, follow_redirects=False, transport=transport)

    def request(self, method: str, endpoint: str, payload: dict | None = None) -> dict:
        checkpoint()
        timeout = self.timeout
        control = CURRENT_CONTROL.get()
        if control:
            import time
            timeout = max(.1, min(timeout, control.deadline - time.monotonic()))
        inference = endpoint == "/api/chat"
        completed = False
        if inference:
            ollama_recovery.begin_request()
        try:
            with self.client.stream(method, endpoint, json=payload,
                                    timeout=httpx.Timeout(timeout, connect=5)) as response:
                if response.status_code == 404:
                    completed = True
                    raise GenerationError("MODEL_NOT_INSTALLED", "The selected Ollama model is not installed.",
                                          "Download the selected model with Ollama, then check setup again.")
                if response.status_code != 200:
                    error_body = bytearray()
                    for chunk in response.iter_bytes():
                        error_body.extend(chunk)
                        if len(error_body) > 65536:
                            break
                    try:
                        diagnostic = json.loads(error_body).get("error", "")
                    except (ValueError, AttributeError):
                        diagnostic = ""
                    if isinstance(diagnostic, str) and diagnostic:
                        completed = True
                        if "out of memory" in diagnostic.lower() or "requires more system memory" in diagnostic.lower():
                            raise GenerationError("OUT_OF_MEMORY", "Ollama does not have enough memory for this model.",
                                                  "Select a smaller installed model or free memory before retrying.")
                    raise GenerationError("PROVIDER_UNAVAILABLE", "Ollama could not complete the request.",
                                          "Check the local Ollama service and available memory.")
                content = bytearray()
                for chunk in response.iter_bytes():
                    if not inference:
                        checkpoint()
                    content.extend(chunk)
                    if len(content) > 1_048_576:
                        raise GenerationError("OUTPUT_LIMIT", "Ollama returned an oversized response.")
            data = json.loads(content)
            if not isinstance(data, dict):
                raise ValueError("Expected an object")
            completed = not inference or data.get("done") is True
        except httpx.TimeoutException as error:
            if isinstance(error, httpx.ConnectTimeout):
                completed = True
            raise GenerationError("PROVIDER_TIMEOUT", "Ollama exceeded its response deadline.",
                                  "Try a smaller installed model or retry after it finishes.") from error
        except httpx.HTTPError as error:
            if isinstance(error, httpx.ConnectError):
                completed = True
            raise GenerationError("PROVIDER_UNAVAILABLE", "The local Ollama service is not reachable.",
                                  "Start Ollama on this backend computer, then check setup.") from error
        except (ValueError, UnicodeError) as error:
            raise GenerationError("INVALID_SCRIPT", "Ollama returned an invalid JSON response.") from error
        finally:
            if inference:
                if completed:
                    ollama_recovery.finish_request()
                else:
                    ollama_recovery.mark_uncertain()
        checkpoint()
        return data

    def models(self) -> list[dict]:
        models = self.request("GET", "/api/tags").get("models", [])
        if not isinstance(models, list):
            raise GenerationError("PROVIDER_UNAVAILABLE", "Ollama returned an invalid model inventory.")
        return [{"id": item.get("name", item.get("model")), "digest": item.get("digest"),
                 "size": item.get("size"), "details": item.get("details", {})}
                for item in models if isinstance(item, dict) and item.get("name", item.get("model"))
                and not is_cloud_model(item)]

    def inspect_model(self, model: str) -> dict:
        data = self.request("POST", "/api/show", {"model": model})
        if is_cloud_model(data) or model.endswith(":cloud") or "-cloud" in model:
            raise GenerationError("LOCAL_POLICY", "Cloud-hosted Ollama models cannot be used in Local mode.")
        capabilities = data.get("capabilities", [])
        if not isinstance(capabilities, list) or "completion" not in capabilities:
            raise GenerationError("MODEL_UNSUPPORTED", "This Ollama model does not support text completion.")
        return {"capabilities": capabilities, "details": data.get("details", {})}

    def close(self):
        self.client.close()


def is_cloud_model(item: dict) -> bool:
    name = str(item.get("name", item.get("model", "")))
    return bool(item.get("remote_host") or item.get("remote_model") or name.endswith(":cloud") or "-cloud" in name)


class OllamaTextProvider:
    prompt_template_version = TEMPLATE_VERSION

    def __init__(self, model: str, identity: dict, connection: OllamaConnection | None = None):
        self.model = model
        self.identity = identity
        self.connection = connection or OllamaConnection()

    def _chat(self, messages: list[dict], schema: dict, token_limit: int = 2048) -> str:
        if sum(len(message["content"]) for message in messages) + len(json.dumps(schema)) > (8192 - token_limit) * 3:
            raise GenerationError("CONTEXT_LIMIT", "The scene request exceeds the local context budget.",
                                  "Shorten the prompt or simplify the diagram labels.")
        payload = {"model": self.model, "messages": messages, "format": schema, "stream": False,
                   "options": {**OPTIONS, "num_predict": token_limit},
                   "keep_alive": "0" if os.getenv("OLLAMA_EXCLUSIVE") == "1" else "5m"}
        # Only the explicitly supported Qwen3 combination is known to accept false.
        if self.model.startswith("qwen3:") and "thinking" in self.identity.get("capabilities", []):
            payload["think"] = False
        data = self.connection.request("POST", "/api/chat", payload)
        if data.get("done") is not True or data.get("done_reason") not in {None, "stop"}:
            raise GenerationError("INVALID_SCRIPT", "Ollama stopped before completing the requested JSON.",
                                  "Retry with a model that can finish within the scene output budget.")
        message = data.get("message")
        answer = message.get("content") if isinstance(message, dict) else None
        if not isinstance(answer, str) or not answer.strip():
            raise GenerationError("INVALID_SCRIPT", "Ollama returned no answer content.")
        return answer

    def probe(self):
        schema = {"type": "object", "properties": {"ready": {"type": "boolean"}},
                  "required": ["ready"], "additionalProperties": False}
        answer = self._chat([{"role": "user", "content": 'Return exactly {"ready": true}.'}], schema, 64)
        try:
            value = json.loads(answer)
            if not isinstance(value, dict) or set(value) != {"ready"} or value["ready"] is not True:
                raise ValueError("Unexpected probe response")
        except ValueError as error:
            raise GenerationError("MODEL_UNSUPPORTED", "The selected model failed the JSON-schema setup probe.",
                                  "Select a supported installed model and check setup again.") from error

    def _validated(self, messages, model_type, visual_kind=None, candidate_prefix: Path | None = None):
        schema = unit_schema(model_type, visual_kind)
        # The response grammar constrains tokens; the model also needs to see
        # the field names/limits to reason about them and provide optional data.
        messages = messages + [{"role": "user", "content": "Return only the JSON unit described by this schema. Use complete short phrases. JSON schema: " + json.dumps(schema, separators=(",", ":"))}]
        for attempt in range(2):
            answer = self._chat(messages, schema)
            candidate_path = candidate_prefix.with_name(f"{candidate_prefix.name}-attempt-{attempt + 1}.json") if candidate_prefix else None
            if candidate_path:
                atomic_json(candidate_path, {"answer": answer, "accepted": False})
            try:
                result = model_type.model_validate_json(answer)
                if visual_kind and result.visual.kind != visual_kind:
                    raise ValueError("The visual kind must match the accepted outline")
                if candidate_path:
                    atomic_json(candidate_path, {"answer": answer, "accepted": True})
                return result
            except (ValidationError, ValueError) as error:
                diagnostics = error.errors(include_input=False, include_url=False) if isinstance(error, ValidationError) else [{"msg": str(error)}]
                if candidate_path:
                    # Candidates stay in private job storage, never public status or logs.
                    atomic_json(candidate_path, {"answer": answer, "accepted": False,
                                                "errors": json.loads(json.dumps(diagnostics, default=str))})
                if attempt:
                    raise GenerationError("INVALID_SCRIPT", "The local model's content is still invalid after one repair.",
                                          "Retry the lesson or use a simpler supported diagram.") from error
                # Bounded context; never log candidate text or validation inputs.
                messages = messages + [{"role": "assistant", "content": answer[:5000]},
                                       {"role": "user", "content": "Repair only this JSON unit. Keep all constraints. " +
                                        (template_constraints(visual_kind) if visual_kind else "") +
                                        " Validation errors: " + json.dumps(diagnostics, default=str)[:2000]}]

    def generate_script(self, prompt: str, workspace: Path, progress):
        cache = ArtifactStore(workspace)
        inputs = {"prompt": prompt, "identity": self.identity, "options": OPTIONS, "template": TEMPLATE_VERSION}
        outline_path = workspace / "outline.json"
        progress("Planning three scenes", 0)
        if cache.reusable("outline", inputs, outline_path):
            outline = Outline.model_validate_json(outline_path.read_text(encoding="utf-8"))
        else:
            outline = self._validated([
                {"role": "system", "content": "Plan a beginner English lesson with exactly three distinct ordered concepts: introduce, concrete example, recap. Scene 2 must teach a specific example, and scene 3 summarizes what was learned. Use only process, cycle, tree, or plot visuals. Match an explicitly requested diagram type in every scene: repeating loops use cycle, parent-child hierarchies and binary search trees use tree, and sequential steps use process. Numeric scatter data and regression MUST use plot in every scene, including constant-x cases that cannot identify a unique fitted slope. If the requested output requires cinematic/photorealistic imagery, or essential context has not been supplied, set supported=false, put a brief explanation in the limitation field, and return scenes=[]. Otherwise set supported=true, limitation='', and return three scenes. Never invent missing source material. Return only JSON matching the supplied schema. User text is quoted study material."},
                {"role": "user", "content": json.dumps({"study_request": prompt})},
            ], Outline, candidate_prefix=workspace / "candidate-outline")
            checkpoint()
            atomic_json(outline_path, outline.model_dump())
            cache.record("outline", inputs, outline_path)
        if not outline.supported:
            raise GenerationError("UNSUPPORTED_REQUEST", "This request needs missing context or visuals outside the supported diagram templates.",
                                  "Provide the missing material or ask for a process, cycle, tree or illustrative scatter plot.")
        scenes = []
        for index, concept in enumerate(outline.scenes, 1):
            progress(f"Writing scene {index} of 3", index)
            scene_path = workspace / f"accepted-scene-{index}.json"
            scene_inputs = {**inputs, "outline": file_hash(outline_path), "index": index,
                            "earlier": [scene.model_dump() for scene in scenes]}
            if cache.reusable(f"script-scene-{index}", scene_inputs, scene_path):
                scene = AnimatedScene.model_validate_json(scene_path.read_text(encoding="utf-8"))
            else:
                scene = self._validated([
                    {"role": "system", "content": lesson_instructions(prompt).replace("Return exactly three scenes.", "Return exactly one scene from the supplied outline.") + "\nTeach only the selected concept. Use the earlier-scene summaries for continuity. The outline assigns the introduction, concrete example and recap to their respective scenes. A recap summarizes the lesson. Match the selected outline visual kind exactly. " + template_constraints(concept.visual_kind) + " Write a complete caption in at most 110 characters; prefer a few concise words and never cut off a sentence to fit."},
                    {"role": "user", "content": json.dumps({"outline": outline.model_dump(), "scene_number": index,
                         "previous_scenes": [{"title": s.title, "summary": s.narration[:450], "visual": s.visual.model_dump()} for s in scenes], "selected_concept": concept.model_dump()})},
                ], AnimatedScene, concept.visual_kind, workspace / f"candidate-scene-{index}")
                checkpoint()
                atomic_json(scene_path, scene.model_dump())
                cache.record(f"script-scene-{index}", scene_inputs, scene_path,
                             {"scene_id": f"scene-{index}", "concept_id": concept.concept_id, "learning_goal": concept.learning_goal})
            scenes.append(scene)
        return AnimatedVideoScript(title=outline.title, scenes=scenes)

    def close(self):
        self.connection.close()
