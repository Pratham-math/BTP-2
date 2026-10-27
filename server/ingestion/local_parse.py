"""Local-profile parser subprocess: no network, writes one JSON result file."""
import json
import socket
import sys
from pathlib import Path


def deny(*args, **kwargs):
    raise PermissionError("Document parsing has no network access")


def main():
    socket.socket = socket.create_connection = socket.getaddrinfo = deny
    from server.ingestion.previews import pdf_previews
    from server.ingestion.readers import extract_document
    from server.providers.base import GenerationError
    path, kind, result = Path(sys.argv[1]), sys.argv[2], Path(sys.argv[3])
    try:
        evidence, warnings = extract_document(path, kind)
        if kind == "pdf":
            for block, preview in zip(evidence, pdf_previews(path, result.parent)):
                block["preview_file"] = preview["file"]
        for block in evidence:
            # Slide figures are reported, not blocking: students cannot redraw them.
            if "figure_confirmation_required" in block["uncertainty"]:
                block["uncertainty"].remove("figure_confirmation_required")
                warnings.append({"location": block["location"], "code": "figure_not_read", "critical": False})
        output = {"evidence": evidence, "warnings": warnings}
    except GenerationError as error:
        output = {"error_code": error.code, "message": str(error)}
    result.write_text(json.dumps(output, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
