"""Credential-free document parser subprocess; no model-authored code executes."""
import json
import socket
import sys
import signal
import subprocess
import tempfile
from pathlib import Path


def deny(*args, **kwargs):
    raise PermissionError("Document parsing has no network access")


def main():
    if hasattr(signal, "SIGALRM"):
        signal.alarm(150)
    socket.socket = deny
    socket.create_connection = deny
    socket.getaddrinfo = deny
    from server.ingestion.readers import extract_document
    from server.providers.base import GenerationError
    try:
        path, kind = Path(sys.argv[1]), sys.argv[2]
        from server.ingestion.previews import pdf_previews
        if kind in {"ppt", "pptx"}:
            # This runs only inside the no-network, credential-free container.
            with tempfile.TemporaryDirectory() as folder:
                profile = Path(folder) / "profile" / "user"
                profile.mkdir(parents=True)
                (profile / "registrymodifications.xcu").write_text('<?xml version="1.0"?><oor:items xmlns:oor="http://openoffice.org/2001/registry"><item oor:path="/org.openoffice.Office.Common/Security/Scripting"><prop oor:name="MacroSecurityLevel" oor:op="fuse"><value>3</value></prop></item></oor:items>', encoding="utf-8")
                subprocess.run(["libreoffice", "-env:UserInstallation=" + (profile.parent).as_uri(), "--headless", "--convert-to", "pdf", "--outdir", folder, str(path)],
                               check=True, timeout=90, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                converted = Path(folder) / (path.stem + ".pdf")
                if kind == 'pptx':
                    evidence, warnings = extract_document(path, kind)
                else:
                    evidence, warnings = extract_document(converted, 'pdf')
                    for block in evidence:
                        block['id'] = block['id'].replace('page-', 'slide-')
                        block["location"] = block["location"].replace("Page", "Converted slide")
                        block["method"] = "libreoffice-pdf-layout"
                previews = pdf_previews(converted, Path(sys.argv[3]).parent)
                if len(previews) != len(evidence):
                    raise GenerationError('CONVERSION_INCOMPLETE', 'The slide/page inventory changed during conversion. No incomplete preview was accepted.')
        else:
            evidence, warnings = extract_document(path, kind)
            previews = pdf_previews(path, Path(sys.argv[3]).parent)
        for block, preview in zip(evidence, previews):
            block['preview_file'] = preview['file']
        if kind == "pdf" and any(x.get("code") == "ocr_required" for x in warnings):
            try:
                from docling.document_converter import DocumentConverter, PdfFormatOption
                from docling.datamodel.base_models import InputFormat
                from docling.datamodel.pipeline_options import PdfPipelineOptions
                options = PdfPipelineOptions(artifacts_path="/models", enable_remote_services=False)
                document = DocumentConverter(format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=options)}).convert(path).document
                markdown = document.export_to_markdown()
                from server.ingestion.readers import text_blocks
                # Keep the original page inventory and require source-by-source
                # correction; OCR text is a supplementary interpretation.
                evidence.extend(text_blocks(markdown, method="docling-ocr", location="OCR supplement; verify original page locations"))
                warnings.append({"code": "ocr_confirmation_required", "critical": True, "location": "All OCR text"})
                for block in evidence:
                    if block["method"] == "docling-ocr": block["uncertainty"] = ["ocr_confirmation_required"]
            except ImportError:
                pass  # The original per-page warnings remain blocking and visible.
        output = {"evidence": evidence, "warnings": warnings, "previews": previews}
    except GenerationError as error:
        output = {"error_code": error.code, "message": str(error)}
    Path(sys.argv[3]).write_text(json.dumps(output, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
