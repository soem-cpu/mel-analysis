from io import BytesIO
import hashlib

import pandas as pd
import plotly.express as px
import streamlit as st


st.set_page_config(
    page_title="M&E Comparison",
    page_icon="📊",
    layout="wide",
)

st.title("M&E Comparison")
st.write(
    "Compare multiple metrics by township, quarter or another "
    "selected category."
)


# ===========================
# HELPER FUNCTIONS
# ===========================

DATE_FORMATS = [
    "Automatic: day first",
    "Automatic: month first",
    "YYYY-MM-DD",
    "DD/MM/YYYY",
    "MM/DD/YYYY",
]


def clean_frame(frame):
    frame = frame.copy()
    frame.columns = [
        str(column).strip()
        for column in frame.columns
    ]

    if not len(frame.columns):
        raise ValueError("No columns found. Check the header row.")

    if frame.columns.duplicated().any():
        raise ValueError("Column names must be unique.")

    return frame.dropna(how="all").reset_index(drop=True)


def numeric(series):
    return pd.to_numeric(
        series.astype("string")
        .str.strip()
        .str.replace(",", "", regex=False),
        errors="coerce",
    )


def parse_dates(series, format_name):
    formats = {
        "YYYY-MM-DD": "%Y-%m-%d",
        "DD/MM/YYYY": "%d/%m/%Y",
        "MM/DD/YYYY": "%m/%d/%Y",
    }

    if format_name in formats:
        return pd.to_datetime(
            series,
            format=formats[format_name],
            errors="coerce",
        )

    return pd.to_datetime(
        series,
        format="mixed",
        errors="coerce",
        dayfirst=format_name == "Automatic: day first",
    )


def download(frame, filename, label, key):
    st.download_button(
        label,
        data=frame.to_csv(index=False).encode("utf-8-sig"),
        file_name=filename,
        mime="text/csv",
        key=key,
    )


def aggregate(frame, dimensions, method):
    if not dimensions:
        value = (
            frame["Value"].sum(min_count=1)
            if method == "Sum"
            else frame["Value"].mean()
        )
        return pd.DataFrame({"Value": [value]})

    grouped = frame.groupby(
        dimensions,
        dropna=False,
        sort=False,
    )["Value"]

    result = (
        grouped.sum(min_count=1)
        if method == "Sum"
        else grouped.mean()
    )

    return result.reset_index()


def sort_result(frame, key):
    first, second = st.columns(2)

    with first:
        sort_column = st.selectbox(
            "Sort table by",
            list(frame.columns),
            key=f"{key}_column",
        )

    with second:
        ascending = st.selectbox(
            "Table sort direction",
            ["Ascending", "Descending"],
            key=f"{key}_direction",
        ) == "Ascending"

    if pd.api.types.is_numeric_dtype(frame[sort_column]):
        return frame.sort_values(
            sort_column,
            ascending=ascending,
            kind="stable",
            na_position="last",
        ).reset_index(drop=True)

    return frame.sort_values(
        sort_column,
        ascending=ascending,
        kind="stable",
        na_position="last",
        key=lambda values: values.astype("string").str.casefold(),
    ).reset_index(drop=True)


# ===========================
# UPLOAD
# ===========================

uploaded = st.file_uploader(
    "Upload Excel or CSV",
    type=["xlsx", "csv"],
)

if uploaded is None:
    st.info("Upload a file to begin.")
    st.stop()

content = uploaded.getvalue()
file_id = hashlib.sha256(content).hexdigest()[:12]

try:
    if uploaded.name.lower().endswith(".csv"):
        source_frames = {
            "CSV": clean_frame(
                pd.read_csv(BytesIO(content), dtype=object)
            )
        }

    else:
        workbook = pd.ExcelFile(BytesIO(content))

        selected_sheets = st.multiselect(
            "Select sheets containing your metrics",
            workbook.sheet_names,
            default=workbook.sheet_names[:2],
            key=f"{file_id}_sheets",
        )

        if not selected_sheets:
            st.info("Select at least one sheet.")
            st.stop()

        source_frames = {}

        for sheet in selected_sheets:
            header_row = st.number_input(
                f"Header row: {sheet}",
                min_value=1,
                value=1,
                step=1,
                key=f"{file_id}_{sheet}_header",
            )

            source_frames[sheet] = clean_frame(
                pd.read_excel(
                    BytesIO(content),
                    sheet_name=sheet,
                    header=header_row - 1,
                    dtype=object,
                )
            )

