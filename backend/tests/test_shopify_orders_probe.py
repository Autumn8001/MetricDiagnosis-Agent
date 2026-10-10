from __future__ import annotations

import datetime as dt
import json
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import unittest
from unittest.mock import patch

import httpx

from scripts import probe_shopify_orders as probe


START = dt.date(2026, 9, 1)
END = dt.date(2026, 9, 2)
TOKEN = "probe-secret-token"


def _order(
    order_id: str = "gid://shopify/Order/1",
    *,
    created_at: str = "2026-09-01T12:00:00Z",
    test: bool = False,
    cancelled_at: str | None = None,
    financial_status: str | None = "PAID",
) -> dict[str, object]:
    return {
        "id": order_id,
        "createdAt": created_at,
        "updatedAt": "2026-09-03T12:00:00+00:00",
        "test": test,
        "cancelledAt": cancelled_at,
        "displayFinancialStatus": financial_status,
        "currentSubtotalPriceSet": {
            "shopMoney": {"amount": "14.25", "currencyCode": "USD"}
        },
    }


def _scope_data(scopes: list[str] | None = None) -> dict[str, object]:
    return {
        "data": {
            "currentAppInstallation": {
                "accessScopes": [{"handle": item} for item in (scopes or ["read_orders"])]
            }
        }
    }


def _orders_data(
    nodes: list[dict[str, object]], *, has_next: bool = False, cursor: str | None = None
) -> dict[str, object]:
    return {
        "data": {
            "orders": {
                "nodes": nodes,
                "pageInfo": {"hasNextPage": has_next, "endCursor": cursor},
            }
        }
    }


