from dataclasses import dataclass
from typing import Literal
from urllib.parse import urlsplit


EngineName = Literal[
    "keywords",
    "content_studio",
    "linkpilot",
    "local_seo",
    "ecommerce",
    "enterprise",
    "media_query",
    "emerging_geo",
]

FindingImpact = Literal["high", "medium", "low"]
FindingConfidence = Literal["high", "medium"]
FindingEffort = Literal["low", "medium", "high"]


@dataclass(frozen=True, slots=True)
class EngineFinding:
    code: str
    title: str
    impact: FindingImpact
    confidence: FindingConfidence
    effort: FindingEffort
    source_url: str
    evidence: str
    recommendation: str
    verification: str


@dataclass(frozen=True, slots=True)
class EngineAudit:
    engine: EngineName
    version: str
    coverage: Literal["complete", "partial", "unavailable"]
    findings: tuple[EngineFinding, ...]


def _page_rows(crawl: object) -> tuple[dict[str, object], ...]:
    homepage = {
        "url": getattr(crawl, "final_url", None),
        "status": "fetched",
        "http_status_code": getattr(crawl, "http_status", None),
        "title": getattr(crawl, "title", None),
        "meta_description": getattr(crawl, "meta_description", None),
        "h1_count": getattr(crawl, "h1_count", None),
        "h2_count": None,
        "internal_link_count": None,
        "image_count": getattr(crawl, "image_count", None),
        "missing_alt_text_count": getattr(crawl, "missing_alt_text_count", None),
    }
    rows: list[dict[str, object]] = [homepage]
    evidence = getattr(crawl, "page_evidence", None) or ()
    for item in evidence:
        if isinstance(item, dict):
            rows.append(item)
        else:
            rows.append({
                "url": getattr(item, "url", None),
                "status": getattr(item, "status", None),
                "title": getattr(item, "title", None),
                "h1_count": getattr(item, "h1_count", None),
                "h2_count": getattr(item, "h2_count", None),
                "internal_link_count": getattr(item, "internal_link_count", None),
                "image_count": getattr(item, "image_count", None),
                "missing_alt_text_count": getattr(item, "missing_alt_text_count", None),
            })
    return tuple(rows)