except Exception as error:
    st.error(f"Could not read your file: {error}")
    st.stop()


# ===========================
# CONFIGURE DATA
# ===========================

method = st.selectbox(
    "Combine metric values using",
    ["Sum", "Mean"],
    key=f"{file_id}_aggregation",
)

st.caption(
    "Use Sum for additive counts or amounts. Mean is an unweighted "
    "average of valid source values. Analyse compatible units together."
)

st.subheader("Select metrics and filters")

st.info(
    "Give equivalent metrics the same comparison name across sheets. "
    "For example, use 'People tested' in both sheets. Values with the "
    "same metric name, group and period will be combined."
)

long_frames = []

for sheet, original in source_frames.items():
    with st.expander(f"Data settings: {sheet}", expanded=True):
        if original.empty:
            st.warning("This sheet contains no records.")
            continue

        frame = original.copy()
        columns = list(frame.columns)
        prefix = f"{file_id}_{sheet}"

        metrics = st.multiselect(
            "Select numeric metrics",
            columns,
            key=f"{prefix}_metrics",
        )

        metric_labels = {}

        for metric in metrics:
            label = st.text_input(
                f"Comparison name for '{metric}'",
                value=metric,
                key=f"{prefix}_label_{metric}",
            ).strip()

            if not label:
                st.error("Metric names cannot be blank.")
                st.stop()

            metric_labels[metric] = label

        if len(set(metric_labels.values())) != len(metric_labels):
            st.error(
                "Each selected metric within this sheet "
                "must have a different comparison name."
            )
            st.stop()

        first, second = st.columns(2)

        with first:
            group_column = st.selectbox(
                "Township or other group column",
                ["None"] + columns,
                key=f"{prefix}_group",
            )

        with second:
            period_column = st.selectbox(
                "Quarter, period or date column",
                ["None"] + columns,
                key=f"{prefix}_period",
            )

        period_mode = "Labels"
        parsed_dates = None
        frequency = "Quarter"

        if period_column != "None":
            period_mode = st.radio(
                "Period column contains",
                ["Labels", "Dates"],
                horizontal=True,
                key=f"{prefix}_period_mode",
            )

            if period_mode == "Dates":
                date_format = st.selectbox(
                    "Date format",
                    DATE_FORMATS,
                    key=f"{prefix}_date_format",
                )

                frequency = st.selectbox(
                    "Group dates by",
                    ["Month", "Quarter", "Year"],
                    index=1,
                    key=f"{prefix}_frequency",
                )

                parsed_dates = parse_dates(
                    frame[period_column],
                    date_format,
                )

                valid_dates = parsed_dates.dropna()

                if valid_dates.empty:
                    st.warning(
                        "No valid dates. Check the selected column "
                        "and date format."
                    )
                    continue

                earliest = valid_dates.min().date()
                latest = valid_dates.max().date()

                selected_range = st.date_input(
                    "Filter period: start and end",
                    value=(earliest, latest),
                    min_value=earliest,
                    max_value=latest,
                    key=(
                        f"{prefix}_range_{period_column}_"
                        f"{date_format}_{earliest}_{latest}"
                    ),
                )

                if len(selected_range) != 2:
                    st.info("Select start and end dates.")
                    continue

                start, end = selected_range

                if start > end:
                    st.error("Start date must be before end date.")
                    continue

                invalid_count = int(parsed_dates.isna().sum())
                if invalid_count:
                    st.caption(
                        f"{invalid_count:,} missing or invalid "
                        "dates excluded."
                    )

                mask = (
                    parsed_dates.notna()
                    & (parsed_dates.dt.date >= start)
                    & (parsed_dates.dt.date <= end)
                )

                frame = frame.loc[mask].copy()

            else:
                period_values = (
                    frame[period_column].astype("string")
                    .str.strip()
                    .replace("", pd.NA)
                )

                options = sorted(
                    period_values.dropna().unique().tolist()
                )

                selected_periods = st.multiselect(
                    "Periods to include",
                    options,
                    default=options,
                    key=f"{prefix}_period_values",
                )

                include_missing_period = st.checkbox(
                    "Include missing periods",
                    value=False,
                    key=f"{prefix}_missing_period",
                )

                mask = period_values.isin(selected_periods)

                if include_missing_period:
                    mask = mask | period_values.isna()

                frame = frame.loc[mask].copy()

        filter_columns = st.multiselect(
            "Additional filter columns",
            columns,
            key=f"{prefix}_filter_columns",
            help="For example: township, gender, indicator or programme.",
        )

        for column in filter_columns:
            values = (
                frame[column].astype("string")
                .str.strip()
                .replace("", pd.NA)
            )

            options = sorted(
                values.dropna().unique().tolist()
            )

            selected_values = st.multiselect(
                f"Include values: {column}",
                options,
                default=options,
                key=f"{prefix}_filter_{column}",
            )

            include_missing = st.checkbox(
                f"Include missing values: {column}",
                value=True,
                key=f"{prefix}_missing_{column}",
            )

            mask = values.isin(selected_values)

            if include_missing:
                mask = mask | values.isna()

            frame = frame.loc[mask].copy()

        st.caption(f"Filtered records: {len(frame):,}")

        with st.expander("Preview filtered source data"):
            st.dataframe(
                frame.head(100),
                use_container_width=True,
            )

        download(
            frame,
            f"{sheet}_filtered.csv",
            "Download filtered source data",
            f"{prefix}_download",
        )

        if frame.empty or not metrics:
            continue

        base = pd.DataFrame(index=frame.index)

        if group_column == "None":
            base["Group"] = "All groups"
        else:
            base["Group"] = (
                frame[group_column].astype("string")
                .str.strip()
                .replace("", pd.NA)
                .fillna("(Missing)")
            )

        if period_column == "None":
            base["Period"] = "All periods"

        elif period_mode == "Dates":
            frequency_code = {
                "Month": "M",
                "Quarter": "Q",
                "Year": "Y",
            }[frequency]

            base["Period"] = (
                parsed_dates.loc[frame.index]
                .dt.to_period(frequency_code)
                .astype("string")
            )

        else:
            base["Period"] = (
                frame[period_column].astype("string")
                .str.strip()
                .replace("", pd.NA)
                .fillna("(Missing)")
            )

        for metric in metrics:
            part = base.copy()
            part["Metric"] = metric_labels[metric]
            part["Value"] = numeric(frame[metric])

            invalid_count = int(part["Value"].isna().sum())

            if invalid_count:
                st.caption(
                    f"{metric_labels[metric]}: "
                    f"{invalid_count:,} missing or non-numeric "
                    "values excluded."
                )

            part = part.dropna(subset=["Value"])

            if not part.empty:
                long_frames.append(part)

