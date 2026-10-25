"""A small authoritative Python collection, fetched as evidence, with real URLs."""
from html.parser import HTMLParser

import httpx
from server.ingestion.readers import text_blocks
from server.providers.base import GenerationError


class ArticleText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.inside, self.depth, self.parts = False, 0, []

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag == "div" and values.get("role") == "main":
            self.inside, self.depth = True, 1
        elif self.inside and tag == "div":
            self.depth += 1
        if self.inside and tag in {"p", "pre", "h1", "h2", "h3", "li"}:
            self.parts.append("\n\n")

    def handle_endtag(self, tag):
        if self.inside and tag == "div":
            self.depth -= 1
            if self.depth == 0:
                self.inside = False

    def handle_data(self, data):
        if self.inside:
            self.parts.append(data)


def fetch_topic_evidence(topic):
    if not any(word in topic.lower() for word in ("python", "loop", "function", "list", "traversal", "search")):
        raise GenerationError("SOURCES_REQUIRED", "This topic is outside the initial Python source collection. Supply authoritative notes or documents before planning it.")
    urls = ["https://docs.python.org/3/tutorial/controlflow.html", "https://docs.python.org/3/tutorial/datastructures.html"]
    blocks = []
    for number, url in enumerate(urls, 1):
        with httpx.Client(timeout=30, follow_redirects=False) as client:
            response = client.get(url)
            response.raise_for_status()
        if len(response.content) > 2 * 1024 * 1024:
            raise GenerationError("SOURCE_TOO_LARGE", "The curated source exceeded the retrieval limit.")
        parser = ArticleText()
        parser.feed(response.text)
        content = "".join(parser.parts).strip()
        if not content:
            raise GenerationError("SOURCE_UNAVAILABLE", "The authoritative source structure changed. Supply source material explicitly.")
        for block in text_blocks(content, method="official-python-docs", location=url):
            block["id"] = f"python-{number}-{block['id']}"
            blocks.append(block)
    return blocks
