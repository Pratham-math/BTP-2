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


def wikipedia_evidence(topic, *, limit=40000):
    api = "https://en.wikipedia.org/w/api.php"
    headers = {"User-Agent": "BTP2-Learning-Studio/1.0 (https://github.com/Pratham-math/BTP-2; college project)"}
    with httpx.Client(timeout=30, follow_redirects=False, headers=headers) as client:
        found = client.get(api, params={"action": "query", "list": "search", "srsearch": topic, "srlimit": 1, "format": "json"})
        found.raise_for_status()
        query = found.json().get("query", {})
        hits = query.get("search", [])
        suggestion = query.get("searchinfo", {}).get("suggestion")
        if not hits and suggestion:
            # A misspelt topic ("bianry search") finds nothing; Wikipedia suggests the fix.
            found = client.get(api, params={"action": "query", "list": "search", "srsearch": suggestion, "srlimit": 1, "format": "json"})
            found.raise_for_status()
            hits = found.json().get("query", {}).get("search", [])
        if not hits:
            raise GenerationError("SOURCES_REQUIRED", "No reference article matched this topic. Add notes or a document instead.")
        title = hits[0]["title"]
        page = client.get(api, params={"action": "query", "prop": "extracts", "explaintext": 1, "titles": title, "redirects": 1, "format": "json"})
        page.raise_for_status()
    text = next(iter(page.json()["query"]["pages"].values())).get("extract", "").strip()
    if not text:
        raise GenerationError("SOURCE_UNAVAILABLE", "The reference article was empty. Add notes or a document instead.")
    # ponytail: keep the article's opening sections; very long articles exceed one lesson anyway.
    text = text.split("\n== See also ==")[0].split("\n== References ==")[0][:limit]
    url = "https://en.wikipedia.org/wiki/" + title.replace(" ", "_")
    blocks = text_blocks(text, method="wikipedia", location=url)
    for block in blocks:
        block["id"] = "wiki-" + block["id"]
    return blocks


def fetch_topic_evidence(topic):
    if "python" not in topic.lower():
        return wikipedia_evidence(topic)
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