if not long_frames:
    st.info("Select metrics containing valid numeric data.")
    st.stop()

# Append metric observations. No ID matching is performed.
long_data = pd.concat(long_frames, ignore_index=True)
metric_names = sorted(long_data["Metric"].unique().tolist())

st.caption(
    "Charts and tables combine selected data by metric, group and "
    "period. Sheet names are not comparison categories. "
    "Repeated or overlapping source records remain included."
)

chart_tab, table_tab = st.tabs([
    "Comparison charts",
    "Tables and percentages",
])


# ===========================
# CHARTS
# ===========================

with chart_tab:
    chart_metrics = st.multiselect(
        "Metrics to compare",
        metric_names,
        default=metric_names,
        key=f"{file_id}_chart_metrics",
    )

    chart_dimension = st.selectbox(
        "Compare by",
        ["Group", "Period"],
        format_func=lambda value: {
            "Group": "Township / selected group",
            "Period": "Quarter / selected period",
        }[value],
        key="chart_dimension",
    )

    chart_type = st.selectbox(
        "Chart type",
        ["Bar chart", "Line chart"],
        key="chart_type",
    )

    selected_data = long_data[
        long_data["Metric"].isin(chart_metrics)
    ]

    if selected_data.empty:
        st.info("Select at least one metric.")
    else:
        chart_data = aggregate(
            selected_data,
            [chart_dimension, "Metric"],
            method,
        )

        first, second = st.columns(2)

        with first:
            sort_options = (
                ["Name"] + chart_metrics
            )

            sort_by = st.selectbox(
                "Sort categories by",
                sort_options,
                key=f"{file_id}_chart_sort",
                help="Select a metric to sort by its numeric result.",
            )

        with second:
            ascending = st.selectbox(
                "Sort direction",
                ["Ascending", "Descending"],
                key="chart_direction",
            ) == "Ascending"

        if sort_by == "Name":
            category_order = sorted(
                chart_data[chart_dimension].unique().tolist(),
                key=lambda value: str(value).casefold(),
                reverse=not ascending,
            )

        else:
            ranking = (
                chart_data[
                    chart_data["Metric"] == sort_by
                ]
                .set_index(chart_dimension)["Value"]
                .sort_values(
                    ascending=ascending,
                    kind="stable",
                )
            )

            category_order = ranking.index.tolist()

            remaining = [
                category
                for category in chart_data[
                    chart_dimension
                ].unique()
                if category not in category_order
            ]

            category_order += sorted(
                remaining,
                key=lambda value: str(value).casefold(),
            )

        order_map = {
            category: position
            for position, category in enumerate(category_order)
        }

        chart_data["_order"] = (
            chart_data[chart_dimension].map(order_map)
        )

        chart_data = chart_data.sort_values(
            ["Metric", "_order"]
        ).drop(columns="_order")

        chart_options = {
            "data_frame": chart_data,
            "x": chart_dimension,
            "y": "Value",
            "color": "Metric",
            "category_orders": {
                chart_dimension: category_order
            },
            "labels": {
                "Group": "Township / group",
                "Period": "Quarter / period",
            },
            "title": f"{method} comparison",
        }

        if chart_type == "Bar chart":
            figure = px.bar(
                **chart_options,
                barmode="group",
            )
        else:
            figure = px.line(
                **chart_options,
                markers=True,
            )

        figure.update_xaxes(type="category")

        st.plotly_chart(
            figure,
            use_container_width=True,
        )

        st.dataframe(
            chart_data,
            use_container_width=True,
        )

        download(
            chart_data,
            "chart_comparison.csv",
            "Download chart table",
            "chart_download",
        )

        st.caption(
            "For chronological trends, use periods such as "
            "2026-01 or 2026Q1 and sort by Name, Ascending."
        )


