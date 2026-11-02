import re
from html.parser import HTMLParser
from urllib.parse import unquote, urlsplit
from uuid import UUID

from app.schemas import NotionReference


def extract_page_id(url: str) -> UUID | None:
    parsed = urlsplit(url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme not in {"http", "https"} or not any(
        host == domain or host.endswith("." + domain)
        for domain in ("notion.so", "notion.site", "notion.com")
    ):
        return None
    tail = unquote(parsed.path).rstrip("/").rsplit("/", 1)[-1]
    match = re.search(r"([0-9a-fA-F]{32}|[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12})$", tail)
    return UUID(match[1]) if match else None


def without_code_blocks(markdown: str) -> str:
    lines = []
    fence = None
    for line in markdown.splitlines(keepends=True):
        match = re.match(r"^ {0,3}(`{3,}|~{3,})", line)
        if match:
            marker = match[1]
            if fence is None:
                fence = marker
            elif marker[0] == fence[0] and len(marker) >= len(fence) and not line[match.end():].strip():
                fence = None
            continue
        if fence is None:
            lines.append(line)
    # Inline code can document example tags; it is not a real reference.
    return re.sub(r"(`+)(.*?)\1", "", "".join(lines), flags=re.DOTALL)


class ReferenceParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.references: list[NotionReference] = []
        self.current: tuple[str, str, list[str]] | None = None
        self.code_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"code", "pre"}:
            self.code_depth += 1
        if self.code_depth or tag not in {"page", "database", "video", "image", "audio", "file"}:
            return
        attrs = dict(attrs)
        url = attrs.get("url") or attrs.get("src")
        if not url:
            return
        try:
            parsed = urlsplit(url)
            if parsed.scheme not in {"http", "https"} or not parsed.hostname:
                return
        except ValueError:
            return
        self.current = (tag, url, [])

    def handle_data(self, data):
        if self.current is not None and not self.code_depth:
            self.current[2].append(data)

    def handle_endtag(self, tag):
        if tag in {"code", "pre"}:
            self.code_depth = max(0, self.code_depth - 1)
        if self.current is None or tag != self.current[0]:
            return
        kind, url, parts = self.current
        page_id = extract_page_id(url) if kind == "page" else None
        self.references.append(NotionReference(
            kind=kind, title="".join(parts).strip() or None, url=url,
            page_id=page_id, can_register=page_id is not None,
        ))
        self.current = None

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)


def extract_references(markdown: str) -> list[NotionReference]:
    parser = ReferenceParser()
    parser.feed(without_code_blocks(markdown))
    parser.close()
    # Preserve first occurrence order, using page IDs to unify different Notion URLs.
    unique = {}
    for reference in parser.references:
        key = (reference.kind, str(reference.page_id) if reference.page_id else reference.url)
        unique.setdefault(key, reference)
    return list(unique.values())
