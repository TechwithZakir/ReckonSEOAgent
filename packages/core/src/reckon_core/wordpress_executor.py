import base64
import re
from typing import Any
from urllib.parse import urlsplit

import httpx
from pydantic import SecretStr

from reckon_core.crawl_security import (
    CrawlTargetError,
    DnsAddressLookup,
    DnsAddressLookupUnavailable,
    PublicDnsAddressResolver,
    resolve_public_crawl_target,
)
from reckon_core.model_settings import normalize_model_endpoint
from reckon_core.persistence import SeoActionProposal
from reckon_core.websites import InvalidWebsiteUrl


class WordPressExecutionError(RuntimeError):
    pass


class TargetVersionMismatch(WordPressExecutionError):
    pass


class UnsupportedWordPressAction(WordPressExecutionError):
    pass


class WordPressVerificationFailed(WordPressExecutionError):
    pass


_RESOURCE_TYPES = frozenset({"posts", "pages"})
_RESOURCE_ID = re.compile(r"^[1-9][0-9]{0,11}$")
_MAX_VALUE_LENGTH = 1000
_MAX_RESPONSE_BYTES = 2_000_000
DEFAULT_FIELD_MAP = {"heading": "title"}
_ALLOWED_FIELDS = frozenset({"title", "excerpt"})


