"""Analytics query tools for MetricSleuth."""

from collections.abc import Mapping, Sequence
import datetime
from decimal import Decimal
from typing import Any

from psycopg import sql

from app.analytics.models import (
    DateRange,
    MetricQueryError,
    MetricQueryRow,
    MetricQueryResult,
    RelatedMetricQueryResult,
)
from app.data_sources.capabilities import CapabilityContractError, DataSourceCapabilities
from app.metrics.registry import MetricDefinition, MetricRegistry


class AnalyticsTools:
    """Provides controlled database query capabilities driven by MetricRegistry."""

    def __init__(
        self,
        registry: MetricRegistry,
        connection: Any,
        capabilities: DataSourceCapabilities | None = None,
    ) -> None:
        """Initialize with a registry, connection, and optional source contract.

        ``capabilities`` is intentionally optional to preserve existing callers
        and hermetic tests. When supplied, it is checked before any SQL is
        executed; capability-domain failures are translated to
        ``MetricQueryError`` at the analytics boundary.
        """
        self._registry = registry
        self._connection = connection
        if capabilities is not None and not isinstance(capabilities, DataSourceCapabilities):
            raise TypeError(
                "capabilities must be a DataSourceCapabilities instance or None"
            )
        self._capabilities = capabilities

    def get_metric_definition(self, metric: str) -> MetricDefinition:
        """Retrieve the immutable MetricDefinition for a given metric identifier."""
        try:
            return self._registry.get(metric)
        except Exception as e:
            raise MetricQueryError(f"Failed to get metric definition: {e}") from e

    def query_metric(
        self,
        metric: str,
        start_date: datetime.date,
        end_date: datetime.date,
        compare_to: str,
        filters: Mapping[str, str] | None = None,
        group_by: Sequence[str] | None = None,
    ) -> MetricQueryResult:
        """Execute a controlled metric aggregation query comparing current date with baseline.

        Args:
            metric: Metric ID defined in MetricRegistry.
            start_date: Single current period date.
            end_date: Must equal start_date (single UTC day).
            compare_to: Must be 'previous_7_days'.
            filters: Optional dictionary mapping dimension names to string values.
            group_by: Optional sequence of dimension names to group results by.

        Returns:
            MetricQueryResult containing structured and typed query rows.
        """
        if self._capabilities is not None:
            try:
                self._capabilities.validate_query(
                    metric_id=metric,
                    group_by=group_by,
                    filters=filters,
                )
            except CapabilityContractError as exc:
                raise MetricQueryError(
                    f"Data source capability validation failed: {exc}"
                ) from exc

        if not self._registry.has_metric(metric):
            raise MetricQueryError(f"Unknown metric: '{metric}'")

        metric_def = self._registry.get(metric)

        if start_date != end_date:
            raise MetricQueryError(
                f"Only single-day current period (start_date == end_date) is currently supported. "
                f"Got start_date={start_date}, end_date={end_date}"
            )

        if compare_to != "previous_7_days":
            raise MetricQueryError(
                f"Unsupported compare_to: '{compare_to}'. Only 'previous_7_days' is supported in Phase 3."
            )

        validated_filters: dict[str, str] = {}
        if filters:
            for k, v in filters.items():
                if k not in metric_def.dimensions:
                    raise MetricQueryError(
                        f"Invalid filter dimension '{k}' for metric '{metric}'. "
                        f"Supported dimensions: {metric_def.dimensions}"
                    )
                if not isinstance(v, str):
                    raise MetricQueryError(
                        f"Filter value for dimension '{k}' must be a string, got {type(v).__name__}"
                    )
                validated_filters[k] = v

        normalized_group_by: tuple[str, ...] = ()
        if group_by:
            group_list = list(group_by)
            if len(group_list) != len(set(group_list)):
                raise MetricQueryError(f"Duplicate dimensions in group_by: {group_by}")
            for g in group_list:
                if g not in metric_def.dimensions:
                    raise MetricQueryError(
                        f"Invalid group_by dimension '{g}' for metric '{metric}'. "
                        f"Supported dimensions: {metric_def.dimensions}"
                    )
            normalized_group_by = tuple(group_list)

        current_date = start_date
        baseline_start = current_date - datetime.timedelta(days=7)
        baseline_end = current_date - datetime.timedelta(days=1)

        current_period = DateRange(start_date=current_date, end_date=current_date)
        baseline_period = DateRange(start_date=baseline_start, end_date=baseline_end)

        rows = self._execute_metric_query(
            metric_def=metric_def,
            current_date=current_date,
            baseline_start=baseline_start,
            baseline_end=baseline_end,
            filters=validated_filters,
            group_by=normalized_group_by,
        )

        return MetricQueryResult(
            metric_id=metric_def.metric_id,
            unit=metric_def.unit,
            current_period=current_period,
            baseline_period=baseline_period,
            group_by=normalized_group_by,
            rows=tuple(rows),
        )

    def query_related_metrics(
        self,
        metric: str,
        start_date: datetime.date,
        end_date: datetime.date,
        compare_to: str,
        filters: Mapping[str, str] | None = None,
        group_by: Sequence[str] | None = None,
    ) -> RelatedMetricQueryResult:
        """Query all related metrics for a given source metric in declared order.

        Args:
            metric: Source metric ID defined in MetricRegistry.
            start_date: Single current period date.
            end_date: Must equal start_date (single UTC day).
            compare_to: Must be 'previous_7_days'.
            filters: Optional dictionary mapping dimension names to string values.
            group_by: Optional sequence of dimension names to group results by.

        Returns:
            RelatedMetricQueryResult containing structured results for all related metrics.
        """
        if not self._registry.has_metric(metric):
            raise MetricQueryError(f"Unknown metric: '{metric}'")

        related_defs = self._registry.get_related_metrics(metric)

        results: list[MetricQueryResult] = []
        for rel_def in related_defs:
            res = self.query_metric(
                metric=rel_def.metric_id,
                start_date=start_date,
                end_date=end_date,
                compare_to=compare_to,
                filters=filters,
                group_by=group_by,
            )
            results.append(res)

        return RelatedMetricQueryResult(
            source_metric_id=metric,
            results=tuple(results),
        )

    def _execute_metric_query(
        self,
        metric_def: MetricDefinition,
        current_date: datetime.date,
        baseline_start: datetime.date,
        baseline_end: datetime.date,
        filters: dict[str, str],
        group_by: tuple[str, ...],
    ) -> list[MetricQueryRow]:
        """Build and execute parameterized SQL via psycopg.sql identifiers and placeholders."""
        table_parts = self._registry.table.split(".")
        table_ident = sql.SQL(".").join(sql.Identifier(p) for p in table_parts)
        time_col_ident = sql.Identifier(self._registry.time_dimension)
        sample_size_ident = sql.Identifier(self._registry.sample_size_field)

        if metric_def.metric_type == "additive":
            field_ident = sql.Identifier(metric_def.source_fields[0])
            base_select_num = sql.SQL("SUM({})").format(field_ident)
            base_select_den = sql.SQL("NULL::numeric")
            curr_select_num = sql.SQL("SUM({})").format(field_ident)
            curr_select_den = sql.SQL("NULL::numeric")
        elif metric_def.metric_type == "ratio":
            num_ident = sql.Identifier(metric_def.source_fields[0])
            den_ident = sql.Identifier(metric_def.source_fields[1])
            base_select_num = sql.SQL("SUM({})").format(num_ident)
            base_select_den = sql.SQL("SUM({})").format(den_ident)
            curr_select_num = sql.SQL("SUM({})").format(num_ident)
            curr_select_den = sql.SQL("SUM({})").format(den_ident)
        else:
            raise MetricQueryError(f"Unsupported metric_type: '{metric_def.metric_type}'")

        base_where_clauses = [
            sql.SQL("{} >= %s AND {} <= %s").format(time_col_ident, time_col_ident)
        ]
        base_params: list[Any] = [baseline_start, baseline_end]

        curr_where_clauses = [sql.SQL("{} = %s").format(time_col_ident)]
        curr_params: list[Any] = [current_date]

        for k, v in filters.items():
            filter_ident = sql.Identifier(k)
            base_where_clauses.append(sql.SQL("{} = %s").format(filter_ident))
            base_params.append(v)
            curr_where_clauses.append(sql.SQL("{} = %s").format(filter_ident))
            curr_params.append(v)

        base_where_sql = sql.SQL(" AND ").join(base_where_clauses)
        curr_where_sql = sql.SQL(" AND ").join(curr_where_clauses)

        num_group_cols = len(group_by)

        if num_group_cols > 0:
            group_idents = [sql.Identifier(g) for g in group_by]
            group_sql = sql.SQL(", ").join(group_idents)

            coalesce_cols = [
                sql.SQL("COALESCE(curr.{}, base.{}) AS {}").format(
                    ident, ident, ident
                )
                for ident in group_idents
            ]
            coalesce_sql = sql.SQL(", ").join(coalesce_cols)

            join_conditions = [
                sql.SQL("curr.{} = base.{}").format(ident, ident)
                for ident in group_idents
            ]
            join_sql = sql.SQL(" AND ").join(join_conditions)

            order_by_sql = sql.SQL(", ").join(
                sql.SQL("COALESCE(curr.{}, base.{})").format(ident, ident)
                for ident in group_idents
            )

            query = sql.SQL(
                """
                WITH base AS (
                    SELECT
                        {group_sql},
                        {base_select_num} AS base_num,
                        {base_select_den} AS base_den,
                        (SUM({sample_size_ident})::numeric / 7.0) AS base_sessions_avg,
                        COUNT(DISTINCT {time_col_ident}) AS base_days_count
                    FROM {table_ident}
                    WHERE {base_where_sql}
                    GROUP BY {group_sql}
                ),
                curr AS (
                    SELECT
                        {group_sql},
                        {curr_select_num} AS curr_num,
                        {curr_select_den} AS curr_den
                    FROM {table_ident}
                    WHERE {curr_where_sql}
                    GROUP BY {group_sql}
                )
                SELECT
                    {coalesce_sql},
                    base.base_num,
                    base.base_den,
                    base.base_sessions_avg,
                    base.base_days_count,
                    curr.curr_num,
                    curr.curr_den
                FROM base
                FULL OUTER JOIN curr ON {join_sql}
                ORDER BY {order_by_sql}
                """
            ).format(
                group_sql=group_sql,
                base_select_num=base_select_num,
                base_select_den=base_select_den,
                time_col_ident=time_col_ident,
                sample_size_ident=sample_size_ident,
                table_ident=table_ident,
                base_where_sql=base_where_sql,
                curr_select_num=curr_select_num,
                curr_select_den=curr_select_den,
                curr_where_sql=curr_where_sql,
                coalesce_sql=coalesce_sql,
                join_sql=join_sql,
                order_by_sql=order_by_sql,
            )
        else:
            query = sql.SQL(
                """
                WITH base AS (
                    SELECT
                        {base_select_num} AS base_num,
                        {base_select_den} AS base_den,
                        (SUM({sample_size_ident})::numeric / 7.0) AS base_sessions_avg,
                        COUNT(DISTINCT {time_col_ident}) AS base_days_count
                    FROM {table_ident}
                    WHERE {base_where_sql}
                ),
                curr AS (
                    SELECT
                        {curr_select_num} AS curr_num,
                        {curr_select_den} AS curr_den
                    FROM {table_ident}
                    WHERE {curr_where_sql}
                )
                SELECT
                    base.base_num,
                    base.base_den,
                    base.base_sessions_avg,
                    base.base_days_count,
                    curr.curr_num,
                    curr.curr_den
                FROM base
                CROSS JOIN curr
                """
            ).format(
                base_select_num=base_select_num,
                base_select_den=base_select_den,
                time_col_ident=time_col_ident,
                sample_size_ident=sample_size_ident,
                table_ident=table_ident,
                base_where_sql=base_where_sql,
                curr_select_num=curr_select_num,
                curr_select_den=curr_select_den,
                curr_where_sql=curr_where_sql,
            )

        all_params = base_params + curr_params

        with self._connection.cursor() as cur:
            cur.execute(query, all_params)
            db_rows = cur.fetchall()

        result_rows: list[MetricQueryRow] = []
        for db_row in db_rows:
            if num_group_cols > 0:
                dim_dict = {
                    group_by[i]: str(db_row[i]) if db_row[i] is not None else ""
                    for i in range(num_group_cols)
                }
                base_num_raw = db_row[num_group_cols]
                base_den_raw = db_row[num_group_cols + 1]
                base_sess_raw = db_row[num_group_cols + 2]
                base_days_raw = db_row[num_group_cols + 3]
                curr_num_raw = db_row[num_group_cols + 4]
                curr_den_raw = db_row[num_group_cols + 5]
            else:
                dim_dict = {}
                base_num_raw = db_row[0]
                base_den_raw = db_row[1]
                base_sess_raw = db_row[2]
                base_days_raw = db_row[3]
                curr_num_raw = db_row[4]
                curr_den_raw = db_row[5]

            base_days = int(base_days_raw) if base_days_raw is not None else 0
            sample_size = (
                Decimal(str(base_sess_raw)) if base_sess_raw is not None else None
            )

            # Compute current and baseline values based on metric type
            if metric_def.metric_type == "additive":
                curr_value = (
                    Decimal(str(curr_num_raw)) if curr_num_raw is not None else None
                )
                base_value = (
                    (Decimal(str(base_num_raw)) / Decimal("7"))
                    if base_num_raw is not None
                    else None
                )
            else:  # ratio
                curr_num = (
                    Decimal(str(curr_num_raw)) if curr_num_raw is not None else None
                )
                curr_den = (
                    Decimal(str(curr_den_raw)) if curr_den_raw is not None else None
                )
                base_num = (
                    Decimal(str(base_num_raw)) if base_num_raw is not None else None
                )
                base_den = (
                    Decimal(str(base_den_raw)) if base_den_raw is not None else None
                )

                if curr_num is not None and curr_den is not None and curr_den > 0:
                    curr_value = curr_num / curr_den
                else:
                    curr_value = None

                if base_num is not None and base_den is not None and base_den > 0:
                    base_value = base_num / base_den
                else:
                    base_value = None

            # Status and relative_change determination
            if (
                sample_size is None
                or sample_size < Decimal("30")
                or base_days < 7
                or curr_num_raw is None
                or base_num_raw is None
            ):
                status = "insufficient_data"
                relative_change = None
            elif (
                curr_value is None
                or base_value is None
                or base_value == Decimal("0")
            ):
                status = "unavailable"
                relative_change = None
            else:
                status = "ok"
                relative_change = (curr_value - base_value) / base_value

            result_rows.append(
                MetricQueryRow(
                    dimensions=dim_dict,
                    current_value=curr_value,
                    baseline_value=base_value,
                    relative_change=relative_change,
                    status=status,
                    sample_size=sample_size,
                )
            )

        return result_rows
