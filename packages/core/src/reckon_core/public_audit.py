"""Deterministic, tenant-free SEO audit for any public website (the "free audit" tool).

Everything here is derived from a bounded, robots-respecting crawl. The score is the share
of audit weight not lost to the issues this audit found; it is not a ranking prediction.
"""

import ipaddress
import re
from dataclasses import dataclass
from typing import Literal
from urllib.parse import urlsplit

from reckon_core.crawler import (
    CrawlError,
    CrawlResult,
    CrawlUnavailable,
    HomepageCrawler,
    PageEvidence,
)
from reckon_core.seo_audit import audit_homepage

Severity = Literal["high", "medium", "low"]
Category = Literal["Crawlability", "On-page", "Content structure", "Images", "Sitemaps"]

_MAX_INPUT_LENGTH = 253
_LABEL = re.compile(r"^(?!-)[a-z0-9-]{1,63}(?<!-)$")
_PENALTY: dict[str, int] = {"high": 15, "medium": 7, "low": 3}
_TITLE_RANGE = (15, 65)
_DESCRIPTION_RANGE = (70, 165)

_CATEGORY: dict[str, Category] = {
    "non_success_http_status": "Crawlability",
    "noindex_directive": "Crawlability",
    "invalid_canonical_url": "Crawlability",
    "multiple_canonical_links": "Crawlability",
    "cross_host_canonical": "Crawlability",
    "missing_title": "On-page",
    "missing_meta_description": "On-page",
    "missing_h1": "On-page",
    "missing_h2": "Content structure",
    "no_internal_links": "Content structure",
    "images_missing_alt_text": "Images",
    "empty_sitemap": "Sitemaps",
    "incomplete_sitemap_analysis": "Sitemaps",
    "homepage_not_in_sitemap": "Sitemaps",
    "canonical_not_in_sitemap": "Sitemaps",
}

_WHY: dict[str, str] = {
    "non_success_http_status": "Search engines drop or skip pages that do not return a success status.",
    "noindex_directive": "A noindex directive tells search engines to keep the page out of results.",
    "invalid_canonical_url": "An unusable canonical hint can make search engines pick the wrong URL.",
    "multiple_canonical_links": "Conflicting canonical hints are ignored, so duplicates may compete.",
    "cross_host_canonical": "Pointing the canonical at another host can pass your ranking signals away.",
    "missing_title": "The title is the main clickable headline in search results.",
    "missing_meta_description": "Without one, search engines write their own snippet, often a weak one.",
    "missing_h1": "The main heading tells readers and crawlers what the page is about.",
    "missing_h2": "Subheadings make content scannable and help engines understand its structure.",
    "no_internal_links": "Internal links help crawlers discover pages and spread authority.",
    "images_missing_alt_text": "Alt text makes images accessible and lets them appear in image search.",
    "empty_sitemap": "An empty sitemap gives crawlers nothing to discover.",
    "incomplete_sitemap_analysis": "We could not read every sitemap in full, so coverage is unconfirmed.",
    "homepage_not_in_sitemap": "Listing key pages in the sitemap helps them get discovered and refreshed.",
    "canonical_not_in_sitemap": "The sitemap should list the canonical version of a page.",
}


class PublicAuditTargetError(ValueError):
    """The submitted address is not an auditable public website."""


class PublicAuditUnavailable(RuntimeError):
    """The site could not be fetched (down, blocked, or disallowed by robots.txt)."""


@dataclass(frozen=True, slots=True)
class PublicFinding:
    id: str
    category: Category
    severity: Severity
    title: str
    found: str
    why_it_matters: str
    how_to_fix: str
    url: str


@dataclass(frozen=True, slots=True)
class PublicCheck:
    category: Category
    label: str
    passed: bool


@dataclass(frozen=True, slots=True)
class PublicAuditReport:
    host: str
    final_url: str
    score: int
    grade: Literal["A", "B", "C", "D", "F"]
    pages_checked: int
    findings: tuple[PublicFinding, ...]
    checks: tuple[PublicCheck, ...]
    audit_version: str