class WordPressActionExecutor:
    """Approved single-field WordPress REST writes bound to one configured site.

    The target host must equal the configured base host, every request is pinned to a
    public DNS answer, redirects are never followed, and an update is confirmed only by
    an independent read-back. Rollback never overwrites a value changed after execution.
    """

    binding_version = "wordpress-executor-v1"

    def __init__(
        self,
        base_url: str,
        username: str,
        app_password: SecretStr,
        field_map: dict[str, str] | None = None,
        transport: httpx.BaseTransport | None = None,
        resolver: DnsAddressLookup | None = None,
        timeout_seconds: float = 10.0,
    ) -> None:
        try:
            normalized = normalize_model_endpoint(base_url)
        except (ValueError, InvalidWebsiteUrl):
            raise ValueError("The WordPress base URL is invalid.") from None
        parsed = urlsplit(normalized)
        if parsed.scheme != "https" or parsed.hostname is None or parsed.query or parsed.fragment:
            raise ValueError("The WordPress base URL is invalid.")
        secret = app_password.get_secret_value()
        if (
            not username
            or len(username) > 320
            or not secret
            or len(secret) > 4096
            or any(char.isspace() for char in secret)
        ):
            raise ValueError("The WordPress credentials are invalid.")
        if timeout_seconds <= 0:
            raise ValueError("The WordPress timeout must be positive.")
        mapping = dict(DEFAULT_FIELD_MAP if field_map is None else field_map)
        if any(field not in _ALLOWED_FIELDS for field in mapping.values()):
            raise ValueError("The WordPress field mapping is not supported.")
        self._field_map = mapping
        self._base_path = parsed.path.rstrip("/")
        self._host = parsed.hostname.lower()
        self._authorization = "Basic " + base64.b64encode(
            f"{username}:{secret}".encode("utf-8")
        ).decode("ascii")
        self._transport = transport
        self._resolver = resolver or PublicDnsAddressResolver(timeout_seconds=2.0)
        self._timeout = timeout_seconds

    def execute(self, proposal: SeoActionProposal) -> dict[str, str]:
        if proposal.status not in {"approved", "executing"}:
            raise WordPressExecutionError("Only approved proposals may execute.")
        resource, resource_id, field = self._target(proposal)
        value = self._value(proposal.proposed_state)
        current = self._read(resource, resource_id)
        if current["modified_gmt"] != proposal.target_version:
            raise TargetVersionMismatch("The live WordPress item changed after approval.")
        if current[field] != proposal.before_state.get("value"):
            raise TargetVersionMismatch("The live WordPress value differs from the approved before-state.")
        updated = self._write(resource, resource_id, field, value)
        if updated[field] != value:
            raise WordPressVerificationFailed("WordPress did not confirm the approved value.")
        return {
            "value": value,
            "wp_type": resource,
            "wp_id": resource_id,
            "field": field,
            "modified_gmt": updated["modified_gmt"],
            "execution": "wordpress-confirmed",
        }

    def verify(self, proposal: SeoActionProposal) -> dict[str, str]:
        if proposal.executed_state is None:
            raise WordPressExecutionError("No executed state is available for verification.")
        resource, resource_id, field = self._target(proposal)
        live = self._read(resource, resource_id)
        if live[field] != self._value(proposal.proposed_state):
            raise WordPressVerificationFailed("Live WordPress state differs from the approved proposal.")
        return {
            "value": live[field],
            "modified_gmt": live["modified_gmt"],
            "verification": "wordpress-independent-read",
        }

    def rollback(self, proposal: SeoActionProposal) -> dict[str, str]:
        if proposal.executed_state is None:
            raise WordPressExecutionError("Only executed actions can be rolled back.")
        resource, resource_id, field = self._target(proposal)
        original = self._value(proposal.before_state)
        live = self._read(resource, resource_id)
        if live[field] != proposal.executed_state.get("value"):
            raise TargetVersionMismatch("The live value changed after execution; rollback was not attempted.")
        restored = self._write(resource, resource_id, field, original)
        if restored[field] != original:
            raise WordPressVerificationFailed("WordPress did not confirm the restored value.")
        return {
            "value": original,
            "modified_gmt": restored["modified_gmt"],
            "rollback": "wordpress-confirmed",
        }

    def _target(self, proposal: SeoActionProposal) -> tuple[str, str, str]:
        field = self._field_map.get(proposal.action_type)
        if field is None:
            raise UnsupportedWordPressAction("This action type has no approved WordPress field mapping.")
        parsed = urlsplit(proposal.target_url)
        if parsed.scheme != "https" or (parsed.hostname or "").lower() != self._host:
            raise WordPressExecutionError("The action target is outside the configured WordPress site.")
        resource = proposal.before_state.get("wp_type")
        resource_id = proposal.before_state.get("wp_id")
        if resource not in _RESOURCE_TYPES or not resource_id or not _RESOURCE_ID.fullmatch(resource_id):
            raise WordPressExecutionError("The action does not identify a WordPress post or page.")
        return resource, resource_id, field

    @staticmethod
    def _value(state: dict[str, str]) -> str:
        value = state.get("value")
        if value is None or len(value) > _MAX_VALUE_LENGTH:
            raise WordPressExecutionError("The action value is missing or too long.")
        return value

    def _read(self, resource: str, resource_id: str) -> dict[str, str]:
        return self._parse(self._request("GET", resource, resource_id, None))

    def _write(self, resource: str, resource_id: str, field: str, value: str) -> dict[str, str]:
        self._request("POST", resource, resource_id, {field: value})
        # Never trust the write response alone; read the item back independently.
        return self._read(resource, resource_id)

    @staticmethod
    def _parse(body: dict[str, Any]) -> dict[str, str]:
        modified = body.get("modified_gmt")
        result: dict[str, str] = {}
        for field in _ALLOWED_FIELDS:
            node = body.get(field)
            raw = node.get("raw") if isinstance(node, dict) else None
            if isinstance(raw, str):
                result[field] = raw
        if not isinstance(modified, str) or not modified:
            raise WordPressVerificationFailed("WordPress did not return a confirmed item version.")
        result["modified_gmt"] = modified
        return result

    def _request(
        self,
        method: str,
        resource: str,
        resource_id: str,
        payload: dict[str, str] | None,
    ) -> dict[str, Any]:
        try:
            target = resolve_public_crawl_target(self._host, self._resolver)
            address = target.addresses[0]
            authority = f"[{address}]" if ":" in address else address
            url = f"https://{authority}{self._base_path}/wp-json/wp/v2/{resource}/{resource_id}"
            with httpx.Client(
                transport=self._transport,
                trust_env=False,
                follow_redirects=False,
                timeout=httpx.Timeout(self._timeout),
            ) as client:
                response = client.request(
                    method,
                    url,
                    params={"context": "edit"} if method == "GET" else None,
                    json=payload,
                    headers={
                        "Authorization": self._authorization,
                        "Accept": "application/json",
                        "Host": target.host,
                    },
                    extensions={"sni_hostname": target.host},
                )
            if response.status_code != 200 or len(response.content) > _MAX_RESPONSE_BYTES:
                raise WordPressExecutionError("WordPress did not return a confirmed response.")
            body = response.json()
        except (httpx.HTTPError, CrawlTargetError, DnsAddressLookupUnavailable, ValueError):
            raise WordPressExecutionError("The WordPress request could not be confirmed.") from None
        if not isinstance(body, dict):
            raise WordPressExecutionError("WordPress returned an unexpected response.")
        return body
