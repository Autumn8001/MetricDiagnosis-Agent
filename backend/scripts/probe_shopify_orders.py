"""Perform a bounded, read-only Shopify Orders capability probe.

This is an explicit sandbox probe, not a synchronizer or a product connector.
It prints only a small aggregate summary and never persists response data.
"""

from __future__ import annotations

import argparse
import datetime as dt
from decimal import Decimal, InvalidOperation
import json
import os
import re
import sys
import time
from typing import Any

import httpx


API_VERSION = "2026-10"
MAX_RESPONSE_BYTES = 1024 * 1024
MAX_PAGES = 5
PAGE_SIZE = 50
REQUEST_TIMEOUT_SECONDS = 10.0
MAX_TOTAL_SECONDS = 60.0
TOKEN_ENV = "METRICSLEUTH_SHOPIFY_ACCESS_TOKEN"

SCOPE_QUERY = """query MetricSleuthReadScopes {
  currentAppInstallation {
    accessScopes { handle }
  }
}"""

ORDERS_QUERY = """query MetricSleuthOrdersProbe($first: Int!, $after: String, $query: String!) {
  orders(first: $first, after: $after, query: $query, sortKey: CREATED_AT) {
    nodes {
      id
      createdAt
      updatedAt
      test
      cancelledAt
      displayFinancialStatus
      currentSubtotalPriceSet { shopMoney { amount currencyCode } }
    }
    pageInfo { hasNextPage endCursor }
  }
}"""

_SHOP_HOST_RE = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.myshopify\.com\Z")
_CURRENCY_RE = re.compile(r"[A-Z]{3}\Z")
_FINANCIAL_STATUSES = {
    "AUTHORIZED", "EXPIRED", "PAID", "PARTIALLY_PAID", "PARTIALLY_REFUNDED",
    "PENDING", "REFUNDED", "VOIDED",
}