def normalize_target(raw: str) -> tuple[str, str]:
    """Return (scheme, host) for a bare domain or http(s) URL, or raise PublicAuditTargetError."""
    value = (raw or "").strip()
    if not value or len(value) > _MAX_INPUT_LENGTH + 10 or any(ord(c) < 32 for c in value):
        raise PublicAuditTargetError("Enter a website address such as example.com.")
    if "://" not in value:
        value = f"https://{value}"
    try:
        parsed = urlsplit(value)
        hostname = parsed.hostname
        port = parsed.port
    except ValueError as error:
        raise PublicAuditTargetError("That website address is not valid.") from error
    if (
        parsed.scheme.lower() not in {"http", "https"}
        or not hostname
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise PublicAuditTargetError("Enter a public http(s) website address.")
    if port not in {None, 80, 443}:
        raise PublicAuditTargetError("Only standard web ports are supported.")
    try:
        host = hostname.rstrip(".").encode("idna").decode("ascii").lower()
    except UnicodeError as error:
        raise PublicAuditTargetError("That website address is not valid.") from error
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise PublicAuditTargetError("Enter a domain name, not an IP address.")
    labels = host.split(".")
    if (
        len(host) > _MAX_INPUT_LENGTH
        or len(labels) < 2
        or any(not _LABEL.match(label) for label in labels)
        or host.endswith((".local", ".internal", ".localhost", ".test", ".invalid"))
    ):
        raise PublicAuditTargetError("Enter a public domain name such as example.com.")
    return parsed.scheme.lower(), host


def _grade(score: int) -> Literal["A", "B", "C", "D", "F"]:
    return "A" if score >= 90 else "B" if score >= 80 else "C" if score >= 65 else "D" if score >= 50 else "F"


def _page_findings(pages: tuple[PageEvidence, ...]) -> list[PublicFinding]:
    findings: list[PublicFinding] = []
    for page in pages:
        if page.status != "fetched":
            continue
        if page.http_status_code is not None and not 200 <= page.http_status_code < 300:
            findings.append(PublicFinding(
                id=f"page_http_{page.http_status_code}:{page.url}", category="Crawlability",
                severity="medium", title="A linked page returns an error",
                found=f"{page.url} returned HTTP {page.http_status_code}.",
                why_it_matters="Broken internal links waste crawl budget and frustrate visitors.",
                how_to_fix="Fix the page, redirect it to a working URL, or remove the link.",
                url=page.url))
            continue
        if not page.title:
            findings.append(PublicFinding(
                id=f"page_missing_title:{page.url}", category="On-page", severity="medium",
                title="A page has no title", found=f"No <title> was found on {page.url}.",
                why_it_matters=_WHY["missing_title"],
                how_to_fix="Add a unique, descriptive title of about 30–60 characters.", url=page.url))
        if not page.meta_description:
            findings.append(PublicFinding(
                id=f"page_missing_description:{page.url}", category="On-page", severity="low",
                title="A page has no meta description",
                found=f"No meta description was found on {page.url}.",
                why_it_matters=_WHY["missing_meta_description"],
                how_to_fix="Write a compelling summary of about 70–160 characters.", url=page.url))
        if page.h1_count == 0:
            findings.append(PublicFinding(
                id=f"page_missing_h1:{page.url}", category="On-page", severity="low",
                title="A page has no H1 heading", found=f"No <h1> was found on {page.url}.",
                why_it_matters=_WHY["missing_h1"],
                how_to_fix="Add one clear H1 that matches the page topic.", url=page.url))
        elif page.h1_count is not None and page.h1_count > 1:
            findings.append(PublicFinding(
                id=f"page_multiple_h1:{page.url}", category="On-page", severity="low",
                title="A page has several H1 headings",
                found=f"{page.h1_count} <h1> elements were found on {page.url}.",
                why_it_matters="One H1 gives a clear primary topic.",
                how_to_fix="Keep a single H1 and demote the others to H2.", url=page.url))
        if page.missing_alt_text_count:
            findings.append(PublicFinding(
                id=f"page_images_missing_alt:{page.url}", category="Images", severity="low",
                title="Images on a page are missing alt text",
                found=f"{page.missing_alt_text_count} of {page.image_count} images lack alt text on {page.url}.",
                why_it_matters=_WHY["images_missing_alt_text"],
                how_to_fix="Describe each meaningful image in its alt attribute.", url=page.url))
    return findings


def _length_findings(result: CrawlResult) -> list[PublicFinding]:
    findings: list[PublicFinding] = []
    if result.title:
        size = len(result.title.strip())
        low, high = _TITLE_RANGE
        if size < low or size > high:
            findings.append(PublicFinding(
                id="title_length", category="On-page", severity="low",
                title="Homepage title length could be better",
                found=f"The title is {size} characters; about {low}–{high} displays well.",
                why_it_matters="Titles that are too long are truncated; very short ones waste space.",
                how_to_fix=f"Rewrite it to roughly {low}–{high} characters with the main topic first.",
                url=result.final_url))
    if result.meta_description:
        size = len(result.meta_description.strip())
        low, high = _DESCRIPTION_RANGE
        if size < low or size > high:
            findings.append(PublicFinding(
                id="description_length", category="On-page", severity="low",
                title="Homepage meta description length could be better",
                found=f"The description is {size} characters; about {low}–{high} displays well.",
                why_it_matters="Over-long descriptions are cut off; very short ones add little.",
                how_to_fix=f"Rewrite it to roughly {low}–{high} characters.", url=result.final_url))
    return findings


def build_report(host: str, result: CrawlResult) -> PublicAuditReport:
    audit = audit_homepage(result)
    findings: list[PublicFinding] = []
    for item in audit.findings:
        findings.append(PublicFinding(
            id=item.code, category=_CATEGORY[item.code], severity=item.impact,
            title=item.summary.rstrip("."), found=item.evidence,
            why_it_matters=_WHY[item.code], how_to_fix=item.recommendation, url=item.source_url))
    findings.extend(_length_findings(result))
    findings.extend(_page_findings(result.page_evidence))

    penalty = sum(_PENALTY[f.severity] for f in findings)
    score = max(0, 100 - penalty)
    codes = {f.id.split(":")[0] for f in findings}

    def ok(*ids: str) -> bool:
        return not codes.intersection(ids)

    checks = (
        PublicCheck("Crawlability", "Homepage returns a success status", ok("non_success_http_status")),
        PublicCheck("Crawlability", "Page can be indexed", ok("noindex_directive")),
        PublicCheck("Crawlability", "Canonical URL is valid", ok(
            "invalid_canonical_url", "multiple_canonical_links", "cross_host_canonical")),
        PublicCheck("On-page", "Title tag present", ok("missing_title", "page_missing_title")),
        PublicCheck("On-page", "Meta description present", ok(
            "missing_meta_description", "page_missing_description")),
        PublicCheck("On-page", "Exactly one H1", ok("missing_h1", "page_missing_h1", "page_multiple_h1")),
        PublicCheck("Content structure", "Subheadings and internal links", ok("missing_h2", "no_internal_links")),
        PublicCheck("Images", "Images have alt text", ok("images_missing_alt_text", "page_images_missing_alt")),
        PublicCheck("Sitemaps", "Sitemap is present and lists the homepage", ok(
            "empty_sitemap", "homepage_not_in_sitemap", "canonical_not_in_sitemap")),
    )
    order = {"high": 0, "medium": 1, "low": 2}
    findings.sort(key=lambda f: (order[f.severity], f.category, f.id))
    return PublicAuditReport(
        host=host, final_url=result.final_url, score=score, grade=_grade(score),
        pages_checked=1 + sum(1 for p in result.page_evidence if p.status == "fetched"),
        findings=tuple(findings[:60]), checks=checks, audit_version=f"public-{audit.version}")


def run_public_audit(crawler: HomepageCrawler, raw_target: str, max_pages: int = 5) -> PublicAuditReport:
    scheme, host = normalize_target(raw_target)
    last_error: CrawlError | None = None
    for candidate in dict.fromkeys((scheme, "http" if scheme == "https" else "https")):
        try:
            return build_report(host, crawler.crawl_pages(candidate, host, max_pages=max_pages))
        except CrawlUnavailable as error:
            last_error = error
            continue
        except CrawlError as error:
            raise PublicAuditUnavailable(str(error)) from error
    raise PublicAuditUnavailable(
        "We could not reach that website. Check the address and that it is online."
    ) from last_error
