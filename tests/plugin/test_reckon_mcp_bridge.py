import importlib.util
import io
import json
from pathlib import Path
from uuid import uuid4

import httpx
import pytest

BRIDGE_PATH = (
    Path(__file__).resolve().parents[2]
    / "plugins" / "reckon-seo-copilot" / "server" / "reckon_mcp_bridge.py"
)
spec = importlib.util.spec_from_file_location("reckon_mcp_bridge", BRIDGE_PATH)
assert spec is not None and spec.loader is not None
bridge_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bridge_module)

ORG = uuid4()
SITE = str(uuid4())
TOKEN = "rk1_" + "T" * 43


def make_bridge(handler) -> "bridge_module.ReckonBridge":
    return bridge_module.ReckonBridge(
        "https://reckon.example.com", ORG, TOKEN, transport=httpx.MockTransport(handler)
    )


def call(bridge, name: str, arguments: dict) -> dict:
    reply = bridge.handle({
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": name, "arguments": arguments},
    })
    assert reply is not None
    return reply["result"]


def test_tool_list_has_no_approval_or_tenant_arguments() -> None:
    bridge = make_bridge(lambda request: httpx.Response(500))
    reply = bridge.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    tools = {tool["name"]: tool for tool in reply["result"]["tools"]}

    assert "reckon_claim_action" in tools and "reckon_report_action" in tools
    assert set(tools) == {
        "reckon_crawl_list", "reckon_website_evidence", "reckon_engine_audit",
        "reckon_propose_action", "reckon_approved_actions", "reckon_claim_action",
        "reckon_report_action", "reckon_start_crawl",
    }
    for tool in tools.values():
        assert "organization_id" not in tool["inputSchema"]["properties"]
        assert tool["inputSchema"]["additionalProperties"] is False


def test_requests_use_configured_tenant_and_token_only() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"untrusted_content": True})

    result = call(make_bridge(handler), "reckon_website_evidence", {"website_id": SITE})

    assert result["isError"] is False
    assert str(seen[0].url) == (
        f"https://reckon.example.com/api/v1/mcp/organizations/{ORG}"
        "/tools/reckon.website.evidence.get/invoke"
    )
    assert seen[0].headers["authorization"] == f"Bearer {TOKEN}"
    assert json.loads(seen[0].content) == {"website_id": SITE}


def test_tenant_override_and_malformed_arguments_never_reach_the_api() -> None:
    seen: list[httpx.Request] = []
    bridge = make_bridge(lambda request: seen.append(request) or httpx.Response(200, json={}))

    assert call(bridge, "reckon_website_evidence", {"website_id": SITE, "organization_id": str(uuid4())})["isError"]
    assert call(bridge, "reckon_website_evidence", {"website_id": "not-a-uuid"})["isError"]
    assert call(bridge, "reckon_engine_audit", {"website_id": SITE, "engine": "../x"})["isError"]
    assert call(bridge, "reckon_crawl_list", {"website_id": SITE, "limit": 1000})["isError"]
    assert call(bridge, "reckon_report_action", {"proposal_id": str(uuid4()), "outcome": "verified"})["isError"]
    assert seen == []


def test_proposals_use_a_deterministic_idempotency_key_and_cannot_be_high_risk() -> None:
    keys: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        keys.append(request.headers["idempotency-key"])
        return httpx.Response(200, json={"status": "proposed"})

    bridge = make_bridge(handler)
    arguments = {
        "website_id": SITE, "action_type": "meta_title", "target_url": "https://example.com/",
        "target_version": "v1", "before_state": {"title": "Old"},
        "proposed_state": {"title": "New"}, "risk": "low", "reason": "Shorter title",
    }
    call(bridge, "reckon_propose_action", arguments)
    call(bridge, "reckon_propose_action", dict(arguments))
    call(bridge, "reckon_propose_action", {**arguments, "proposed_state": {"title": "Other"}})

    assert keys[0] == keys[1] != keys[2]
    assert call(bridge, "reckon_propose_action", {**arguments, "risk": "high"})["isError"]


