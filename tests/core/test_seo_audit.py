from reckon_core.crawler import CrawlResult, SitemapEvidence
from reckon_core.seo_audit import audit_homepage


def test_homepage_audit_emits_evidence_backed_findings_in_priority_order() -> None:
    result = CrawlResult(
        final_url="https://example.com/",
        status_code=503,
        content_type="text/html; charset=utf-8",
        bytes_read=0,
        title=None,
        redirect_count=0,
        meta_description=None,
        h1_count=0,
    )

    audit = audit_homepage(result)

    assert audit.version == "homepage-v4"
    assert [finding.code for finding in audit.findings] == [
        "non_success_http_status",
        "missing_title",
        "missing_h1",
        "missing_meta_description",
    ]
    assert all(finding.source_url == result.final_url for finding in audit.findings)
    assert all(finding.confidence == "high" for finding in audit.findings)
    assert audit.findings[0].evidence == "Observed HTTP status: 503."


def test_homepage_audit_reconciles_noindex_signals_and_canonical_targets() -> None:
    result = CrawlResult(
        final_url="https://example.com/",
        status_code=200,
        content_type="text/html",
        bytes_read=100,
        title="Example",
        redirect_count=0,
        meta_description="Summary",
        h1_count=1,
        meta_robots_noindex=False,
        x_robots_noindex=True,
        canonical_url="https://other.example.net/preferred",
        canonical_link_count=2,
    )

    audit = audit_homepage(result)

    assert audit.version == "homepage-v4"
    assert [finding.code for finding in audit.findings] == [
        "noindex_directive",
        "cross_host_canonical",
        "multiple_canonical_links",
    ]
    assert (
        audit.findings[0].evidence
        == "X-Robots-Tag contains noindex; robots meta does not contain noindex."
    )


def test_homepage_audit_reports_bounded_structural_and_alt_evidence() -> None:
    result = CrawlResult(
        final_url="https://example.com/",
        status_code=200,
        content_type="text/html",
        bytes_read=100,
        title="Example",
        redirect_count=0,
        meta_description="Summary",
        h1_count=1,
        h2_count=0,
        internal_link_count=0,
        image_count=3,
        missing_alt_text_count=2,
    )

    audit = audit_homepage(result)

    assert [finding.code for finding in audit.findings] == [
        "images_missing_alt_text",
        "missing_h2",
        "no_internal_links",
    ]


def test_homepage_audit_reports_present_but_invalid_canonical_link() -> None:
    result = CrawlResult(
        final_url="https://example.com/",
        status_code=200,
        content_type="text/html",
        bytes_read=100,
        title="Example",
        redirect_count=0,
        meta_description="Summary",
        h1_count=1,
        canonical_url=None,
        canonical_link_count=1,
    )

    audit = audit_homepage(result)

    assert [finding.code for finding in audit.findings] == ["invalid_canonical_url"]


def test_homepage_audit_omits_findings_for_present_fields_and_non_html_pages() -> None:
    html_result = CrawlResult(
        final_url="https://example.com/",
        status_code=200,
        content_type="text/html",
        bytes_read=100,
        title="Example",
        redirect_count=0,
        meta_description="Summary",
        h1_count=1,
    )
    non_html_result = CrawlResult(
        final_url="https://example.com/data",
        status_code=200,
        content_type="application/json",
        bytes_read=100,
        title=None,
        redirect_count=0,
    )

    assert audit_homepage(html_result).findings == ()
    assert audit_homepage(non_html_result).findings == ()


def test_homepage_audit_reports_empty_and_incomplete_sitemap_evidence() -> None:
    result = CrawlResult(
        final_url="https://example.com/",
        status_code=200,
        content_type="text/html",
        bytes_read=100,
        title="Example",
        redirect_count=0,
        meta_description="Summary",
        h1_count=1,
        sitemap_evidence=(
            SitemapEvidence(
                url="https://example.com/empty.xml",
                status="fetched",
                http_status_code=200,
                document_type="urlset",
                url_count=0,
                rejected_count=0,
            ),
            SitemapEvidence(
                url="https://example.com/index.xml",
                status="fetched",
                http_status_code=200,
                document_type="sitemapindex",
                child_sitemap_count=2,
                child_sitemap_urls=("https://example.com/child.xml",),
                rejected_count=1,
                truncated=True,
            ),
            SitemapEvidence(
                url="https://example.com/child.xml",
                status="fetch_limit_reached",
            ),
        ),
    )

    audit = audit_homepage(result)

    assert [finding.code for finding in audit.findings] == [
        "empty_sitemap",
        "incomplete_sitemap_analysis",
    ]
    assert audit.findings[0].source_url == "https://example.com/empty.xml"
    assert audit.findings[1].source_url == "https://example.com/index.xml"
    assert audit.findings[1].evidence == (
        "fetch_limit_reached: 1, fetched: 1; rejected entries: 1; "
        "truncated documents: 1"
    )


