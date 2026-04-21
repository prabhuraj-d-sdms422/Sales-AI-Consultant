import pytest
import httpx

from app.services.website_research_service import WebsiteResearchService, looks_like_website_analysis_request


def _html(title: str, body: str, links: list[str] | None = None) -> str:
    links = links or []
    a_tags = "\n".join([f"<a href='{h}'>link</a>" for h in links])
    return f"""<!doctype html>
<html>
  <head><title>{title}</title></head>
  <body>
    <nav>nav stuff</nav>
    <main>
      <h1>{title}</h1>
      <p>{body}</p>
      {a_tags}
    </main>
    <script>console.log('x')</script>
  </body>
</html>
"""


@pytest.mark.asyncio
async def test_blocks_localhost_and_private_ips():
    svc = WebsiteResearchService()
    with pytest.raises(ValueError):
        await svc.research("http://localhost:8000/")
    with pytest.raises(ValueError):
        await svc.research("http://127.0.0.1/")
    with pytest.raises(ValueError):
        await svc.research("http://10.0.0.5/")


@pytest.mark.asyncio
async def test_crawls_internal_pages_and_respects_cap(monkeypatch):
    requested: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(str(request.url))
        url = str(request.url)
        if url == "https://example.com/":
            return httpx.Response(
                200,
                headers={"content-type": "text/html; charset=utf-8"},
                text=_html(
                    "Home",
                    "We provide logistics software and dispatch automation.",
                    links=["/about", "/services", "https://other.com/evil", "/pricing"],
                ),
            )
        if url == "https://example.com/about":
            return httpx.Response(
                200,
                headers={"content-type": "text/html; charset=utf-8"},
                text=_html("About", "We work with fleet operators."),
            )
        if url == "https://example.com/services":
            return httpx.Response(
                200,
                headers={"content-type": "text/html; charset=utf-8"},
                text=_html("Services", "Automation, integrations, dashboards."),
            )
        if url == "https://example.com/pricing":
            return httpx.Response(
                200,
                headers={"content-type": "text/html; charset=utf-8"},
                text=_html("Pricing", "Contact us for pricing."),
            )
        return httpx.Response(404, text="not found")

    transport = httpx.MockTransport(handler)

    # Avoid real DNS lookups in unit tests; treat example.com as safe.
    import app.services.website_research_service as mod

    monkeypatch.setattr(mod, "_resolve_public_ips", lambda host: ["93.184.216.34"])

    svc = WebsiteResearchService(max_pages=3, transport=transport)
    result = await svc.research("https://example.com/")

    assert result.start_url == "https://example.com/"
    assert len(result.pages) == 3
    assert all(p.url.startswith("https://example.com") for p in result.pages)
    assert all("other.com" not in p.url for p in result.pages)
    # Ensure we did not request external link.
    assert all("other.com" not in u for u in requested)


@pytest.mark.asyncio
async def test_non_html_is_ignored(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "application/json"}, text='{"ok":true}')

    transport = httpx.MockTransport(handler)
    import app.services.website_research_service as mod

    monkeypatch.setattr(mod, "_resolve_public_ips", lambda host: ["93.184.216.34"])

    svc = WebsiteResearchService(max_pages=2, transport=transport)
    result = await svc.research("https://example.com/")
    assert result.pages == []


def test_looks_like_website_request_detects_go_through_phrase():
    assert looks_like_website_analysis_request(
        "This is the website you can go through https://example.com/about"
    )


def test_looks_like_website_request_requires_url():
    assert not looks_like_website_analysis_request("Please go through our website")


def test_looks_like_website_request_still_detects_analyze():
    assert looks_like_website_analysis_request("Please analyze https://example.com")