def test_start_crawl_uses_fresh_or_caller_idempotency_keys_and_hides_them_from_the_body() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"crawl": {"status": "running"}})

    bridge = make_bridge(handler)
    call(bridge, "reckon_start_crawl", {"website_id": SITE})
    call(bridge, "reckon_start_crawl", {"website_id": SITE})
    call(bridge, "reckon_start_crawl", {"website_id": SITE, "idempotency_key": "retry-key-0001"})

    keys = [request.headers["idempotency-key"] for request in seen]
    assert keys[0] != keys[1] and keys[2] == "retry-key-0001"
    assert all(json.loads(request.content) == {"website_id": SITE} for request in seen)
    assert all(str(request.url).endswith("/tools/reckon.crawl.start/invoke") for request in seen)
    assert call(bridge, "reckon_start_crawl", {"website_id": SITE, "idempotency_key": "bad key!"})["isError"]
    assert len(seen) == 3


def test_api_errors_are_sanitized_and_do_not_leak_the_token() -> None:
    bridge = make_bridge(lambda request: httpx.Response(409, json={"detail": "Only approved proposals can be claimed."}))
    result = call(bridge, "reckon_claim_action", {"proposal_id": str(uuid4())})

    assert result["isError"] is True
    assert "409" in result["content"][0]["text"]
    assert TOKEN not in json.dumps(result)

    def failing(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom " + TOKEN)

    unreachable = call(make_bridge(failing), "reckon_claim_action", {"proposal_id": str(uuid4())})
    assert unreachable["isError"] is True
    assert TOKEN not in json.dumps(unreachable)


def test_oversized_and_redirected_responses_are_not_returned() -> None:
    big = make_bridge(lambda request: httpx.Response(200, text="x" * (bridge_module.MAX_RESULT_CHARS + 1)))
    assert call(big, "reckon_crawl_list", {"website_id": SITE})["isError"] is True
    redirect = make_bridge(lambda request: httpx.Response(302, headers={"location": "https://evil.example/"}))
    assert call(redirect, "reckon_crawl_list", {"website_id": SITE})["isError"] is True


def test_protocol_handles_initialize_notifications_and_bad_input() -> None:
    bridge = make_bridge(lambda request: httpx.Response(500))
    stdin = io.StringIO("\n".join([
        json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-03-26"}}),
        json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}),
        json.dumps({"jsonrpc": "2.0", "id": 2, "method": "nope"}),
        "{not json",
    ]) + "\n")
    stdout = io.StringIO()

    bridge_module.serve(bridge, stdin, stdout)
    replies = [json.loads(line) for line in stdout.getvalue().splitlines()]

    assert replies[0]["result"]["protocolVersion"] == "2025-03-26"
    assert replies[1]["error"]["code"] == -32601
    assert replies[2]["error"]["code"] == -32700
    assert len(replies) == 3


@pytest.mark.parametrize(
    "environ",
    [
        {"RECKON_API_URL": "http://reckon.example.com", "RECKON_ORGANIZATION_ID": str(ORG), "RECKON_ACCESS_TOKEN": TOKEN},
        {"RECKON_API_URL": "https://user:pw@reckon.example.com", "RECKON_ORGANIZATION_ID": str(ORG), "RECKON_ACCESS_TOKEN": TOKEN},
        {"RECKON_API_URL": "https://reckon.example.com/x", "RECKON_ORGANIZATION_ID": str(ORG), "RECKON_ACCESS_TOKEN": TOKEN},
        {"RECKON_API_URL": "https://reckon.example.com", "RECKON_ORGANIZATION_ID": "nope", "RECKON_ACCESS_TOKEN": TOKEN},
        {"RECKON_API_URL": "https://reckon.example.com", "RECKON_ORGANIZATION_ID": str(ORG), "RECKON_ACCESS_TOKEN": ""},
    ],
)
def test_unsafe_configuration_is_rejected(environ: dict[str, str]) -> None:
    with pytest.raises(bridge_module.BridgeConfigError):
        bridge_module.load_config(environ)


def test_loopback_http_is_allowed_for_local_development() -> None:
    base, org, _ = bridge_module.load_config({
        "RECKON_API_URL": "http://127.0.0.1:8000/", "RECKON_ORGANIZATION_ID": str(ORG),
        "RECKON_ACCESS_TOKEN": TOKEN,
    })
    assert base == "http://127.0.0.1:8000" and org == ORG
