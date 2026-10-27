import math
from server.lessons.contracts import GradingKey


def matches(actual: str, expected: str, comparison="trim_lines", tolerance=1e-6):
    if comparison == "exact":
        # print() always ends with a newline; exact still means exact spacing and content.
        return actual.rstrip("\n") == expected.rstrip("\n")
    if comparison == "numeric":
        try:
            values, targets = [float(x) for x in actual.split()], [float(x) for x in expected.split()]
            return bool(values) and len(values) == len(targets) and all(
                math.isfinite(a) and math.isfinite(b) and math.isclose(a, b, rel_tol=tolerance, abs_tol=tolerance)
                for a, b in zip(values, targets))
        except ValueError:
            return False
    return "\n".join(x.rstrip() for x in actual.strip().splitlines()) == "\n".join(x.rstrip() for x in expected.strip().splitlines())


def grade(question, private, answer):
    key = GradingKey.model_validate(private)
    kind = question["kind"]
    tag = None
    if kind == "mcq":
        selected = answer.get("choice")
        if not isinstance(selected, str) or selected not in {x["id"] for x in question["options"]}:
            raise ValueError("Choose one of the available options")
        passed = [selected] == key.correct
        tag = key.misconception_map.get(selected)
    elif kind == "multiple":
        selected = answer.get("choices")
        if not isinstance(selected, list) or any(not isinstance(x, str) for x in selected):
            raise ValueError("Select the applicable options")
        if len(selected) != len(set(selected)) or not set(selected).issubset({x["id"] for x in question["options"]}):
            raise ValueError("Invalid option selection")
        passed = set(selected) == set(key.correct)
    elif kind == "trace":
        output = answer.get("output")
        if not isinstance(output, str) or len(output) > 16000:
            raise ValueError("Enter the predicted output")
        passed = matches(output, key.expected_output, key.comparison, key.tolerance)
    else:
        raise ValueError("Python tasks must be submitted to the isolated runner")
    return {"passed": passed, "score": 1.0 if passed else 0.0,
            "feedback": "Correct." if passed else "Review the concept and try the equivalent check.",
            "misconception": tag}
