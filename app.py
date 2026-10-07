from io import BytesIO
import hashlib

import pandas as pd
import plotly.express as px
import streamlit as st


st.set_page_config(
    page_title="M&E Dashboard",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
.block-container {padding-top: 2rem;}
[data-testid="stMetric"] {
    background: #f0f6fa;
    padding: 16px;
    border-radius: 12px;
}
</style>
""", unsafe_allow_html=True)


# ---------------------------
# Helpers
# ---------------------------

def number(series):
    return pd.to_numeric(
        series.astype("string").str.strip()
        .str.replace(",", "", regex=False),
        errors="coerce",
    )


def summarise(data, dimensions, method):
    grouped = data.groupby(
        dimensions, dropna=False, sort=False
    )["Value"]

    result = (
        grouped.sum(min_count=1)
        if method == "Total"
        else grouped.mean()
    )
    return result.reset_index()


def download(data, name, key):
    st.download_button(
        "⬇ Download table",
        data.to_csv(index=False).encode("utf-8-sig"),
        file_name=name,
        mime="text/csv",
        key=key,
    )


def preferred_column(columns, keywords):
    for keyword in keywords:
        for index, column in enumerate(columns):
            if keyword in column.lower():
                return index + 1
    return 0


def category_order(table, category, metric, direction):
    ascending = direction == "Smallest first"

    if metric == "Name":
        return sorted(
            table[category].unique(),
            key=lambda item: str(item).casefold(),
            reverse=direction == "Largest first",
        )

    ranking = (
        table[table["Metric"] == metric]
        .set_index(category)["Value"]
        .sort_values(ascending=ascending)
    )
    order = ranking.index.tolist()
    order += [
        value for value in table[category].unique()
        if value not in order
    ]
    return order


# ---------------------------
# Header and upload
# ---------------------------

st.title("📊 M&E Dashboard")
st.caption("Upload your data • Choose metrics • Explore results")

with st.sidebar:
    st.header("1 · Upload data")
    uploaded = st.file_uploader(
        "Excel or CSV file",
        type=["xlsx", "csv"],
    )

if uploaded is None:
    st.info("👈 Upload an Excel or CSV file in the sidebar.")

    a, b, c = st.columns(3)
    a.markdown("### 📁 Upload\nUse one or several Excel sheets.")
    b.markdown("### 🎯 Select\nChoose metrics, township and period.")
    c.markdown("### 📈 Explore\nView charts, tables and percentages.")
    st.stop()

content = uploaded.getvalue()
file_key = hashlib.sha256(content).hexdigest()[:10]

try:
    with st.sidebar:
        if uploaded.name.lower().endswith(".csv"):
            sheet_names = ["CSV"]
            selected_sheets = sheet_names
        else:
            workbook = pd.ExcelFile(BytesIO(content))
            sheet_names = workbook.sheet_names
            selected_sheets = st.multiselect(
                "Use these sheets",
                sheet_names,
                default=sheet_names[:2],
                key=f"{file_key}_sheets",
            )

        with st.expander("File settings"):
            header_row = st.number_input(
                "Header row",
                min_value=1,
                value=1,
                help="Use 2 if column names are in row two.",
            )

    if not selected_sheets:
        st.info("Select a sheet in the sidebar.")
        st.stop()

    frames = {}

    for sheet in selected_sheets:
        if sheet == "CSV" and uploaded.name.lower().endswith(".csv"):
            frame = pd.read_csv(
                BytesIO(content),
                header=header_row - 1,
                dtype=object,
            )
        else:
            frame = pd.read_excel(
                BytesIO(content),
                sheet_name=sheet,
                header=header_row - 1,
                dtype=object,
            )

        frame.columns = [str(c).strip() for c in frame.columns]

        if frame.columns.duplicated().any():
            raise ValueError(f"Duplicate column names in {sheet}.")

        frames[sheet] = frame.dropna(how="all")

except Exception as error:
    st.error(f"Could not read the file: {error}")
    st.stop()


# ---------------------------
# Simple sidebar configuration
# ---------------------------

observations = []
record_count = 0

with st.sidebar:
    st.header("2 · Select data")

    method = st.radio(
        "Show",
        ["Total", "Average"],
        horizontal=True,
        help="Total adds values. Average uses valid numeric records.",
    )

    for sheet, original in frames.items():
        with st.expander(
            f"📄 {sheet}",
            expanded=len(frames) == 1,
        ):
            columns = original.columns.tolist()
            key = f"{file_key}_{sheet}"

            metrics = st.multiselect(
                "Metrics to compare",
                columns,
                key=f"{key}_metrics",
                help="Select counts, amounts or scores.",
            )

            group_column = st.selectbox(
                "Township / category",
                ["None"] + columns,
                index=preferred_column(
                    columns, ["township", "organization", "gender"]
                ),
                key=f"{key}_group",
            )

            period_column = st.selectbox(
                "Quarter / period",
                ["None"] + columns,
                index=preferred_column(
                    columns, ["quarter", "month", "year", "date"]
                ),
                key=f"{key}_period",
            )

            frame = original.copy()
            period_values = pd.Series(
                "All periods", index=frame.index, dtype="string"
            )

            if period_column != "None":
                period_values = (
                    frame[period_column].astype("string")
                    .str.strip().replace("", pd.NA)
                )

                is_date = st.checkbox(
                    "This column contains full dates",
                    key=f"{key}_is_date",
                )

                if is_date:
                    day_first = st.checkbox(
                        "Day comes before month",
                        value=True,
                        key=f"{key}_day_first",
                    )
                    frequency = st.selectbox(
                        "Summarise dates by",
                        ["Quarter", "Month", "Year"],
                        key=f"{key}_frequency",
                    )

                    parsed = pd.to_datetime(
                        frame[period_column],
                        format="mixed",
                        dayfirst=day_first,
                        errors="coerce",
                    )

                    code = {
                        "Quarter": "Q", "Month": "M", "Year": "Y"
                    }[frequency]

                    period_values = parsed.dt.to_period(code).astype("string")
                    period_values = period_values.mask(parsed.isna())

                    valid = parsed.dropna()

                    if not valid.empty:
                        start_limit = valid.min().date()
                        end_limit = valid.max().date()

                        selected_range = st.date_input(
                            "Date range",
                            value=(start_limit, end_limit),
                            min_value=start_limit,
                            max_value=end_limit,
                            key=f"{key}_range_{period_column}_{day_first}",
                        )

                        if len(selected_range) != 2:
                            st.info("Select both dates.")
                            continue

                        start, end = selected_range
                        if start > end:
                            st.error("Start date must be before end date.")
                            continue

                        mask = (
                            parsed.notna()
                            & (parsed.dt.date >= start)
                            & (parsed.dt.date <= end)
                        )
                        frame = frame.loc[mask].copy()

                        invalid = int(parsed.isna().sum())
                        if invalid:
                            st.caption(
                                f"{invalid:,} invalid or missing dates excluded."
                            )
                    else:
                        st.warning("No valid dates in this column.")
                        continue

                choices = sorted(
                    period_values.loc[frame.index]
                    .dropna().unique().tolist()
                )
                chosen = st.multiselect(
                    "Periods",
                    choices,
                    default=choices,
                    key=f"{key}_period_filter_{period_column}_{is_date}",
                )
                frame = frame.loc[
                    period_values.loc[frame.index].isin(chosen)
                ].copy()

            if group_column != "None":
                group_values = (
                    frame[group_column].astype("string")
                    .str.strip().replace("", pd.NA)
                    .fillna("(Missing)")
                )
                choices = sorted(group_values.unique().tolist())
                chosen = st.multiselect(
                    "Townships / categories",
                    choices,
                    default=choices,
                    key=f"{key}_group_filter_{group_column}",
                )
                frame = frame.loc[group_values.isin(chosen)].copy()

            with st.expander("More options"):
                extra_filters = st.multiselect(
                    "Other filters",
                    columns,
                    key=f"{key}_other_filters",
                )

                for column in extra_filters:
                    values = (
                        frame[column].astype("string")
                        .str.strip().replace("", pd.NA)
                        .fillna("(Missing)")
                    )
                    options = sorted(values.unique().tolist())
                    chosen = st.multiselect(
                        column,
                        options,
                        default=options,
                        key=f"{key}_extra_{column}",
                    )
                    frame = frame.loc[values.isin(chosen)].copy()

                labels = {}
                for metric in metrics:
                    labels[metric] = st.text_input(
                        f"Display name: {metric}",
                        value=metric,
                        key=f"{key}_label_{metric}",
                    ).strip()

                st.caption(
                    "Use the same display name for equivalent "
                    "metrics in different sheets."
                )

            if any(not label for label in labels.values()):
                st.error("Metric display names cannot be blank.")
                continue

            if len(set(labels.values())) != len(labels):
                st.error("Use different names for metrics within this sheet.")
                continue

            st.caption(f"{len(frame):,} records after filters")

            if not metrics or frame.empty:
                continue

            record_count += len(frame)

            for metric in metrics:
                values = number(frame[metric])
                part = pd.DataFrame(index=frame.index)

                part["Group"] = (
                    frame[group_column].astype("string")
                    .str.strip().replace("", pd.NA).fillna("(Missing)")
                    if group_column != "None"
                    else "All groups"
                )
                part["Period"] = period_values.loc[frame.index]
                part["Metric"] = labels[metric]
                part["Value"] = values

                missing = int(values.isna().sum())
                if missing:
                    st.caption(
                        f"{labels[metric]}: {missing:,} non-numeric "
                        "or missing values excluded."
                    )

                part = part.dropna(subset=["Value", "Period"])
                if not part.empty:
                    observations.append(part)

if not observations:
    st.info(
        "👈 Open a sheet under 'Select data', then select "
        "one or more numeric metrics."
    )
    st.stop()

data = pd.concat(observations, ignore_index=True)
metric_names = sorted(data["Metric"].unique().tolist())


# ---------------------------
# Main overview
# ---------------------------

a, b, c = st.columns(3)
a.metric("Filtered source records", f"{record_count:,}")
b.metric("Metrics", len(metric_names))
c.metric("Townships / categories", data["Group"].nunique())

st.caption(
    "Equivalent metrics are combined across selected sheets. "
    "Source records are included as supplied."
)

chart_tab, table_tab, percent_tab = st.tabs([
    "📊 Charts", "📋 Tables", "🔢 Percentages"
])


# ---------------------------
# Charts
# ---------------------------

with chart_tab:
    left, right = st.columns(2)

    with left:
        category = st.radio(
            "Compare by",
            ["Group", "Period"],
            format_func=lambda x: (
                "Township / category" if x == "Group"
                else "Quarter / period"
            ),
            horizontal=True,
        )

    with right:
        chart_type = st.radio(
            "Chart",
            ["Bars", "Trend"],
            horizontal=True,
        )

    selected_metrics = st.multiselect(
        "Show metrics",
        metric_names,
        default=metric_names,
        key=f"{file_key}_visible_metrics",
    )

    chart_source = data[data["Metric"].isin(selected_metrics)]

    if chart_source.empty:
        st.info("Select a metric to display.")
    else:
        chart_data = summarise(
            chart_source, [category, "Metric"], method
        )

        with st.expander("Sort chart"):
            a, b = st.columns(2)
            with a:
                sort_metric = st.selectbox(
                    "Sort by",
                    ["Name"] + selected_metrics,
                )
            with b:
                direction = st.selectbox(
                    "Order",
                    ["Smallest first", "Largest first"],
                )

        order = category_order(
            chart_data, category, sort_metric, direction
        )
        ranks = {value: i for i, value in enumerate(order)}
        chart_data["_order"] = chart_data[category].map(ranks)
        chart_data = chart_data.sort_values(
            ["Metric", "_order"]
        ).drop(columns="_order")

        options = dict(
            data_frame=chart_data,
            x=category,
            y="Value",
            color="Metric",
            category_orders={category: order},
            template="plotly_white",
            color_discrete_sequence=px.colors.qualitative.Safe,
            labels={
                "Group": "Township / category",
                "Period": "Quarter / period",
                "Value": method,
            },
        )

        if chart_type == "Bars":
            figure = px.bar(
                **options,
                barmode="group",
                text_auto=".3s",
            )
        else:
            figure = px.line(**options, markers=True)

        figure.update_xaxes(type="category")
        figure.update_layout(
            height=480,
            legend_title_text="",
            margin=dict(t=30, b=30),
        )
        st.plotly_chart(figure, use_container_width=True)

        if chart_type == "Trend":
            st.caption(
                "Use periods such as 2026-01 or 2026Q1 and "
                "sort by Name, Smallest first for chronological order."
            )

        download(chart_data, "chart_data.csv", "chart_download")


# ---------------------------
# Table configuration
# ---------------------------

with table_tab:
    breakdown = st.multiselect(
        "Break table down by",
        ["Group", "Period"],
        default=["Group", "Period"],
        format_func=lambda x: (
            "Township / category" if x == "Group"
            else "Quarter / period"
        ),
    )

    summary = summarise(
        data, breakdown + ["Metric"], method
    )

    # Prefix columns to prevent collisions with Group or Period.
    summary["Metric column"] = "Metric: " + summary["Metric"]

    if breakdown:
        table = summary.pivot(
            index=breakdown,
            columns="Metric column",
            values="Value",
        ).reset_index()
    else:
        table = pd.DataFrame([{
            row["Metric column"]: row["Value"]
            for _, row in summary.iterrows()
        }])
        table.insert(0, "Scope", "Overall")

    table.columns.name = None
    st.dataframe(table.round(2), use_container_width=True)
    st.caption("Click a column heading to sort the displayed table.")
    download(table, "comparison_table.csv", "table_download")


# ---------------------------
# Percentages
# ---------------------------

with percent_tab:
    percent_mode = st.radio(
        "Calculate",
        ["One metric ÷ another", "Share of total"],
        horizontal=True,
    )

    percent_breakdown = st.multiselect(
        "Calculate for each",
        ["Group", "Period"],
        default=["Group"],
        format_func=lambda x: (
            "Township / category" if x == "Group"
            else "Quarter / period"
        ),
        key="percent_breakdown",
    )

    totals = summarise(
        data, percent_breakdown + ["Metric"], "Total"
    )

    if percent_mode == "One metric ÷ another":
        a, b = st.columns(2)
        with a:
            numerator = st.selectbox(
                "Numerator",
                metric_names,
                key=f"{file_key}_numerator",
            )
        with b:
            denominator = st.selectbox(
                "Denominator",
                metric_names,
                key=f"{file_key}_denominator",
            )

        if percent_breakdown:
            wide = totals.pivot(
                index=percent_breakdown,
                columns="Metric",
                values="Value",
            )
        else:
            wide = pd.DataFrame([{
                row["Metric"]: row["Value"]
                for _, row in totals.iterrows()
            }])

        result = pd.DataFrame(
            {
                "Numerator": wide[numerator],
                "Denominator": wide[denominator],
            },
            index=wide.index,
        )
        result["Percent"] = (
            result["Numerator"]
            / result["Denominator"].where(result["Denominator"] > 0)
            * 100
        )

        if percent_breakdown:
            result = result.reset_index()
        else:
            result.insert(0, "Scope", "Overall")

        st.caption(
            f"{numerator} ÷ {denominator} × 100, using totals. "
            "Use metrics covering equivalent populations and periods."
        )

    else:
        metric = st.selectbox(
            "Metric",
            metric_names,
            key=f"{file_key}_share_metric",
        )
        result = totals[totals["Metric"] == metric].drop(
            columns="Metric"
        ).rename(columns={"Value": "Subtotal"})

        total = result["Subtotal"].sum(min_count=1)
        result["Overall total"] = total
        result["Percent"] = (
            result["Subtotal"] / total * 100
            if pd.notna(total) and total > 0
            else float("nan")
        )

        if not percent_breakdown:
            result.insert(0, "Scope", "Overall")

        st.caption(
            "Category subtotal ÷ overall filtered total × 100. "
            "Suitable for non-negative additive counts or amounts."
        )

    st.dataframe(result.round(2), use_container_width=True)

    if percent_breakdown:
        plot_data = result.copy()
        plot_data["Category"] = (
            plot_data[percent_breakdown].astype(str)
            .agg(" | ".join, axis=1)
        )
        figure = px.bar(
            plot_data,
            x="Category",
            y="Percent",
            text_auto=".1f",
            template="plotly_white",
            color_discrete_sequence=["#247BA0"],
        )
        figure.update_layout(height=350)
        st.plotly_chart(figure, use_container_width=True)

    download(result, "percentage_table.csv", "percent_download")

    st.caption(
        "Missing or non-positive denominators produce blank percentages."
    )
