import pandas as pd
import plotly.express as px
import streamlit as st

st.set_page_config(
    page_title="M&E Data Analysis",
    page_icon="📊",
    layout="wide",
)

st.title("M&E Data Analysis")
st.write(
    "Upload your dataset to compare trends, analyse groups "
    "and calculate gaps against targets."
)

uploaded_file = st.file_uploader(
    "Upload an Excel or CSV file",
    type=["xlsx", "csv"],
)

if uploaded_file is None:
    st.info("Upload a file to start.")
    st.stop()

try:
    if uploaded_file.name.lower().endswith(".csv"):
        df = pd.read_csv(uploaded_file)
    else:
        workbook = pd.ExcelFile(uploaded_file)
        sheet = st.selectbox("Select a sheet", workbook.sheet_names)
        header_row = st.number_input(
            "Row containing column names",
            min_value=1,
            value=1,
            step=1,
        )
        df = pd.read_excel(workbook, sheet_name=sheet, header=header_row - 1)

except Exception as error:
    st.error(f"Could not read the file: {error}")
    st.stop()

df.columns = [str(column).strip() for column in df.columns]
df = df.dropna(how="all")

if df.empty:
    st.warning("The selected dataset contains no data rows.")
    st.stop()

if df.columns.duplicated().any():
    st.error("Column names must be unique. Rename duplicate columns.")
    st.stop()

st.caption(f"{len(df):,} rows | {len(df.columns):,} columns")

with st.expander("Preview data"):
    st.dataframe(df.head(100), use_container_width=True)

# Optional filter, for example to select one indicator.
with st.sidebar:
    st.header("Filter data")
    filter_column = st.selectbox(
        "Filter by a column",
        ["None"] + list(df.columns),
    )

    if filter_column != "None":
        options = sorted(
            df[filter_column].dropna().astype(str).unique().tolist()
        )
        selected = st.multiselect(
            "Include values",
            options,
            default=options,
        )
        df = df[df[filter_column].astype(str).isin(selected)].copy()

if df.empty:
    st.warning("No rows match the selected filter.")
    st.stop()

st.subheader("Choose analysis settings")

columns = list(df.columns)

left, right = st.columns(2)

with left:
    actual_column = st.selectbox("Actual/result column", columns)
    aggregation = st.selectbox(
        "How should results be combined?",
        ["Sum", "Mean"],
        help=(
            "Use Sum for additive counts or amounts. "
            "Use Mean for comparable scores. "
            "Rates may require a weighted calculation."
        ),
    )
    period_column = st.selectbox(
        "Date or period column",
        ["None"] + columns,
    )

with right:
    group_column = st.selectbox(
        "Group column, such as township or gender",
        ["None"] + columns,
    )
    target_column = st.selectbox(
        "Target column",
        ["None"] + [
            column for column in columns
            if column != actual_column
        ],
    )

period_mode = "Keep labels"
frequency = "Monthly"

if period_column != "None":
    period_mode = st.radio(
        "Period format",
        ["Keep labels", "Dates"],
        horizontal=True,
        help=(
            "Keep labels for periods such as January or 2025 Q1. "
            "Dates groups full dates into months, quarters or years."
        ),
    )

    if period_mode == "Dates":
        frequency = st.selectbox(
            "Trend frequency",
            ["Monthly", "Quarterly", "Yearly"],
        )
        day_first = st.checkbox(
            "Dates use day/month/year",
            value=True,
        )

st.caption(
    "Select one indicator and unit before combining results. "
    "Targets must be recorded at the same level as actual results; "
    "a repeated annual target should not be summed across monthly rows."
)


def numeric_values(series):
    """Convert numbers and comma-separated numeric text."""
    return pd.to_numeric(
        series.astype("string")
        .str.strip()
        .str.replace(",", "", regex=False),
        errors="coerce",
    )


# Use a separate table to avoid overwriting source columns.
data = pd.DataFrame(index=df.index)
data["Actual"] = numeric_values(df[actual_column])

invalid_actual = int(data["Actual"].isna().sum())

