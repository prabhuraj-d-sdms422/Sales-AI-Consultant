from __future__ import annotations

import ipaddress
import re
import socket
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Iterable
from urllib.parse import urljoin, urldefrag, urlparse, urlunparse

import httpx


_ANALYSIS_INTENT_RE = re.compile(r"\b(analy[sz]e|review|audit|check)\b", re.I)
# Broader intent: user shares a URL and asks to read/visit/go through it.
_LINK_INTENT_RE = re.compile(
    r"("
    r"\b(visit|browse|navigate|read|explore|understand)\b"
    r"|"
    r"\b(go\s+through|look\s+through|take\s+a\s+look|have\s+a\s+look|check\s+out)\b"
    r"|"
    r"\b(this|that|our|the)\s+(website|site)\b"
    r"|"
    r"\b(website|site)\s+(here|below|above)\b"
    r"|"
    r"\b(link|url)\s*:\s*https?://"
    r")",
    re.I,
)


def _normalize_host(host: str) -> str:
    h = (host or "").strip().lower().rstrip(".")
    if h.startswith("www."):
        h = h[4:]
    return h


def _is_ip_literal(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
        return True
    except Exception:
        return False


def _is_public_ip(ip: str) -> bool:
    addr = ipaddress.ip_address(ip)
    return not (
        addr.is_private
        or addr.is_loopback
        or addr.is_link_local
        or addr.is_multicast
        or addr.is_unspecified
        or addr.is_reserved
    )


def _resolve_public_ips(host: str) -> list[str]:
    # Resolve both A and AAAA; block if *any* resolution is non-public.
    ips: list[str] = []
    infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    for fam, _type, _proto, _canon, sockaddr in infos:
        ip = sockaddr[0]
        if not _is_public_ip(ip):
            raise ValueError("Host resolves to a non-public IP address")
        ips.append(ip)
    if not ips:
        raise ValueError("Host could not be resolved")
    return sorted(set(ips))


def _is_safe_url(url: str) -> bool:
    p = urlparse(url)
    if p.scheme not in {"http", "https"}:
        return False
    if not p.netloc:
        return False
    host = p.hostname or ""
    if not host:
        return False
    h = _normalize_host(host)
    if h in {"localhost"}:
        return False
    if _is_ip_literal(h):
        return _is_public_ip(h)
    # DNS check (SSRF protection)
    _resolve_public_ips(h)
    return True


def _canonicalize_url(url: str) -> str:
    # Drop fragment, keep query (some sites route via query), but normalize host.
    u, _frag = urldefrag(url)
    p = urlparse(u)
    host = _normalize_host(p.hostname or "")
    netloc = host
    if p.port:
        netloc = f"{host}:{p.port}"
    return urlunparse((p.scheme.lower(), netloc, p.path or "/", p.params, p.query, ""))


class _HtmlTextAndLinksParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._skip_depth = 0
        self.text_parts: list[str] = []
        self.links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        t = tag.lower()
        if t in {"script", "style", "noscript", "svg"}:
            self._skip_depth += 1
            return
        if self._skip_depth:
            return
        if t == "a":
            href = None
            for k, v in attrs:
                if k.lower() == "href" and v:
                    href = v
                    break
            if href:
                self.links.append(href.strip())

        # Add spacing around structural tags so text doesn't glue together.
        if t in {"p", "br", "div", "li", "section", "header", "footer", "h1", "h2", "h3", "h4"}:
            self.text_parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        t = tag.lower()
        if t in {"script", "style", "noscript", "svg"} and self._skip_depth:
            self._skip_depth -= 1
            return
        if self._skip_depth:
            return
        if t in {"p", "div", "li", "section"}:
            self.text_parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        if not data or not data.strip():
            return
        self.text_parts.append(data)


def _extract_title(html: str) -> str:
    m = re.search(r"<title[^>]*>(.*?)</title>", html, re.I | re.S)
    if not m:
        return ""
    title = re.sub(r"\s+", " ", m.group(1)).strip()
    return title[:160]


def _extract_text_and_links(html: str) -> tuple[str, list[str]]:
    parser = _HtmlTextAndLinksParser()
    parser.feed(html)
    text = re.sub(r"\n{3,}", "\n\n", "".join(parser.text_parts))
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = text.strip()
    return text, parser.links


def looks_like_website_analysis_request(text: str) -> bool:
    if not text:
        return False
    if not re.search(r"https?://", text, re.I):
        return False
    return bool(_ANALYSIS_INTENT_RE.search(text) or _LINK_INTENT_RE.search(text))


def _extract_first_url(text: str) -> str | None:
    m = re.search(r"(https?://[^\s)\\]>\"']+)", text or "", re.I)
    return m.group(1) if m else None


def _same_site(url_a: str, url_b: str) -> bool:
    a = urlparse(url_a)
    b = urlparse(url_b)
    return _normalize_host(a.hostname or "") == _normalize_host(b.hostname or "")


def _score_path(path: str) -> int:
    p = (path or "/").lower()
    # Prefer common business pages; higher score means higher priority.
    priorities: list[tuple[int, Iterable[str]]] = [
        (100, ("/",)),
        (95, ("/about", "/about-us", "/company", "/who-we-are")),
        (90, ("/services", "/solutions", "/what-we-do")),
        (85, ("/products", "/product", "/platform")),
        (80, ("/industries", "/use-cases", "/case-studies", "/customers")),
        (75, ("/pricing", "/plans")),
        (70, ("/contact",)),
    ]
    for score, keys in priorities:
        for k in keys:
            if p == k or p.startswith(k + "/"):
                return score
    return 10


@dataclass(frozen=True)
class WebsitePage:
    url: str
    title: str
    text_snippet: str
    word_count: int


@dataclass(frozen=True)
class WebsiteResearchResult:
    start_url: str
    pages: list[WebsitePage]

    @property
    def sources(self) -> list[str]:
        return [p.url for p in self.pages]

    @property
    def summary_text(self) -> str:
        chunks: list[str] = []
        for p in self.pages:
            header = f"URL: {p.url}\nTitle: {p.title or 'n/a'}"
            chunks.append(header + "\n" + p.text_snippet.strip())
        return "\n\n---\n\n".join(chunks).strip()


class WebsiteResearchService:
    def __init__(
        self,
        *,
        max_pages: int = 6,
        timeout_seconds: float = 15.0,
        max_bytes_per_page: int = 600_000,
        max_chars_per_page: int = 6000,
        user_agent: str = "StarkDigitalAIConsultant/1.0 (+public-site-analysis)",
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.max_pages = int(max_pages)
        self.timeout_seconds = float(timeout_seconds)
        self.max_bytes_per_page = int(max_bytes_per_page)
        self.max_chars_per_page = int(max_chars_per_page)
        self.user_agent = user_agent
        self.transport = transport

    async def research_from_text(self, user_text: str) -> WebsiteResearchResult | None:
        url = _extract_first_url(user_text)
        if not url:
            return None
        return await self.research(url)

    async def research(self, start_url: str) -> WebsiteResearchResult:
        start_url = _canonicalize_url(start_url)
        if not _is_safe_url(start_url):
            raise ValueError("Unsafe or unsupported URL")

        visited: set[str] = set()
        to_visit: list[str] = [start_url]
        pages: list[WebsitePage] = []

        async with httpx.AsyncClient(
            timeout=self.timeout_seconds,
            follow_redirects=True,
            headers={"User-Agent": self.user_agent},
            transport=self.transport,
        ) as client:
            while to_visit and len(pages) < self.max_pages:
                url = to_visit.pop(0)
                url = _canonicalize_url(url)
                if url in visited:
                    continue
                if not _same_site(start_url, url):
                    continue
                if not _is_safe_url(url):
                    continue
                visited.add(url)

                r = await client.get(url)
                ct = (r.headers.get("content-type") or "").lower()
                if "text/html" not in ct:
                    continue

                raw = r.content[: self.max_bytes_per_page]
                html = raw.decode(r.encoding or "utf-8", errors="ignore")
                title = _extract_title(html)
                text, links = _extract_text_and_links(html)
                if not text:
                    continue

                snippet = text[: self.max_chars_per_page].strip()
                wc = len(re.findall(r"\\w+", snippet))
                pages.append(WebsitePage(url=url, title=title, text_snippet=snippet, word_count=wc))

                # Enqueue internal links (best-effort)
                candidates: list[str] = []
                for href in links:
                    if not href or href.startswith(("mailto:", "tel:", "javascript:")):
                        continue
                    abs_url = urljoin(url, href)
                    abs_url = _canonicalize_url(abs_url)
                    if not _same_site(start_url, abs_url):
                        continue
                    candidates.append(abs_url)

                # Prioritize “about/services/etc.” paths.
                candidates = sorted(
                    set(candidates),
                    key=lambda u: (-_score_path(urlparse(u).path), u),
                )
                for c in candidates:
                    if c not in visited and c not in to_visit:
                        to_visit.append(c)

        # Ensure the start_url is first if present.
        pages = sorted(pages, key=lambda p: (0 if p.url == start_url else 1, -_score_path(urlparse(p.url).path)))
        return WebsiteResearchResult(start_url=start_url, pages=pages)