class ProbeFailure(Exception):
    """A fixed safe error classification; never includes remote or user text."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _parse_date(value: str) -> dt.date:
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ProbeFailure("invalid_date")
    try:
        parsed = dt.date.fromisoformat(value)
    except ValueError:
        raise ProbeFailure("invalid_date") from None
    if parsed.isoformat() != value:
        raise ProbeFailure("invalid_date")
    return parsed


def _validate_config(shop: str, start_text: str, end_text: str, allow_sandbox_read: bool) -> tuple[dt.date, dt.date]:
    if not allow_sandbox_read:
        raise ProbeFailure("sandbox_read_confirmation_required")
    if not isinstance(shop, str) or not _SHOP_HOST_RE.fullmatch(shop):
        raise ProbeFailure("invalid_shop_host")
    start = _parse_date(start_text)
    end = _parse_date(end_text)
    if end < start or (end - start).days >= 31 or end == dt.date.max:
        raise ProbeFailure("invalid_date_range")
    return start, end


def _api_url(shop: str) -> str:
    # `shop` has already passed an exact hostname allowlist; no URL is caller supplied.
    return f"https://{shop}/admin/api/{API_VERSION}/graphql.json"


def _json_response(
    client: httpx.Client, url: str, token: str, payload: dict[str, Any], deadline: float
) -> tuple[dict[str, Any], bool]:
    if time.monotonic() >= deadline:
        raise ProbeFailure("total_time_budget_exceeded")
    try:
        with client.stream(
            "POST",
            url,
            headers={
                "X-Shopify-Access-Token": token,
                "Accept": "application/json",
                "Accept-Encoding": "identity",
            },
            json=payload,
        ) as response:
            status = response.status_code
            if 300 <= status < 400:
                raise ProbeFailure("http_redirect")
            if 400 <= status < 500:
                raise ProbeFailure("http_client_error")
            if 500 <= status < 600:
                raise ProbeFailure("http_server_error")
            if status != 200:
                raise ProbeFailure("http_unexpected_status")
            api_version_header = response.headers.get("x-shopify-api-version")
            if api_version_header is not None and api_version_header != API_VERSION:
                raise ProbeFailure("api_version_mismatch")
            version_confirmed = api_version_header == API_VERSION
            encoding = response.headers.get("content-encoding", "identity").lower()
            if encoding not in {"", "identity"}:
                raise ProbeFailure("unsupported_content_encoding")
            chunks: list[bytes] = []
            total = 0
            for chunk in response.iter_bytes():
                if time.monotonic() >= deadline:
                    raise ProbeFailure("total_time_budget_exceeded")
                total += len(chunk)
                if total > MAX_RESPONSE_BYTES:
                    raise ProbeFailure("response_too_large")
                chunks.append(chunk)
            raw = b"".join(chunks)
    except ProbeFailure:
        raise
    except httpx.TimeoutException:
        raise ProbeFailure("request_timeout") from None
    except httpx.TransportError:
        raise ProbeFailure("request_transport_error") from None
    except Exception:
        # Do not serialize exception text: it can contain URLs, headers, or body data.
        raise ProbeFailure("request_failed") from None

    try:
        decoded = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ProbeFailure("invalid_json") from None
    if not isinstance(decoded, dict):
        raise ProbeFailure("invalid_response_shape")
    if "errors" in decoded:
        errors = decoded["errors"]
        if not isinstance(errors, list):
            raise ProbeFailure("invalid_graphql_errors")
        if errors:
            raise ProbeFailure("graphql_error")
    data = decoded.get("data")
    if not isinstance(data, dict):
        raise ProbeFailure("invalid_response_shape")
    return data, version_confirmed


def _aware_datetime(value: Any, error_code: str) -> dt.datetime:
    if not isinstance(value, str) or len(value) > 64:
        raise ProbeFailure(error_code)
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ProbeFailure(error_code) from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ProbeFailure(error_code)
    return parsed.astimezone(dt.timezone.utc)


def _validate_order(node: Any, start: dt.date, end_exclusive: dt.date) -> tuple[dt.date, bool, bool, bool, str]:
    if not isinstance(node, dict):
        raise ProbeFailure("invalid_order_shape")
    order_id = node.get("id")
    if not isinstance(order_id, str) or not order_id or len(order_id) > 256:
        raise ProbeFailure("invalid_order_id")

    created_at = _aware_datetime(node.get("createdAt"), "invalid_created_at")
    _aware_datetime(node.get("updatedAt"), "invalid_updated_at")
    created_day = created_at.date()
    if not start <= created_day < end_exclusive:
        raise ProbeFailure("order_outside_requested_range")

    test = node.get("test")
    if type(test) is not bool:
        raise ProbeFailure("invalid_test_flag")

    if "cancelledAt" not in node or "displayFinancialStatus" not in node:
        raise ProbeFailure("missing_nullable_order_field")
    cancelled_at = node["cancelledAt"]
    if cancelled_at is not None:
        _aware_datetime(cancelled_at, "invalid_cancelled_at")

    financial_status = node.get("displayFinancialStatus")
    if financial_status is not None and (
        not isinstance(financial_status, str) or financial_status not in _FINANCIAL_STATUSES
    ):
        raise ProbeFailure("invalid_financial_status")

    money_set = node.get("currentSubtotalPriceSet")
    if not isinstance(money_set, dict):
        raise ProbeFailure("invalid_money_shape")
    shop_money = money_set.get("shopMoney")
    if not isinstance(shop_money, dict):
        raise ProbeFailure("invalid_money_shape")
    amount = shop_money.get("amount")
    if not isinstance(amount, str) or len(amount) > 128:
        raise ProbeFailure("invalid_amount")
    try:
        parsed_amount = Decimal(amount)
    except (InvalidOperation, ValueError):
        raise ProbeFailure("invalid_amount") from None
    if not parsed_amount.is_finite():
        raise ProbeFailure("invalid_amount")
    currency = shop_money.get("currencyCode")
    if not isinstance(currency, str) or not _CURRENCY_RE.fullmatch(currency):
        raise ProbeFailure("invalid_currency")

    return created_day, test, cancelled_at is not None, financial_status is None, currency


def _orders_query(start: dt.date, end: dt.date) -> str:
    end_exclusive = end + dt.timedelta(days=1)
    return (
        f"created_at:>='{start.isoformat()}T00:00:00Z' "
        f"created_at:<'{end_exclusive.isoformat()}T00:00:00Z'"
    )


def probe_with_client(
    *, shop: str, start: dt.date, end: dt.date, token: str, client: httpx.Client
) -> dict[str, Any]:
    """Execute the fixed scope check and bounded Orders query using an injected client."""
    if not isinstance(token, str) or not token or len(token) > 8192 or any(ord(char) < 32 for char in token):
        raise ProbeFailure("invalid_access_token")
    if not isinstance(shop, str) or not _SHOP_HOST_RE.fullmatch(shop):
        raise ProbeFailure("invalid_shop_host")
    if type(start) is not dt.date or type(end) is not dt.date:
        raise ProbeFailure("invalid_date_range")
    if end < start or (end - start).days >= 31 or end == dt.date.max:
        raise ProbeFailure("invalid_date_range")
    url = _api_url(shop)
    deadline = time.monotonic() + MAX_TOTAL_SECONDS
    scope_data, scope_version_confirmed = _json_response(
        client, url, token, {"query": SCOPE_QUERY}, deadline
    )
    installation = scope_data.get("currentAppInstallation")
    if not isinstance(installation, dict):
        raise ProbeFailure("invalid_scope_response")
    scope_result = installation.get("accessScopes")
    if not isinstance(scope_result, list):
        raise ProbeFailure("invalid_scope_response")
    scopes: set[str] = set()
    for item in scope_result:
        if not isinstance(item, dict) or not isinstance(item.get("handle"), str):
            raise ProbeFailure("invalid_scope_response")
        scopes.add(item["handle"])
    if "read_orders" not in scopes:
        raise ProbeFailure("required_scope_missing")

    end_exclusive = end + dt.timedelta(days=1)
    after: str | None = None
    seen_cursors: set[str] = set()
    seen_ids: set[str] = set()
    days: set[dt.date] = set()
    currency_codes: set[str] = set()
    order_count = test_count = cancelled_count = missing_status_count = 0
    complete = False
    version_confirmed = scope_version_confirmed

    for page_number in range(1, MAX_PAGES + 1):
        payload = {
            "query": ORDERS_QUERY,
            "variables": {"first": PAGE_SIZE, "after": after, "query": _orders_query(start, end)},
        }
        data, response_version_confirmed = _json_response(client, url, token, payload, deadline)
        version_confirmed = version_confirmed and response_version_confirmed
        connection = data.get("orders")
        if not isinstance(connection, dict):
            raise ProbeFailure("invalid_orders_response")
        nodes = connection.get("nodes")
        page_info = connection.get("pageInfo")
        if not isinstance(nodes, list) or len(nodes) > PAGE_SIZE or not isinstance(page_info, dict):
            raise ProbeFailure("invalid_orders_response")
        if "endCursor" not in page_info:
            raise ProbeFailure("invalid_page_info")
        has_next = page_info.get("hasNextPage")
        if type(has_next) is not bool:
            raise ProbeFailure("invalid_page_info")
        cursor = page_info["endCursor"]
        if cursor is not None and (
            not isinstance(cursor, str) or not cursor or len(cursor) > 512
        ):
            raise ProbeFailure("invalid_pagination_cursor")

        for node in nodes:
            if not isinstance(node, dict):
                raise ProbeFailure("invalid_order_shape")
            order_id = node.get("id")
            if not isinstance(order_id, str) or not order_id or order_id in seen_ids:
                raise ProbeFailure("duplicate_or_invalid_order_id")
            seen_ids.add(order_id)
            created_day, is_test, is_cancelled, missing_status, currency = _validate_order(
                node, start, end_exclusive
            )
            days.add(created_day)
            currency_codes.add(currency)
            order_count += 1
            test_count += int(is_test)
            cancelled_count += int(is_cancelled)
            missing_status_count += int(missing_status)

        if not has_next:
            complete = True
            break
        if (
            not isinstance(cursor, str)
            or cursor == after
            or cursor in seen_cursors
        ):
            raise ProbeFailure("invalid_pagination_cursor")
        seen_cursors.add(cursor)
        after = cursor
        if page_number == MAX_PAGES:
            raise ProbeFailure("page_budget_exceeded")

    requested_days = (end - start).days + 1
    return {
        "ok": True,
        "api_verified": True,
        "version_confirmed": version_confirmed,
        "complete": complete,
        "snapshot_consistent": False,
        "coverage_timezone": "UTC",
        "coverage_start_utc": start.isoformat(),
        "coverage_end_utc_inclusive": end.isoformat(),
        "requested_day_count": requested_days,
        "sample_days_covered": len(days),
        "all_requested_days_have_samples": len(days) == requested_days,
        "order_count": order_count,
        "test_order_count": test_count,
        "cancelled_order_count": cancelled_count,
        "missing_financial_status_count": missing_status_count,
        "currency_codes": sorted(currency_codes),
    }


def _parser() -> argparse.ArgumentParser:
    class SafeArgumentParser(argparse.ArgumentParser):
        def error(self, _message: str) -> None:
            print(json.dumps({"ok": False, "error": "invalid_configuration"}, separators=(",", ":")))
            raise SystemExit(1)

    parser = SafeArgumentParser(description=__doc__)
    parser.add_argument("--allow-sandbox-read", action="store_true")
    parser.add_argument("--shop", required=True, help="Exact shop host, for example example.myshopify.com")
    parser.add_argument("--start-date", required=True, help="Inclusive ISO date, YYYY-MM-DD")
    parser.add_argument("--end-date", required=True, help="Inclusive ISO date, YYYY-MM-DD")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        start, end = _validate_config(args.shop, args.start_date, args.end_date, args.allow_sandbox_read)
        # Read the token only after every non-secret configuration check passes.
        token = os.environ.get(TOKEN_ENV)
        if token is None:
            raise ProbeFailure("access_token_missing")
        with httpx.Client(
            verify=True,
            trust_env=False,
            follow_redirects=False,
            timeout=REQUEST_TIMEOUT_SECONDS,
        ) as client:
            result = probe_with_client(shop=args.shop, start=start, end=end, token=token, client=client)
        print(json.dumps(result, separators=(",", ":"), sort_keys=True))
        return 0
    except ProbeFailure as exc:
        print(json.dumps({"ok": False, "error": exc.code}, separators=(",", ":")))
        return 1
    except Exception:
        # CLI output stays safe if local configuration or the HTTP stack fails unexpectedly.
        print(json.dumps({"ok": False, "error": "probe_failed"}, separators=(",", ":")))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
