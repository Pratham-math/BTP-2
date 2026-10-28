"""Untrusted learner programs are sent only to a separately operated Judge0 host."""
import base64
from urllib.parse import urlsplit

import httpx
from server.assessment.grading import matches
from server.lessons.contracts import GradingKey
from server.providers.base import GenerationError


def encoded(text):
    return base64.b64encode(text.encode()).decode("ascii")


def configured_runner(settings):
    if settings.demo_runner:
        from server.local_services import LocalRunner
        return LocalRunner(settings)
    return JudgeRunner(settings)


class JudgeRunner:
    def __init__(self, settings):
        self.settings = settings
        self.client = httpx.Client(timeout=15, follow_redirects=False,
                                   headers={"X-Auth-Token": settings.runner_token})

    def ready(self):
        if not self.settings.runner_url or not self.settings.runner_language_id or not self.settings.runner_verified:
            raise GenerationError("RUNNER_NOT_VERIFIED", "Configure and verify a separate isolated Python runner before enabling code submissions.")
        if urlsplit(self.settings.runner_url).scheme != "https":
            raise GenerationError("RUNNER_NOT_VERIFIED", "The runner connection must use HTTPS.")

    def submit(self, code, key):
        self.ready()
        grading = GradingKey.model_validate(key)
        if not isinstance(code, str) or not code.strip() or len(code) > 16000:
            raise GenerationError("INVALID_CODE", "Submit between 1 and 16000 characters of Python code.")
        tokens = []
        for case in grading.tests:
            response = self.client.post(self.settings.runner_url + "/submissions", params={"base64_encoded": "true", "wait": "false"}, json={
                "source_code": encoded(code), "language_id": self.settings.runner_language_id,
                "stdin": encoded(case.stdin), "cpu_time_limit": 2, "wall_time_limit": 5,
                "memory_limit": 131072, "stack_limit": 8192, "max_processes_and_or_threads": 1,
                "max_file_size": 64, "enable_network": False,
                "enable_per_process_and_thread_time_limit": False,
                "enable_per_process_and_thread_memory_limit": False,
                "redirect_stderr_to_stdout": False,
            })
            response.raise_for_status()
            token = response.json().get("token")
            if not isinstance(token, str) or not 1 <= len(token) <= 128 or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-" for c in token):
                raise GenerationError("RUNNER_FAILED", "The runner did not accept the submission.")
            tokens.append(token)
        return tokens

    def poll(self, tokens, key):
        self.ready()
        grading = GradingKey.model_validate(key)
        if len(tokens) != len(grading.tests):
            raise GenerationError("RUNNER_FAILED", "The runner test record is incomplete.")
        outcomes = []
        for token, case in zip(tokens, grading.tests):
            response = self.client.get(self.settings.runner_url + "/submissions/" + token,
                                       params={"base64_encoded": "true", "fields": "status,stdout"})
            response.raise_for_status()
            value = response.json()
            status = value.get("status", {}).get("id")
            if status in {1, 2}:
                return None
            if status in {None, 13, 14}:
                raise GenerationError("RUNNER_FAILED", "The grading service failed. Your code is saved; retry grading.")
            raw = value.get("stdout") or ""
            if len(raw) > 90000:
                output, passed = "", False
            else:
                try:
                    output = base64.b64decode(raw, validate=True).decode("utf-8", errors="replace")
                except (ValueError, TypeError):
                    raise GenerationError("RUNNER_FAILED", "The runner returned invalid output.") from None
                passed = status == 3 and len(output.encode()) <= 65536 and matches(output, case.expected, grading.comparison, grading.tolerance)
            outcomes.append({"passed": passed, "category": case.category, "essential": case.essential, "weight": case.weight})
        score = sum(x["weight"] for x in outcomes if x["passed"]) / sum(x["weight"] for x in outcomes)
        passed = score >= .8 and all(x["passed"] for x in outcomes if x["essential"])
        return {"passed": passed, "score": score, "feedback": "All required checks passed." if passed else "Some checks did not pass. Use a hint and review your code.",
                "failed_categories": sorted({x["category"] for x in outcomes if not x["passed"]})}

    def close(self):
        self.client.close()