# ===========================
# COMPARISON TABLE
# ===========================

with table_tab:
    st.subheader("Comparison table")

    table_dimensions = st.multiselect(
        "Table breakdown",
        ["Group", "Period"],
        default=["Group", "Period"],
        format_func=lambda value: {
            "Group": "Township / selected group",
            "Period": "Quarter / selected period",
        }[value],
        key="table_dimensions",
    )

    table_metrics = st.multiselect(
        "Metrics in table",
        metric_names,
        default=metric_names,
        key=f"{file_id}_table_metrics",
    )

    table_source = long_data[
        long_data["Metric"].isin(table_metrics)
    ]

    if table_source.empty:
        st.info("Select at least one metric.")
    else:
        table_long = aggregate(
            table_source,
            table_dimensions + ["Metric"],
            method,
        )

        # Prefix metric columns to avoid collisions with
        # dimension names such as Group or Period.
        table_long["Metric column"] = (
            "Metric: " + table_long["Metric"]
        )

        if table_dimensions:
            wide = table_long.pivot(
                index=table_dimensions,
                columns="Metric column",
                values="Value",
            ).reset_index()
        else:
            wide = pd.DataFrame([{
                row["Metric column"]: row["Value"]
                for _, row in table_long.iterrows()
            }])
            wide.insert(0, "Scope", "Overall")

        wide.columns.name = None

        wide_sorted = sort_result(
            wide,
            "comparison_table_sort",
        )

        st.dataframe(
            wide_sorted.round(2),
            use_container_width=True,
        )

        download(
            wide_sorted,
            "comparison_table.csv",
            "Download comparison table",
            "comparison_table_download",
        )


        # ===========================
        # PERCENTAGE TABLE
        # ===========================

        st.subheader("Percentage calculations")

        percent_mode = st.selectbox(
            "Percentage method",
            [
                "Metric divided by another metric",
                "Share of overall total",
            ],
            key="percent_mode",
        )

        available_metrics = sorted(
            table_source["Metric"].unique().tolist()
        )

        if percent_mode == "Metric divided by another metric":
            first, second = st.columns(2)

            with first:
                numerator = st.selectbox(
                    "Numerator metric",
                    available_metrics,
                    key=f"{file_id}_numerator",
                )

            with second:
                denominator = st.selectbox(
                    "Denominator metric",
                    available_metrics,
                    key=f"{file_id}_denominator",
                )

            calculation_method = st.selectbox(
                "Percentage aggregation",
                ["Ratio of sums", "Ratio of means"],
                key="percentage_aggregation",
            )

            percent_aggregate = aggregate(
                table_source,
                table_dimensions + ["Metric"],
                (
                    "Sum"
                    if calculation_method == "Ratio of sums"
                    else "Mean"
                ),
            )

            if table_dimensions:
                percent_wide = percent_aggregate.pivot(
                    index=table_dimensions,
                    columns="Metric",
                    values="Value",
                )
            else:
                percent_wide = pd.DataFrame([{
                    row["Metric"]: row["Value"]
                    for _, row in percent_aggregate.iterrows()
                }])

            # Build output separately so source metric names
            # cannot overwrite calculation column names.
            result = pd.DataFrame(
                {
                    "Numerator": percent_wide[numerator],
                    "Denominator": percent_wide[denominator],
                },
                index=percent_wide.index,
            )

            result["Percent"] = (
                result["Numerator"]
                / result["Denominator"].where(
                    result["Denominator"] > 0
                )
                * 100
            )

            if table_dimensions:
                result = result.reset_index()
            else:
                result.insert(0, "Scope", "Overall")

            st.caption(
                f"Percent = {numerator} ÷ {denominator} × 100. "
                "Missing or non-positive denominators give blanks. "
                "Use equivalent populations and periods. "
                "Ratio of sums is normally appropriate for counts."
            )

        else:
            selected_metric = st.selectbox(
                "Metric for share calculation",
                available_metrics,
                key=f"{file_id}_share_metric",
            )

            share_source = table_source[
                table_source["Metric"] == selected_metric
            ]

            result = aggregate(
                share_source,
                table_dimensions,
                "Sum",
            ).rename(columns={"Value": "Subtotal"})

            if not table_dimensions:
                result.insert(0, "Scope", "Overall")

            total = result["Subtotal"].sum(min_count=1)
            result["Overall total"] = total

            result["Percent"] = (
                result["Subtotal"] / total * 100
                if pd.notna(total) and total > 0
                else float("nan")
            )

            st.caption(
                "Percent = category subtotal ÷ overall filtered "
                "total × 100. This uses sums and is intended "
                "for non-negative additive counts or amounts."
            )

        result = sort_result(
            result,
            f"percentage_sort_{percent_mode}",
        )

        st.dataframe(
            result.round(2),
            use_container_width=True,
        )

        download(
            result,
            "percentage_analysis.csv",
            "Download percentage table",
            "percentage_download",
        )