if invalid_actual:
    st.warning(
        f"{invalid_actual:,} rows have missing or non-numeric "
        "actual values and are excluded."
    )

data = data[data["Actual"].notna()].copy()

if data.empty:
    st.error("No numeric actual values were found.")
    st.stop()

if group_column != "None":
    data["Group"] = (
        df.loc[data.index, group_column]
        .astype("string")
        .fillna("(Missing)")
        .replace("", "(Missing)")
    )

if target_column != "None":
    data["Target"] = numeric_values(
        df.loc[data.index, target_column]
    )

if period_column != "None":
    source_period = df.loc[data.index, period_column]

    if period_mode == "Dates":
        dates = pd.to_datetime(
            source_period,
            errors="coerce",
            dayfirst=day_first,
        )
        codes = {
            "Monthly": "M",
            "Quarterly": "Q",
            "Yearly": "Y",
        }
        data["Period"] = (
            dates.dt.to_period(codes[frequency])
            .dt.to_timestamp()
        )
    else:
        data["Period"] = source_period.astype("string")
        data.loc[
            source_period.isna()
            | source_period.astype("string").str.strip().eq(""),
            "Period",
        ] = pd.NA

method = "sum" if aggregation == "Sum" else "mean"


def summarise(table, keys, measures):
    if method == "sum":
        return (
            table.groupby(keys, sort=True)[measures]
            .sum(min_count=1)
            .reset_index()
        )
    return (
        table.groupby(keys, sort=True)[measures]
        .mean()
        .reset_index()
    )


def download_table(table, filename, label):
    st.download_button(
        label,
        data=table.to_csv(index=False).encode("utf-8"),
        file_name=filename,
        mime="text/csv",
    )


st.subheader("Overview")

metric_left, metric_right = st.columns(2)
metric_left.metric("Rows analysed", f"{len(data):,}")
overall = data["Actual"].agg(method)
metric_right.metric(
    f"{aggregation} of {actual_column}",
    f"{overall:,.2f}",
)

trend_tab, group_tab, gap_tab = st.tabs(
    ["Trends", "Group comparisons", "Target gaps"]
)

with trend_tab:
    if period_column == "None":
        st.info("Select a date or period column to view trends.")
    else:
        trend_data = data.dropna(subset=["Period"])
        excluded = len(data) - len(trend_data)

        if excluded:
            st.caption(
                f"{excluded:,} rows excluded from trends "
                "because their period is missing or invalid."
            )

        if trend_data.empty:
            st.warning("No valid periods were found.")
        else:
            keys = ["Period"]
            if group_column != "None":
                keys.append("Group")

            trend = summarise(trend_data, keys, ["Actual"])

            if period_mode == "Keep labels":
                # Preserve source order for labels such as month names.
                order = trend_data["Period"].drop_duplicates().tolist()
                ranks = {value: index for index, value in enumerate(order)}
                trend["_order"] = trend["Period"].map(ranks)
                trend = trend.sort_values(keys[1:] + ["_order"])
                trend = trend.drop(columns="_order")
                st.caption(
                    "Period labels follow their first appearance "
                    "in the uploaded data."
                )

            chart = px.line(
                trend,
                x="Period",
                y="Actual",
                color="Group" if group_column != "None" else None,
                markers=True,
                title=f"{actual_column}: trend",
            )
            st.plotly_chart(chart, use_container_width=True)
            st.dataframe(trend, use_container_width=True)

            # Describe changes separately for each group.
            series_groups = (
                trend.groupby("Group")
                if group_column != "None"
                else [("Overall", trend)]
            )

            st.markdown("**Calculated findings**")
            for label, series in series_groups:
                series = series.sort_values("Period") if (
                    period_mode == "Dates"
                ) else series

                if len(series) < 2:
                    continue

                first = float(series.iloc[0]["Actual"])
                last = float(series.iloc[-1]["Actual"])
                change = last - first

                statement = (
                    f"{label}: from the first to the last displayed "
                    f"period, results changed from {first:,.2f} "
                    f"to {last:,.2f}, a change of {change:+,.2f}."
                )
                if first > 0:
                    statement += (
                        f" Relative change: "
                        f"{change / first * 100:+,.1f} percent."
                    )
                st.write(statement)

            download_table(
                trend,
                "trend_analysis.csv",
                "Download trend table",
            )

