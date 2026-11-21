from dataclasses import dataclass
from typing import Literal
from urllib.parse import urlsplit

from reckon_core.crawler import CrawlResult

HomepageFindingCode = Literal[
    "non_success_http_status",
    "missing_title",
    "missing_meta_description",
    "missing_h1",
    "noindex_directive",
    "invalid_canonical_url",
    "multiple_canonical_links",
    "cross_host_canonical",
    "empty_sitemap",
    "incomplete_sitemap_analysis",
    "homepage_not_in_sitemap",
    "canonical_not_in_sitemap",
    "missing_h2",
    "no_internal_links",
    "images_missing_alt_text",
]
FindingImpact = Literal["high", "medium", "low"]
FindingConfidence = Literal["high"]
FindingEffort = Literal["low", "medium"]

HOMEPAGE_AUDIT_VERSION = "homepage-v4"

_IMPACT_ORDER: dict[FindingImpact, int] = {
    "high": 0,
    "medium": 1,
    "low": 2,
}
_CONFIDENCE_ORDER: dict[FindingConfidence, int] = {"high": 0}
_EFFORT_ORDER: dict[FindingEffort, int] = {"low": 0, "medium": 1}


@dataclass(frozen=True, slots=True)
class HomepageFinding:
    code: HomepageFindingCode
    impact: FindingImpact
    confidence: FindingConfidence
    effort: FindingEffort
    source_url: str
    summary: str
    evidence: str
    recommendation: str
    verification: str


@dataclass(frozen=True, slots=True)
class HomepageAudit:
    version: str
    findings: tuple[HomepageFinding, ...]


def _sitemap_evidence_is_complete(result: CrawlResult) -> bool:
    evidence = result.sitemap_evidence or ()
    if (
        not evidence
        or result.sitemap_discovery_truncated is not False
        or result.sitemap_rejected_count != 0
    ):
        return False

    evidence_by_url = {item.url: item for item in evidence}
    for item in evidence:
        if (
            item.status != "fetched"
            or item.truncated
            or item.rejected_count != 0
        ):
            return False
        for child_url in item.child_sitemap_urls:
            child_evidence = evidence_by_url.get(child_url)
            if child_evidence is None or child_evidence.status != "fetched":
                return False
    return True