def test_homepage_audit_does_not_call_rejected_sitemap_entries_empty() -> None:
    result = CrawlResult(
        final_url="https://example.com/",
        status_code=200,
        content_type="text/html",
        bytes_read=100,
        title="Example",
        redirect_count=0,
        meta_description="Summary",
        h1_count=1,
        sitemap_evidence=(
            SitemapEvidence(
                url="https://example.com/sitemap.xml",
                status="fetched",
                http_status_code=200,
                document_type="urlset",
                url_count=0,
                rejected_count=4,
            ),
        ),
    )

    audit = audit_homepage(result)

    assert [finding.code for finding in audit.findings] == [
        "incomplete_sitemap_analysis",
    ]


def test_homepage_audit_reports_absent_homepage_and_canonical_in_complete_sitemaps() -> None:
    result = CrawlResult(
        final_url="https://example.com/",
        status_code=200,
        content_type="text/html",
        bytes_read=100,
        title="Example",
        redirect_count=0,
        meta_description="Summary",
        h1_count=1,
        canonical_url="https://example.com/preferred",
        canonical_link_count=1,
        sitemap_urls=("https://example.com/sitemap.xml",),
        sitemap_declaration_count=1,
        sitemap_rejected_count=0,
        sitemap_discovery_truncated=False,
        sitemap_evidence=(
            SitemapEvidence(
                url="https://example.com/sitemap.xml",
                status="fetched",
                http_status_code=200,
                document_type="urlset",
                url_count=2,
                homepage_listed=False,
                canonical_url_listed=False,
                rejected_count=0,
            ),
        ),
    )

    audit = audit_homepage(result)

    assert [finding.code for finding in audit.findings] == [
        "canonical_not_in_sitemap",
        "homepage_not_in_sitemap",
    ]


def test_homepage_audit_does_not_claim_missing_membership_for_incomplete_sitemaps() -> None:
    result = CrawlResult(
        final_url="https://example.com/",
        status_code=200,
        content_type="text/html",
        bytes_read=100,
        title="Example",
        redirect_count=0,
        meta_description="Summary",
        h1_count=1,
        sitemap_urls=("https://example.com/sitemap.xml",),
        sitemap_declaration_count=1,
        sitemap_rejected_count=0,
        sitemap_discovery_truncated=False,
        sitemap_evidence=(
            SitemapEvidence(
                url="https://example.com/sitemap.xml",
                status="fetched",
                http_status_code=200,
                document_type="urlset",
                url_count=2,
                homepage_listed=False,
                rejected_count=0,
                truncated=True,
            ),
        ),
    )

    audit = audit_homepage(result)

    assert [finding.code for finding in audit.findings] == [
        "incomplete_sitemap_analysis",
    ]


def test_homepage_audit_reports_rejected_or_truncated_sitemap_discovery() -> None:
    result = CrawlResult(
        final_url="https://example.com/",
        status_code=200,
        content_type="text/html",
        bytes_read=100,
        title="Example",
        redirect_count=0,
        meta_description="Summary",
        h1_count=1,
        sitemap_urls=(),
        sitemap_declaration_count=101,
        sitemap_rejected_count=2,
        sitemap_discovery_truncated=True,
        sitemap_evidence=(),
    )

    audit = audit_homepage(result)

    assert [finding.code for finding in audit.findings] == [
        "incomplete_sitemap_analysis",
    ]
    assert audit.findings[0].source_url == result.final_url
    assert audit.findings[0].evidence == (
        "rejected sitemap declarations: 2; sitemap discovery was truncated"
    )