def audit_engine(crawl: object, engine: EngineName) -> EngineAudit:
    rows = _page_rows(crawl)
    findings: list[EngineFinding] = []
    final_url = str(getattr(crawl, "final_url", "") or "")
    page_count = len([row for row in rows if row.get("status") == "fetched"])

    if engine == "keywords":
        title = str(getattr(crawl, "title", "") or "").strip()
        path = urlsplit(final_url).path
        slug_terms = [
            part.replace("-", " ").strip()
            for part in path.strip("/").split("/")
            if part and part not in {"index", "home"}
        ]
        if not title:
            findings.append(EngineFinding(
                code="missing_primary_title",
                title="Homepage title is missing",
                impact="high",
                confidence="high",
                effort="low",
                source_url=final_url,
                evidence="The crawl recorded no non-empty homepage title.",
                recommendation="Define a unique descriptive homepage title after reviewing actual business intent.",
                verification="Fetch the homepage and confirm the title is unique and descriptive.",
            ))
        elif slug_terms:
            findings.append(EngineFinding(
                code="review_title_intent",
                title="Review title against homepage URL intent",
                impact="low",
                confidence="medium",
                effort="low",
                source_url=final_url,
                evidence=f"Observed title: {title!r}; URL terms: {', '.join(slug_terms)!r}.",
                recommendation="Compare the title with search intent using a licensed keyword data source before changing it.",
                verification="Verify the approved title is descriptive and does not promise unsupported ranking results.",
            ))
        coverage = "partial" if title or slug_terms else "unavailable"

    elif engine == "content_studio":
        h1 = getattr(crawl, "h1_count", None)
        h2 = next((row.get("h2_count") for row in rows if row.get("h2_count") is not None), None)
        description = getattr(crawl, "meta_description", None)
        if h1 == 0:
            findings.append(EngineFinding(
                code="missing_primary_heading",
                title="Homepage H1 is missing",
                impact="medium",
                confidence="high",
                effort="low",
                source_url=final_url,
                evidence="The crawl recorded zero H1 elements.",
                recommendation="Add one clear primary heading that accurately summarizes the homepage topic.",
                verification="Fetch the homepage and confirm one primary visible H1 is present.",
            ))
        if not description:
            findings.append(EngineFinding(
                code="missing_summary",
                title="Homepage summary metadata is missing",
                impact="low",
                confidence="high",
                effort="low",
                source_url=final_url,
                evidence="The crawl recorded no non-empty meta description.",
                recommendation="Draft a concise factual summary for the homepage after brand and intent review.",
                verification="Fetch the homepage and confirm a unique, factual meta description.",
            ))
        if h2 == 0:
            findings.append(EngineFinding(
                code="missing_section_structure",
                title="No H2 section structure was observed",
                impact="low",
                confidence="medium",
                effort="low",
                source_url=final_url,
                evidence="Available page evidence contained zero H2 elements.",
                recommendation="Review whether key sections should use descriptive H2 headings.",
                verification="Fetch the homepage and verify heading structure remains readable and accurate.",
            ))
        coverage = "complete" if h1 is not None and description is not None else "partial"

    elif engine == "linkpilot":
        coverage = "unavailable"
        findings.append(EngineFinding(
            code="external_link_data_not_configured",
            title="Backlink and prospect data is not configured",
            impact="low",
            confidence="high",
            effort="medium",
            source_url=final_url,
            evidence="No licensed backlink or unlinked-mention provider is connected.",
            recommendation="Connect an approved backlink/provider adapter before generating prospect or outreach recommendations.",
            verification="Confirm provider configuration and independent prospect evidence before external outreach.",
        ))

    elif engine == "local_seo":
        coverage = "unavailable"
        findings.append(EngineFinding(
            code="local_business_data_not_configured",
            title="Local business profile data is not configured",
            impact="low",
            confidence="high",
            effort="medium",
            source_url=final_url,
            evidence="No local business profile, NAP record or local schema source is connected.",
            recommendation="Add verified business profile and location data before local SEO recommendations.",
            verification="Compare live page/location data with the approved business profile.",
        ))

    elif engine == "ecommerce":
        ecommerce_terms = ("product", "category", "shop", "cart", "checkout")
        internal_urls = tuple(str(url) for url in (getattr(crawl, "internal_urls", None) or ()) )
        matches = [
            url for url in internal_urls
            if any(term in urlsplit(url).path.casefold() for term in ecommerce_terms)
        ]
        if matches:
            findings.append(EngineFinding(
                code="ecommerce_urls_detected",
                title="Ecommerce-style URLs are present",
                impact="medium",
                confidence="medium",
                effort="medium",
                source_url=matches[0],
                evidence=f"Observed {len(matches)} same-host URL(s) with ecommerce path terms.",
                recommendation="Validate product/category schema and faceted-navigation rules against the actual CMS.",
                verification="Fetch representative product/category URLs and verify schema and indexability.",
            ))
        else:
            findings.append(EngineFinding(
                code="ecommerce_signals_not_observed",
                title="No ecommerce-specific URLs were observed",
                impact="low",
                confidence="medium",
                effort="medium",
                source_url=final_url,
                evidence="The crawl found no homepage evidence for common ecommerce path terms.",
                recommendation="Configure a product/category data source if this is an ecommerce site.",
                verification="Confirm site content and CMS product routes independently.",
            ))
        coverage = "partial" if matches else "unavailable"

    elif engine == "enterprise":
        internal_urls = tuple(str(url) for url in (getattr(crawl, "internal_urls", None) or ()) )
        if page_count > 1 or len(internal_urls) > 10:
            findings.append(EngineFinding(
                code="scale_candidate",
                title="The crawl contains sufficient evidence for segmented analysis",
                impact="medium",
                confidence="medium",
                effort="medium",
                source_url=final_url,
                evidence=f"Observed {page_count} crawled page row(s) and {len(internal_urls)} discovered URL(s).",
                recommendation="Segment findings by template, domain and indexability state before bulk action.",
                verification="Compare affected URLs across a completed bounded recrawl.",
            ))
        else:
            findings.append(EngineFinding(
                code="enterprise_scale_unproven",
                title="Enterprise-scale evidence is incomplete",
                impact="low",
                confidence="medium",
                effort="medium",
                source_url=final_url,
                evidence=f"Only {page_count} crawled page row(s) were available.",
                recommendation="Run a broader authorized crawl before enterprise-scale recommendations.",
                verification="Confirm the crawl covers representative templates and domains.",
            ))
        coverage = "partial"

    elif engine == "media_query":
        image_count = sum(
            int(row.get("image_count") or 0)
            for row in rows
            if isinstance(row.get("image_count"), int)
        )
        missing_alt = sum(
            int(row.get("missing_alt_text_count") or 0)
            for row in rows
            if isinstance(row.get("missing_alt_text_count"), int)
        )
        if missing_alt:
            findings.append(EngineFinding(
                code="media_alt_text_missing",
                title="Media image alt text is missing",
                impact="medium",
                confidence="high",
                effort="low",
                source_url=final_url,
                evidence=f"Observed {missing_alt} image(s) missing alt text across {image_count} discovered image row(s).",
                recommendation="Review meaningful images and add concise factual alternative text.",
                verification="Fetch the affected pages and verify appropriate alt attributes.",
            ))
        else:
            findings.append(EngineFinding(
                code="media_evidence_not_observed",
                title="No missing-alt finding was observed",
                impact="low",
                confidence="medium",
                effort="low",
                source_url=final_url,
                evidence="No missing-alt evidence was available in the crawled page rows.",
                recommendation="Verify media coverage with representative pages before using this as a clean result.",
                verification="Fetch additional representative pages and repeat the check.",
            ))
        coverage = "partial" if image_count else "unavailable"

    else:
        title = str(getattr(crawl, "title", "") or "")
        h1 = getattr(crawl, "h1_count", None)
        canonical = getattr(crawl, "canonical_url", None)
        if title or h1 is not None or canonical:
            findings.append(EngineFinding(
                code="entity_signals_observed",
                title="Basic entity signals are observable",
                impact="low",
                confidence="medium",
                effort="medium",
                source_url=final_url,
                evidence=f"Title present: {bool(title)}; H1 observed: {h1 is not None}; canonical: {bool(canonical)}.",
                recommendation="Use factual title, heading and canonical context to improve entity clarity; do not claim answer-engine ranking.",
                verification="Verify visible page facts and structured data independently.",
            ))
        else:
            findings.append(EngineFinding(
                code="entity_signals_unavailable",
                title="Entity clarity evidence is unavailable",
                impact="low",
                confidence="medium",
                effort="medium",
                source_url=final_url,
                evidence="No title, heading or canonical evidence was available.",
                recommendation="Complete the crawl and validate structured data before an GEO assessment.",
                verification="Fetch a representative page and verify visible entity facts and schema.",
            ))
        coverage = "partial"

    findings.sort(key=lambda finding: (
        {"high": 0, "medium": 1, "low": 2}[finding.impact],
        {"high": 0, "medium": 1}[finding.confidence],
        {"low": 0, "medium": 1, "high": 2}[finding.effort],
        finding.code,
    ))
    return EngineAudit(
        engine=engine,
        version=f"{engine}-v1",
        coverage=coverage,
        findings=tuple(findings),
    )