def audit_homepage(result: CrawlResult) -> HomepageAudit:
    findings: list[HomepageFinding] = []
    if not 200 <= result.status_code < 300:
        findings.append(
            HomepageFinding(
                code="non_success_http_status",
                impact="high",
                confidence="high",
                effort="medium",
                source_url=result.final_url,
                summary="The homepage returned a non-success HTTP status.",
                evidence=f"Observed HTTP status: {result.status_code}.",
                recommendation=(
                    "Confirm the homepage should be available at this URL and "
                    "returns an appropriate success status."
                ),
                verification=(
                    "Fetch the verified homepage again and confirm its intended "
                    "HTTP status."
                ),
            )
        )

    if result.meta_robots_noindex is True or result.x_robots_noindex is True:
        x_robots_state = (
            "contains noindex"
            if result.x_robots_noindex is True
            else "does not contain noindex"
            if result.x_robots_noindex is False
            else "was not present"
        )
        meta_robots_state = (
            "contains noindex"
            if result.meta_robots_noindex is True
            else "does not contain noindex"
            if result.meta_robots_noindex is False
            else "was not present"
        )
        findings.append(
            HomepageFinding(
                code="noindex_directive",
                impact="high",
                confidence="high",
                effort="low",
                source_url=result.final_url,
                summary="A noindex directive was observed for the homepage.",
                evidence=(
                    f"X-Robots-Tag {x_robots_state}; robots meta {meta_robots_state}."
                ),
                recommendation=(
                    "Confirm the homepage is intentionally excluded from indexing; "
                    "remove the directive from the source that emitted it if not."
                ),
                verification=(
                    "Fetch the homepage again and inspect both X-Robots-Tag and "
                    "robots meta directives."
                ),
            )
        )

    canonical_count = result.canonical_link_count
    if canonical_count is not None and canonical_count > 1:
        findings.append(
            HomepageFinding(
                code="multiple_canonical_links",
                impact="low",
                confidence="high",
                effort="low",
                source_url=result.final_url,
                summary="Multiple canonical links were detected.",
                evidence=f"Observed {canonical_count} rel=canonical links.",
                recommendation=(
                    "Review the canonical declarations and retain one intended "
                    "preferred URL."
                ),
                verification=(
                    "Fetch the homepage HTML and confirm it contains one intended "
                    "rel=canonical link."
                ),
            )
        )
    if canonical_count is not None and canonical_count > 0:
        if result.canonical_url is None:
            findings.append(
                HomepageFinding(
                    code="invalid_canonical_url",
                    impact="medium",
                    confidence="high",
                    effort="low",
                    source_url=result.final_url,
                    summary=(
                        "The canonical link did not resolve to a valid HTTP(S) URL."
                    ),
                    evidence=(
                        "A rel=canonical link was present, but its href could not be "
                        "normalized safely."
                    ),
                    recommendation=(
                        "Review the canonical href and use a valid absolute or "
                        "page-relative HTTP(S) URL without credentials."
                    ),
                    verification=(
                        "Fetch the homepage and confirm its first canonical href "
                        "resolves to the intended HTTP(S) URL."
                    ),
                )
            )
        else:
            try:
                page_host = urlsplit(result.final_url).hostname
                canonical_host = urlsplit(result.canonical_url).hostname
            except ValueError:
                page_host = None
                canonical_host = None
            if (
                page_host is not None
                and canonical_host is not None
                and page_host.casefold() != canonical_host.casefold()
            ):
                findings.append(
                    HomepageFinding(
                        code="cross_host_canonical",
                        impact="medium",
                        confidence="high",
                        effort="low",
                        source_url=result.final_url,
                        summary="The canonical link points to a different host.",
                        evidence=(
                            f"Observed canonical URL: {result.canonical_url}."
                        ),
                        recommendation=(
                            "Confirm the cross-host canonical is intentional and "
                            "targets the preferred page."
                        ),
                        verification=(
                            "Fetch the homepage again and verify the canonical host "
                            "matches the intended destination."
                        ),
                    )
                )

    media_type = result.content_type.split(";", 1)[0].strip().lower()
    if media_type in {"text/html", "application/xhtml+xml"}:
        if not (result.title or "").strip():
            findings.append(
                HomepageFinding(
                    code="missing_title",
                    impact="medium",
                    confidence="high",
                    effort="low",
                    source_url=result.final_url,
                    summary="No page title was detected in the homepage HTML.",
                    evidence="The fetched HTML contained no non-empty <title> text.",
                    recommendation=(
                        "Add a concise title that accurately describes the homepage."
                    ),
                    verification=(
                        "Fetch the homepage HTML and confirm it contains a non-empty "
                        "<title> element."
                    ),
                )
            )
        if not (result.meta_description or "").strip():
            findings.append(
                HomepageFinding(
                    code="missing_meta_description",
                    impact="low",
                    confidence="high",
                    effort="low",
                    source_url=result.final_url,
                    summary="No meta description was detected in the homepage HTML.",
                    evidence=(
                        'The fetched HTML contained no non-empty <meta name="description">.'
                    ),
                    recommendation=(
                        "Consider adding a concise description that summarizes the "
                        "homepage."
                    ),
                    verification=(
                        'Fetch the homepage HTML and confirm it contains a non-empty '
                        '<meta name="description" content="...">.'
                    ),
                )
            )
        if result.h1_count == 0:
            findings.append(
                HomepageFinding(
                    code="missing_h1",
                    impact="low",
                    confidence="high",
                    effort="low",
                    source_url=result.final_url,
                    summary="No H1 heading was detected in the homepage HTML.",
                    evidence="The fetched HTML contained zero <h1> elements.",
                    recommendation=(
                        "Check whether the homepage should have a primary visible "
                        "heading and add one if appropriate."
                    ),
                    verification=(
                        "Fetch the homepage HTML and confirm a primary <h1> appears "
                        "when the page design calls for one."
                    ),
                )
            )
        if result.h2_count == 0:
            findings.append(
                HomepageFinding(
                    code="missing_h2",
                    impact="low",
                    confidence="high",
                    effort="low",
                    source_url=result.final_url,
                    summary="No H2 subheadings were detected in the homepage HTML.",
                    evidence="The fetched HTML contained zero <h2> elements.",
                    recommendation=(
                        "Review the homepage structure and add descriptive H2 "
                        "sections where useful for readers."
                    ),
                    verification=(
                        "Fetch the homepage HTML and confirm H2 elements organize "
                        "the intended content sections."
                    ),
                )
            )
        if result.internal_link_count == 0:
            findings.append(
                HomepageFinding(
                    code="no_internal_links",
                    impact="low",
                    confidence="high",
                    effort="low",
                    source_url=result.final_url,
                    summary="No same-host internal links were detected on the homepage.",
                    evidence="The fetched HTML contained zero same-host HTTP(S) links.",
                    recommendation=(
                        "Review key navigation and linking paths and add relevant "
                        "links to important pages where appropriate."
                    ),
                    verification=(
                        "Fetch the homepage HTML and confirm important same-host "
                        "navigation links are present."
                    ),
                )
            )
        if (result.missing_alt_text_count or 0) > 0:
            findings.append(
                HomepageFinding(
                    code="images_missing_alt_text",
                    impact="medium",
                    confidence="high",
                    effort="low",
                    source_url=result.final_url,
                    summary="Some homepage images omit alternative text.",
                    evidence=(
                        f"{result.missing_alt_text_count} image(s) had no "
                        "non-empty alt attribute."
                    ),
                    recommendation=(
                        "Provide concise alternative text for meaningful images "
                        "and use empty alt text for decorative images."
                    ),
                    verification=(
                        "Fetch the homepage HTML and verify every image has an "
                        "appropriate alt attribute."
                    ),
                )
            )

    sitemap_evidence = result.sitemap_evidence or ()
    for sitemap in sitemap_evidence:
        if (
            sitemap.status == "fetched"
            and sitemap.rejected_count == 0
            and (
                sitemap.document_type == "urlset"
                and sitemap.url_count == 0
                or sitemap.document_type == "sitemapindex"
                and sitemap.child_sitemap_count == 0
            )
        ):
            findings.append(
                HomepageFinding(
                    code="empty_sitemap",
                    impact="low",
                    confidence="high",
                    effort="low",
                    source_url=sitemap.url,
                    summary="The sitemap contains no accepted entries.",
                    evidence=(
                        f"Parsed {sitemap.document_type}; no unique same-host "
                        "URL or child-sitemap entries were found."
                    ),
                    recommendation=(
                        "Confirm the empty sitemap is intentional; if not, publish "
                        "the intended canonical URLs or sitemap references."
                    ),
                    verification=(
                        "Fetch this sitemap again and confirm it contains its "
                        "intended same-host entries."
                    ),
                )
            )

    incomplete_sitemaps = [
        sitemap
        for sitemap in sitemap_evidence
        if (
            sitemap.status != "fetched"
            or sitemap.truncated
            or (sitemap.rejected_count or 0) > 0
        )
    ]
    discovery_rejected_count = result.sitemap_rejected_count or 0
    discovery_was_truncated = result.sitemap_discovery_truncated is True
    if incomplete_sitemaps or discovery_rejected_count or discovery_was_truncated:
        status_counts: dict[str, int] = {}
        for sitemap in incomplete_sitemaps:
            status_counts[sitemap.status] = (
                status_counts.get(sitemap.status, 0) + 1
            )
        status_summary = ", ".join(
            f"{status}: {count}"
            for status, count in sorted(status_counts.items())
        )
        rejected_count = sum(
            sitemap.rejected_count or 0 for sitemap in incomplete_sitemaps
        )
        truncated_count = sum(
            1 for sitemap in incomplete_sitemaps if sitemap.truncated
        )
        details = [status_summary] if status_summary else []
        if rejected_count:
            details.append(f"rejected entries: {rejected_count}")
        if discovery_rejected_count:
            details.append(
                f"rejected sitemap declarations: {discovery_rejected_count}"
            )
        if truncated_count:
            details.append(f"truncated documents: {truncated_count}")
        if discovery_was_truncated:
            details.append("sitemap discovery was truncated")
        findings.append(
            HomepageFinding(
                code="incomplete_sitemap_analysis",
                impact="low",
                confidence="high",
                effort="low",
                source_url=(
                    incomplete_sitemaps[0].url
                    if incomplete_sitemaps
                    else result.final_url
                ),
                summary="Some sitemap evidence could not be fully analyzed.",
                evidence="; ".join(details),
                recommendation=(
                    "Review the sitemap evidence and confirm inaccessible, "
                    "rejected, or truncated entries are expected."
                ),
                verification=(
                    "Inspect the recorded sitemap statuses and rerun the bounded "
                    "crawl after addressing any unexpected gaps."
                ),
            )
        )

    url_sets = [
        item
        for item in sitemap_evidence
        if item.document_type == "urlset"
    ]
    has_sitemap_urls = any((item.url_count or 0) > 0 for item in url_sets)
    if (
        has_sitemap_urls
        and _sitemap_evidence_is_complete(result)
        and all(item.homepage_listed is False for item in url_sets)
    ):
        findings.append(
            HomepageFinding(
                code="homepage_not_in_sitemap",
                impact="low",
                confidence="high",
                effort="low",
                source_url=url_sets[0].url,
                summary="The homepage was not found in the analyzed sitemap URL sets.",
                evidence=(
                    f"The homepage was absent from {len(url_sets)} fully analyzed "
                    "URL set(s)."
                ),
                recommendation=(
                    "Confirm the homepage should be included and add its canonical "
                    "URL to the sitemap if appropriate."
                ),
                verification=(
                    "Fetch the declared sitemap documents again and confirm they "
                    "include the intended canonical homepage URL."
                ),
            )
        )

    canonical_url = result.canonical_url
    if canonical_url is not None and canonical_url != result.final_url:
        try:
            canonical_host = urlsplit(canonical_url).hostname
            homepage_host = urlsplit(result.final_url).hostname
        except ValueError:
            canonical_host = None
            homepage_host = None
        if (
            has_sitemap_urls
            and canonical_host is not None
            and homepage_host is not None
            and canonical_host.casefold() == homepage_host.casefold()
            and _sitemap_evidence_is_complete(result)
            and all(item.canonical_url_listed is False for item in url_sets)
        ):
            findings.append(
                HomepageFinding(
                    code="canonical_not_in_sitemap",
                    impact="low",
                    confidence="high",
                    effort="low",
                    source_url=url_sets[0].url,
                    summary="The same-host canonical URL was not found in the sitemap.",
                    evidence=(
                        f"Observed canonical URL {canonical_url} was absent from "
                        f"{len(url_sets)} fully analyzed URL set(s)."
                    ),
                    recommendation=(
                        "Confirm the canonical target is intended and include it "
                        "in the sitemap if it should be indexed."
                    ),
                    verification=(
                        "Fetch the declared sitemap documents again and verify the "
                        "canonical target is present."
                    ),
                )
            )

    findings.sort(
        key=lambda finding: (
            _IMPACT_ORDER[finding.impact],
            _CONFIDENCE_ORDER[finding.confidence],
            _EFFORT_ORDER[finding.effort],
            finding.code,
        )
    )
    return HomepageAudit(
        version=HOMEPAGE_AUDIT_VERSION,
        findings=tuple(findings),
    )