with group_tab:
    if group_column == "None":
        st.info("Select a group column to compare groups.")
    else:
        comparison = summarise(data, ["Group"], ["Actual"])
        comparison = comparison.sort_values("Actual", ascending=False)

        chart = px.bar(
            comparison,
            x="Group",
            y="Actual",
            title=f"{actual_column} by {group_column}",
        )
        st.plotly_chart(chart, use_container_width=True)
        st.dataframe(comparison, use_container_width=True)

        highest = comparison.iloc[0]
        lowest = comparison.iloc[-1]

        st.write(
            f"Highest result: {highest['Group']} "
            f"({highest['Actual']:,.2f}). "
            f"Lowest result: {lowest['Group']} "
            f"({lowest['Actual']:,.2f}). "
            f"Difference: "
            f"{highest['Actual'] - lowest['Actual']:,.2f}."
        )

        st.caption(
            "Differences describe recorded results. They do not "
            "explain causes or adjust for population size."
        )

        download_table(
            comparison,
            "group_comparison.csv",
            "Download group comparison",
        )

with gap_tab:
    if target_column == "None":
        st.info("Select a target column to calculate target gaps.")
    else:
        st.caption(
            "Positive gap = below target. "
            "Negative gap = above target. "
            "This assumes higher results are desirable."
        )

        paired = data.dropna(subset=["Target"]).copy()

        if len(paired) < len(data):
            st.warning(
                f"{len(data) - len(paired):,} rows excluded from "
                "gap analysis because targets are missing "
                "or non-numeric."
            )

        if paired.empty:
            st.warning("No rows have both actual and target values.")
        else:
            possible_dimensions = []
            if group_column != "None":
                possible_dimensions.append("Group")
            if period_column != "None":
                possible_dimensions.append("Period")

            dimensions = st.multiselect(
                "Calculate gaps by",
                possible_dimensions,
                default=possible_dimensions,
            )

            if dimensions:
                paired = paired.dropna(subset=dimensions)
                gaps = summarise(
                    paired,
                    dimensions,
                    ["Actual", "Target"],
                )
            else:
                gaps = pd.DataFrame({
                    "Scope": ["Overall"],
                    "Actual": [paired["Actual"].agg(method)],
                    "Target": [paired["Target"].agg(method)],
                })

            if gaps.empty:
                st.warning("No valid rows for these gap dimensions.")
            else:
                gaps["Gap"] = gaps["Target"] - gaps["Actual"]
                gaps["Achievement (percent)"] = (
                    gaps["Actual"]
                    / gaps["Target"].where(gaps["Target"] > 0)
                    * 100
                )

                label_columns = dimensions or ["Scope"]
                gaps["Comparison"] = (
                    gaps[label_columns].astype(str)
                    .agg(" | ".join, axis=1)
                )

                plot_data = gaps.melt(
                    id_vars=["Comparison"],
                    value_vars=["Actual", "Target"],
                    var_name="Measure",
                    value_name="Value",
                )

                chart = px.bar(
                    plot_data,
                    x="Comparison",
                    y="Value",
                    color="Measure",
                    barmode="group",
                    title="Actual versus target",
                )
                st.plotly_chart(chart, use_container_width=True)

                gaps = gaps.sort_values("Gap", ascending=False)
                st.dataframe(gaps, use_container_width=True)

                shortfalls = gaps[gaps["Gap"] > 0]

                if shortfalls.empty:
                    st.success(
                        "No shortfalls in the displayed comparisons."
                    )
                else:
                    largest = shortfalls.iloc[0]
                    st.write(
                        f"Largest shortfall: "
                        f"{largest['Comparison']}, "
                        f"with a gap of {largest['Gap']:,.2f}."
                    )

                download_table(
                    gaps,
                    "target_gap_analysis.csv",
                    "Download gap analysis",
                )