class ShopifyOrdersProbeTests(unittest.TestCase):
    def _client(self, handler):
        return httpx.Client(transport=httpx.MockTransport(handler), trust_env=False)

    def _probe(self, client: httpx.Client, **kwargs):
        return probe.probe_with_client(
            shop="sandbox-shop.myshopify.com",
            start=START,
            end=END,
            token=TOKEN,
            client=client,
            **kwargs,
        )

    def test_valid_probe_is_aggregate_only_and_uses_fixed_read_only_queries(self) -> None:
        requests: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            body = json.loads(request.content)
            if len(requests) == 1:
                return httpx.Response(200, json=_scope_data())
            return httpx.Response(
                200,
                json=_orders_data(
                    [
                        _order(test=True, financial_status=None),
                        _order(
                            "gid://shopify/Order/2",
                            created_at="2026-09-02T01:00:00-05:00",
                            cancelled_at="2026-09-02T07:00:00Z",
                        ),
                    ]
                ),
            )

        with self._client(handler) as client:
            result = self._probe(client)

        self.assertEqual(len(requests), 2)
        self.assertTrue(all(request.method == "POST" for request in requests))
        self.assertEqual(
            str(requests[0].url),
            "https://sandbox-shop.myshopify.com/admin/api/2026-10/graphql.json",
        )
        for request in requests:
            self.assertEqual(request.headers["X-Shopify-Access-Token"], TOKEN)
            self.assertEqual(request.headers["Accept-Encoding"], "identity")
        scope_payload = json.loads(requests[0].content)
        orders_payload = json.loads(requests[1].content)
        self.assertEqual(scope_payload, {"query": probe.SCOPE_QUERY})
        self.assertEqual(orders_payload["query"], probe.ORDERS_QUERY)
        for query in (scope_payload["query"], orders_payload["query"]):
            self.assertNotIn("mutation", query.lower())
            self.assertNotIn("customer", query.lower())
            self.assertNotIn("email", query.lower())
            self.assertNotIn("address", query.lower())
            self.assertNotIn("lineitems", query.lower())
        self.assertEqual(orders_payload["variables"]["first"], 50)
        self.assertIsNone(orders_payload["variables"]["after"])
        self.assertEqual(
            orders_payload["variables"]["query"],
            "created_at:>='2026-09-01T00:00:00Z' created_at:<'2026-09-03T00:00:00Z'",
        )
        self.assertEqual(
            result,
            {
                "ok": True,
                "api_verified": True,
                "version_confirmed": False,
                "complete": True,
                "snapshot_consistent": False,
                "coverage_timezone": "UTC",
                "coverage_start_utc": "2026-09-01",
                "coverage_end_utc_inclusive": "2026-09-02",
                "requested_day_count": 2,
                "sample_days_covered": 2,
                "all_requested_days_have_samples": True,
                "order_count": 2,
                "test_order_count": 1,
                "cancelled_order_count": 1,
                "missing_financial_status_count": 1,
                "currency_codes": ["USD"],
            },
        )
        output = json.dumps(result)
        self.assertNotIn("gid://", output)
        self.assertNotIn("14.25", output)
        self.assertNotIn(TOKEN, output)

    def test_empty_result_is_complete_but_has_no_sample_coverage(self) -> None:
        responses = iter([_scope_data(), _orders_data([])])
        with self._client(lambda _request: httpx.Response(200, json=next(responses))) as client:
            result = self._probe(client)
        self.assertTrue(result["complete"])
        self.assertFalse(result["all_requested_days_have_samples"])
        self.assertEqual(result["sample_days_covered"], 0)

    def test_next_page_uses_cursor_and_deduplicates_across_pages(self) -> None:
        seen: list[dict[str, object]] = []

        def handler(request: httpx.Request) -> httpx.Response:
            payload = json.loads(request.content)
            seen.append(payload)
            if len(seen) == 1:
                return httpx.Response(200, json=_scope_data())
            after = payload.get("variables", {}).get("after")
            if after is None:
                return httpx.Response(200, json=_orders_data([_order()], has_next=True, cursor="opaque-1"))
            return httpx.Response(200, json=_orders_data([_order("gid://shopify/Order/2")]))

        with self._client(handler) as client:
            result = self._probe(client)
        self.assertEqual(result["order_count"], 2)
        self.assertEqual(seen[2]["variables"]["after"], "opaque-1")

    def test_scope_is_checked_before_orders_request(self) -> None:
        calls: list[int] = []

        def handler(_request: httpx.Request) -> httpx.Response:
            calls.append(1)
            return httpx.Response(200, json=_scope_data(["read_products"]))

        with self._client(handler) as client:
            with self.assertRaisesRegex(probe.ProbeFailure, "required_scope_missing"):
                self._probe(client)
        self.assertEqual(len(calls), 1)

    def test_bad_shop_hosts_and_date_ranges_are_rejected_before_token_access(self) -> None:
        invalid_shops = [
            "https://sandbox-shop.myshopify.com",
            "user@sandbox-shop.myshopify.com",
            "sandbox-shop.myshopify.com/path",
            "sandbox-shop.myshopify.com:443",
            "sandbox-shop.myshopify.com?x=1",
            "sandbox-shop.myshopify.com.",
        ]
        for shop in invalid_shops:
            with self.subTest(shop=shop), self.assertRaisesRegex(probe.ProbeFailure, "invalid_shop_host"):
                probe._validate_config(shop, START.isoformat(), END.isoformat(), True)
        for start, end in [
            ("2026-02-30", "2026-03-01"),
            ("2026-09-01T00:00:00Z", "2026-09-02"),
            ("2026-09-01", "2026-10-02"),
            ("2026-09-03", "2026-09-02"),
            ("9999-12-30", "9999-12-31"),
        ]:
            with self.subTest(start=start, end=end), self.assertRaises(probe.ProbeFailure):
                probe._validate_config("sandbox-shop.myshopify.com", start, end, True)

        stdout = StringIO()
        stderr = StringIO()
        with patch.dict("os.environ", {probe.TOKEN_ENV: TOKEN}):
            with patch.object(probe.os.environ, "get", wraps=probe.os.environ.get) as get_env:
                with patch.object(probe, "probe_with_client", side_effect=AssertionError("must not call")):
                    with redirect_stdout(stdout), redirect_stderr(stderr):
                        exit_code = probe.main(
                            ["--shop", "bad.example", "--start-date", "bad", "--end-date", "bad"]
                        )
                self.assertNotIn(
                    unittest.mock.call(probe.TOKEN_ENV), get_env.call_args_list
                )
        self.assertEqual(exit_code, 1)
        self.assertNotIn("bad.example", stdout.getvalue() + stderr.getvalue())
        self.assertNotIn(TOKEN, stdout.getvalue() + stderr.getvalue())

    def test_sandbox_confirmation_is_mandatory(self) -> None:
        with self.assertRaisesRegex(probe.ProbeFailure, "sandbox_read_confirmation_required"):
            probe._validate_config("sandbox-shop.myshopify.com", START.isoformat(), END.isoformat(), False)

    def test_cli_uses_bounded_secure_client_and_prints_only_summary(self) -> None:
        responses = iter([_scope_data(), _orders_data([_order()])])
        client = self._client(lambda _request: httpx.Response(200, json=next(responses)))
        stdout = StringIO()
        with patch.dict("os.environ", {probe.TOKEN_ENV: TOKEN}):
            with patch.object(probe.httpx, "Client", return_value=client) as factory:
                with redirect_stdout(stdout):
                    exit_code = probe.main(
                        [
                            "--allow-sandbox-read",
                            "--shop",
                            "sandbox-shop.myshopify.com",
                            "--start-date",
                            START.isoformat(),
                            "--end-date",
                            END.isoformat(),
                        ]
                    )
        self.assertEqual(exit_code, 0)
        client_args = factory.call_args.kwargs
        self.assertIs(client_args["verify"], True)
        self.assertIs(client_args["trust_env"], False)
        self.assertIs(client_args["follow_redirects"], False)
        self.assertEqual(client_args["timeout"], probe.REQUEST_TIMEOUT_SECONDS)
        self.assertNotIn("gid://", stdout.getvalue())
        self.assertNotIn(TOKEN, stdout.getvalue())
        client.close()

    def test_scope_graphql_errors_and_http_statuses_return_fixed_codes(self) -> None:
        cases = [
            (httpx.Response(302, headers={"location": "https://private.example/token"}), "http_redirect"),
            (httpx.Response(403, text="private response with " + TOKEN), "http_client_error"),
            (httpx.Response(503, text="private response with " + TOKEN), "http_server_error"),
            (httpx.Response(200, json={"errors": [{"message": TOKEN}], "data": {}}), "graphql_error"),
            (httpx.Response(200, json={"errors": {"message": TOKEN}, "data": {}}), "invalid_graphql_errors"),
            (httpx.Response(200, text="not-json-" + TOKEN), "invalid_json"),
        ]
        for response, expected in cases:
            with self.subTest(code=expected), self._client(lambda _request, response=response: response) as client:
                with self.assertRaises(probe.ProbeFailure) as caught:
                    self._probe(client)
                self.assertEqual(caught.exception.code, expected)
                self.assertNotIn(TOKEN, str(caught.exception))

    def test_response_body_limit_is_enforced(self) -> None:
        body = b"{" + (b" " * probe.MAX_RESPONSE_BYTES) + b"}"
        with self._client(lambda _request: httpx.Response(200, content=body)) as client:
            with self.assertRaisesRegex(probe.ProbeFailure, "response_too_large"):
                self._probe(client)

    def test_duplicate_order_ids_are_rejected(self) -> None:
        responses = iter([_scope_data(), _orders_data([_order(), _order()])])
        with self._client(lambda _request: httpx.Response(200, json=next(responses))) as client:
            with self.assertRaisesRegex(probe.ProbeFailure, "duplicate_or_invalid_order_id"):
                self._probe(client)

    def test_invalid_order_values_are_rejected_without_returning_them(self) -> None:
        invalid_orders = [
            (_order(test="false"), "invalid_test_flag"),  # type: ignore[arg-type]
            (_order(created_at="2026-08-31T23:59:59Z"), "order_outside_requested_range"),
            (_order(created_at="2026-09-01T12:00:00"), "invalid_created_at"),
            (_order(financial_status="SENSITIVE-RAW-VALUE"), "invalid_financial_status"),
        ]
        for node, expected in invalid_orders:
            responses = iter([_scope_data(), _orders_data([node])])
            with self.subTest(code=expected), self._client(
                lambda _request, responses=responses: httpx.Response(200, json=next(responses))
            ) as client:
                with self.assertRaises(probe.ProbeFailure) as caught:
                    self._probe(client)
                self.assertEqual(caught.exception.code, expected)
                self.assertNotIn("SENSITIVE-RAW-VALUE", str(caught.exception))

    def test_cursor_must_be_nonempty_and_advance(self) -> None:
        for cursor in (None, ""):
            responses = iter(
                [_scope_data(), _orders_data([_order()], has_next=True, cursor=cursor)]
            )
            with self.subTest(cursor=cursor), self._client(
                lambda _request, responses=responses: httpx.Response(200, json=next(responses))
            ) as client:
                with self.assertRaisesRegex(probe.ProbeFailure, "invalid_pagination_cursor"):
                    self._probe(client)

        pages = iter(
            [
                _scope_data(),
                _orders_data([_order("gid://shopify/Order/1")], has_next=True, cursor="c1"),
                _orders_data([_order("gid://shopify/Order/2")], has_next=True, cursor="c1"),
            ]
        )
        with self._client(lambda _request: httpx.Response(200, json=next(pages))) as client:
            with self.assertRaisesRegex(probe.ProbeFailure, "invalid_pagination_cursor"):
                self._probe(client)

    def test_page_budget_failure_is_not_reported_as_complete(self) -> None:
        calls = 0

        def handler(_request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            if calls == 1:
                return httpx.Response(200, json=_scope_data())
            page_index = calls - 1
            return httpx.Response(
                200,
                json=_orders_data(
                    [_order(f"gid://shopify/Order/{page_index}")],
                    has_next=True,
                    cursor=f"cursor-{page_index}",
                ),
            )

        with self._client(handler) as client:
            with self.assertRaisesRegex(probe.ProbeFailure, "page_budget_exceeded"):
                self._probe(client)
        self.assertEqual(calls, 1 + probe.MAX_PAGES)

    def test_retry_is_disabled_and_transport_errors_are_redacted(self) -> None:
        calls = 0

        def handler(_request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            raise httpx.ReadTimeout("private timeout text " + TOKEN)

        with self._client(handler) as client:
            with self.assertRaisesRegex(probe.ProbeFailure, "request_timeout") as caught:
                self._probe(client)
        self.assertEqual(calls, 1)
        self.assertNotIn(TOKEN, str(caught.exception))

    def test_present_but_mismatched_api_version_fails(self) -> None:
        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=_scope_data(), headers={"X-Shopify-API-Version": "2025-10"})

        with self._client(handler) as client:
            with self.assertRaisesRegex(probe.ProbeFailure, "api_version_mismatch"):
                self._probe(client)

    def test_total_time_budget_stops_before_next_request(self) -> None:
        calls = []
        def handler(request):
            calls.append(request)
            return httpx.Response(200, json=_scope_data())
        with self._client(handler) as client, patch.object(
            probe.time, "monotonic", side_effect=[0.0, 61.0]
        ):
            with self.assertRaisesRegex(probe.ProbeFailure, "total_time_budget_exceeded"):
                self._probe(client)
        self.assertEqual(calls, [])

    def test_direct_entry_rejects_untrusted_host_without_network(self) -> None:
        calls = []
        with self._client(lambda request: calls.append(request)) as client:
            with self.assertRaisesRegex(probe.ProbeFailure, "invalid_shop_host"):
                probe.probe_with_client(
                    shop="private.example", start=START, end=END, token=TOKEN, client=client
                )
        self.assertEqual(calls, [])

    def test_invalid_scope_and_order_shapes_fail_closed(self) -> None:
        malformed_scope = {"data": {"currentAppInstallation": {"accessScopes": "read_orders"}}}
        with self._client(lambda _request: httpx.Response(200, json=malformed_scope)) as client:
            with self.assertRaisesRegex(probe.ProbeFailure, "invalid_scope_response"):
                self._probe(client)

        pages = iter([_scope_data(), {"data": {"orders": {"nodes": [], "pageInfo": {"hasNextPage": 0}}}}])
        with self._client(lambda _request: httpx.Response(200, json=next(pages))) as client:
            with self.assertRaisesRegex(probe.ProbeFailure, "invalid_page_info"):
                self._probe(client)

        missing_nullable_field = _order()
        del missing_nullable_field["cancelledAt"]
        pages = iter([_scope_data(), _orders_data([missing_nullable_field])])
        with self._client(lambda _request: httpx.Response(200, json=next(pages))) as client:
            with self.assertRaisesRegex(probe.ProbeFailure, "missing_nullable_order_field"):
                self._probe(client)


if __name__ == "__main__":
    unittest.main()
