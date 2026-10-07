from io import BytesIO
import hashlib

import pandas as pd
import plotly.express as px
import streamlit as st


st.set_page_config(
    page_title="Compare Sheets",
    page_icon="📊",
    layout="wide",
)

st.title("Compare Sheets and Metrics")
st.write(
    "Compare Excel sheets independently. Select multiple metrics, "
    "filter periods and groups, and calculate percentages."
)


# ===========================
# HELPERS
# ===========================

def clean_frame(frame):
    frame = frame.copy()
    frame.columns = [str(column).strip() for column in frame.columns]

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


def dates_from(series, format_name):
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
    grouped = frame.groupby(
        dimensions,
        dropna=False,
        sort=False,
    )["Value"]

    if method == "Sum":
        return grouped.sum(min_count=1).reset_index()

    return grouped.mean().reset_index()


DATE_FORMATS = [
    "Automatic: day first",
    "Automatic: month first",
    "YYYY-MM-DD",
    "DD/MM/YYYY",
    "MM/DD/YYYY",
]


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
        selected_sheets = ["CSV"]
        source_frames = {
            "CSV": clean_frame(
                pd.read_csv(BytesIO(content), dtype=object)
            )
        }

    else:
        workbook = pd.ExcelFile(BytesIO(content))

        selected_sheets = st.multiselect(
            "Sheets to compare",
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
    st.error(f"Could not read the file: {error}")
    st.stop()


# ===========================
# SETTINGS
# ===========================

method = st.selectbox(
    "Combine numeric values using",
    ["Sum", "Mean"],
)

st.caption(
    "Use Sum for additive counts or amounts. Use Mean for "
    "comparable scores. Existing percentages may require weighted "
    "calculations. Compare metrics only when their units are compatible."
)

st.subheader("Configure each sheet")
st.write(
    "Choose columns separately for each sheet. Give equivalent "
    "metrics the same comparison name, such as 'People tested'."
)

long_frames = []
filtered_exports = {}
metric_names = set()

for sheet, original in source_frames.items():
    with st.expander(f"Settings: {sheet}", expanded=True):
        if original.empty:
            st.warning("This sheet is empty.")
            continue

        frame = original.copy()
        columns = list(frame.columns)
        prefix = f"{file_id}_{sheet}"

        st.caption(f"Source records: {len(frame):,}")

        metrics = st.multiselect(
            "Numeric metrics",
            columns,
            key=f"{prefix}_metrics",
        )

        labels = {}
        for metric in metrics:
            label = st.text_input(
                f"Comparison name for {metric}",
                value=metric,
                key=f"{prefix}_label_{metric}",
            ).strip()

            if not label:
                st.error("Comparison names cannot be blank.")
                st.stop()

            labels[metric] = label

        if len(set(labels.values())) != len(labels):
            st.error(
                "Each metric within this sheet needs a different "
                "comparison name."
            )
            st.stop()

        first, second = st.columns(2)

        with first:
            period_column = st.selectbox(
                "Date or period column",
                ["None"] + columns,
                key=f"{prefix}_period",
            )

        with second:
            group_column = st.selectbox(
                "Group column",
                ["None"] + columns,
                key=f"{prefix}_group",
            )

        period_mode = "Labels"
        parsed_dates = None

        if period_column != "None":
            period_mode = st.radio(
                "Period type",
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
                    key=f"{prefix}_frequency",
                )

                parsed_dates = dates_from(
                    frame[period_column], date_format
                )

                valid_dates = parsed_dates.dropna()

                if valid_dates.empty:
                    st.warning("No valid dates for this sheet.")
                    continue

                start_limit = valid_dates.min().date()
                end_limit = valid_dates.max().date()

                selected_range = st.date_input(
                    "Period filter: start and end",
                    value=(start_limit, end_limit),
                    min_value=start_limit,
                    max_value=end_limit,
                    key=(
                        f"{prefix}_range_{period_column}_"
                        f"{date_format}_{start_limit}_{end_limit}"
                    ),
                )

                if len(selected_range) != 2:
                    st.info("Select both start and end dates.")
                    continue

                start_date, end_date = selected_range

                if start_date > end_date:
                    st.error("Start date must be before end date.")
                    continue

                invalid_dates = int(parsed_dates.isna().sum())
                if invalid_dates:
                    st.caption(
                        f"{invalid_dates:,} missing or invalid dates "
                        "excluded."
                    )

                mask = (
                    parsed_dates.notna()
                    & (parsed_dates.dt.date >= start_date)
                    & (parsed_dates.dt.date <= end_date)
                )
                frame = frame.loc[mask].copy()

            else:
                period_values = (
                    frame[period_column].astype("string")
                    .str.strip()
                )
                choices = sorted(
                    period_values.dropna().unique().tolist()
                )

                chosen_periods = st.multiselect(
                    "Periods to include",
                    choices,
                    default=choices,
                    key=f"{prefix}_period_values",
                )
                frame = frame.loc[
                    period_values.isin(chosen_periods)
                ].copy()

        filter_columns = st.multiselect(
            "Additional filter columns",
            columns,
            key=f"{prefix}_filter_columns",
        )

        for column in filter_columns:
            values = frame[column].astype("string")
            options = sorted(
                values.dropna().unique().tolist()
            )

            chosen = st.multiselect(
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

            mask = values.isin(chosen)
            if include_missing:
                mask = mask | values.isna()

            frame = frame.loc[mask].copy()

        st.caption(f"Filtered records: {len(frame):,}")
        filtered_exports[sheet] = frame

        st.dataframe(
            frame.head(30),
            use_container_width=True,
        )

        download(
            frame,
            f"{sheet}_filtered.csv",
            "Download this sheet's filtered data",
            f"{prefix}_download",
        )

        if frame.empty or not metrics:
            continue

        base = pd.DataFrame(index=frame.index)
        base["Sheet"] = sheet

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
            code = {
                "Month": "M",
                "Quarter": "Q",
                "Year": "Y",
            }[frequency]

            base["Period"] = (
                parsed_dates.loc[frame.index]
                .dt.to_period(code)
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
            part["Metric"] = labels[metric]
            part["Value"] = numeric(frame[metric])

            missing = int(part["Value"].isna().sum())
            if missing:
                st.caption(
                    f"{labels[metric]}: {missing:,} missing or "
                    "non-numeric values excluded."
                )

            part = part.dropna(subset=["Value"])
            if not part.empty:
                long_frames.append(part)
                metric_names.add(labels[metric])

if not long_frames:
    st.info(
        "Select numeric metrics with valid data in at least one sheet."
    )
    st.stop()

# Append independent observations. No patient ID merge is performed.
long_data = pd.concat(long_frames, ignore_index=True)

summary = aggregate(
    long_data,
    ["Sheet", "Period", "Group", "Metric"],
    method,
)

st.caption(
    "Sheets remain independent. No UID matching or deduplication "
    "is performed. Use matching period formats, group labels and "
    "metric names when comparing equivalent results."
)


# ===========================
# COMPARISON CHARTS
# ===========================

chart_tab, table_tab = st.tabs([
    "Comparison charts",
    "Tables and percentages",
])

with chart_tab:
    chart_metrics = st.multiselect(
        "Metrics to compare",
        sorted(metric_names),
        default=sorted(metric_names),
        key="chart_metrics",
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
        # Combine equivalent metrics across selected sheets.
        # Sheet is not a comparison dimension.
        chart_data = aggregate(
            selected_data,
            [chart_dimension, "Metric"],
            method,
        )

        first, second = st.columns(2)

        with first:
            sort_by = st.selectbox(
                "Sort categories by",
                ["Name", "Numeric result"],
                key="chart_sort",
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
                chart_data.groupby(chart_dimension)["Value"]
                .sum(min_count=1)
                .sort_values(ascending=ascending)
            )
            category_order = ranking.index.tolist()

        ranks = {
            name: position
            for position, name in enumerate(category_order)
        }

        chart_data["_order"] = (
            chart_data[chart_dimension].map(ranks)
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
            "title": f"{method} comparison by {chart_dimension}",
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


# ===========================
# TABLES AND PERCENTAGES
# ===========================

with table_tab:
    st.subheader("Comparison table")

    table_dimensions = st.multiselect(
        "Table breakdown",
        ["Period", "Group"],
        default=["Period", "Group"],
        key="table_dimensions",
    )

    table_metrics = st.multiselect(
        "Metrics in table",
        sorted(metric_names),
        default=sorted(metric_names),
        key="table_metrics",
    )

    table_source = long_data[
        long_data["Metric"].isin(table_metrics)
    ]

    keys = table_dimensions

    if table_source.empty:
        st.info("Select at least one metric.")
    else:
        table_long = aggregate(
            table_source,
            keys + ["Metric"],
            method,
        )

        wide = table_long.pivot(
            index=keys,
            columns="Metric",
            values="Value",
        ).reset_index()

        wide.columns.name = None

        st.dataframe(wide, use_container_width=True)

        download(
            wide,
            "comparison_table.csv",
            "Download comparison table",
            "comparison_table_download",
        )

        st.subheader("Percentage calculations")

        percent_mode = st.selectbox(
            "Percentage method",
            [
                "Metric divided by another metric",
                "Share of overall total",
            ],
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
                    key="numerator_metric",
                )

            with second:
                denominator = st.selectbox(
                    "Denominator metric",
                    available_metrics,
                    key="denominator_metric",
                )

            result = wide[keys].copy()
            result["Numerator"] = wide[numerator]
            result["Denominator"] = wide[denominator]

            result["Percent"] = (
                result["Numerator"]
                / result["Denominator"].where(
                    result["Denominator"] > 0
                )
                * 100
            )

            st.caption(
                f"Percent = {numerator} / {denominator} × 100. "
                "Missing or non-positive denominators produce blanks. "
                "Both metrics should cover the same population and period."
            )

        elif percent_mode == "Share of overall total":
            selected_metric = st.selectbox(
                "Metric for share calculation",
                available_metrics,
                key="share_metric",
            )

            share_source = table_source[
                table_source["Metric"] == selected_metric
            ]

            if keys:
                result = aggregate(
                    share_source,
                    keys,
                    "Sum",
                ).rename(columns={"Value": "Subtotal"})
            else:
                result = pd.DataFrame({
                    "Subtotal": [
                        share_source["Value"].sum(min_count=1)
                    ]
                })

            total = result["Subtotal"].sum(min_count=1)
            result["Overall total"] = total

            result["Percent"] = (
                result["Subtotal"] / total * 100
                if pd.notna(total) and total > 0
                else float("nan")
            )

            st.caption(
                "Percent = category subtotal / overall filtered "
                "total × 100. Selected sheets contribute to "
                "the overall total."
            )
        else:
            available_sheets = list(
                table_source["Sheet"].unique()
            )

            if len(available_sheets) < 2:
                st.info(
