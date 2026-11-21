from reckon_core.crawler import CrawlResult, PageEvidence
from reckon_core.seo_engines import audit_engine


def crawl() -> CrawlResult:
    return CrawlResult(
        final_url="https://example.com/",
        status_code=200,
        content_type="text/html",
        bytes_read=240,
        title=None,
        redirect_count=0,
        meta_description=None,
        h1_count=0,
        h2_count=0,
        internal_link_count=2,
        image_count=3,
        missing_alt_text_count=2,
        canonical_url="https://example.com/",
        canonical_link_count=1,
        robots_status_code=200,
        sitemap_urls=("https://example.com/sitemap.xml",),
        sitemap_declaration_count=1,
        sitemap_rejected_count=0,
        sitemap_discovery_truncated=False,
        sitemap_evidence=(),
        internal_urls=("https://example.com/product/test", "https://example.com/category/shoes"),
        page_evidence=(
            PageEvidence(
                url="https://example.com/product/test",
                status="fetched",
                http_status_code=200,
                title="Test product",
                h1_count=1,
                h2_count=2,
                image_count=2,
                missing_alt_text_count=1,
            ),
        ),
    )


def test_all_staged_engines_return_typed_evidence_bound_audits() -> None:
    result = crawl()
    engines = (
        "keywords",
        "content_studio",
        "linkpilot",
        "local_seo",
        "ecommerce",
        "enterprise",
        "media_query",
        "emerging_geo",
    )
    for engine in engines:
        audit = audit_engine(result, engine)
        assert audit.engine == engine
        assert audit.version == f"{engine}-v1"
        assert audit.coverage in {"complete", "partial", "unavailable"}
        assert audit.findings
        assert all(finding.confidence in {"high", "medium"} for finding in audit.findings)


def test_provider_dependent_engines_surface_explicit_unavailable_state() -> None:
    result = crawl()
    linkpilot = audit_engine(result, "linkpilot")
    local = audit_engine(result, "local_seo")
    assert linkpilot.coverage == "unavailable"
    assert local.coverage == "unavailable"
    assert linkpilot.findings[0].code == "external_link_data_not_configured"
    assert local.findings[0].code == "local_business_data_not_configured"


def test_ecommerce_and_enterprise_use_only_observed_crawl_signals() -> None:
    result = crawl()
    ecommerce = audit_engine(result, "ecommerce")
    enterprise = audit_engine(result, "enterprise")
    assert ecommerce.findings[0].code == "ecommerce_urls_detected"
    assert "product" in ecommerce.findings[0].source_url
    assert enterprise.findings


def test_media_and_emerging_geo_use_partial_or_corroborated_evidence() -> None:
    result = crawl()
    media = audit_engine(result, "media_query")
    geo = audit_engine(result, "emerging_geo")
    assert media.coverage == "partial"
    assert media.findings[0].code == "media_alt_text_missing"
    assert geo.coverage == "partial"
