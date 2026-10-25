"""Page rendering for the credential-free parser container only."""
import math
from contextlib import closing
from pathlib import Path

from server.providers.base import GenerationError


def pdf_previews(path, output):
    import pypdfium2 as pdfium
    output = Path(output)
    images, total = [], 0
    with pdfium.PdfDocument(path) as document:
        if not 1 <= len(document) <= 200:
            raise GenerationError('SOURCE_BATCH_REQUIRED', 'Render 1–200 pages per explicit source batch; no pages were omitted.')
        for index in range(len(document)):
            with closing(document[index]) as page:
                width, height = page.get_size()
                if not all(math.isfinite(x) and x > 0 for x in (width, height)):
                    raise GenerationError('INVALID_SOURCE', 'A page has invalid rendering dimensions.')
                scale = min(1.5, 1600 / max(width, height))
                name = f'page-{index + 1}.png'
                with closing(page.render(scale=scale)) as bitmap:
                    image = bitmap.to_pil()
                    try:
                        image.save(output / name, format='PNG')
                    finally:
                        image.close()
                total += (output / name).stat().st_size
                if total > 128 * 1024 * 1024:
                    raise GenerationError('SOURCE_BATCH_REQUIRED', 'Page previews exceed the batch storage budget. Split this document; no partial import was confirmed.')
                images.append({'file': name, 'page': index + 1})
    return images
