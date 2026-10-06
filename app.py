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
    "Upload Excel or CSV data. Analyse one sheet or connect "
    "two sheets using a shared identifier."
)


def prepare_sheet(frame):
    """Clean column names and remove completely empty rows."""
    frame = frame.copy()
    frame.columns = [
        str(column).strip()
        for column in frame.columns
    ]
    frame = frame.dropna(how="all").reset_index(drop=True)

    if frame.columns.duplicated().any():
        st.error(
            "Duplicate column names found. "
            "Rename the duplicate columns in your file."
        )
        st.stop()

    return frame


def normalise_uid(series):
    """
    Convert identifiers to trimmed text.
    Blank identifiers remain missing, so they cannot match.
    """
    values = series.astype("string").str.strip()
    return values.mask(values.eq(""))


uploaded_file = st.file_uploader(
    "Upload an Excel or CSV file",
    type=["xlsx", "csv"],
)

if uploaded_file is None:
    st.info("Upload a file to start.")
    st.stop()

try:
    if uploaded_file.name.lower().endswith(".csv"):
        df = prepare_sheet(
            pd.read_csv(uploaded_file, dtype=object)
        )

    else:
        workbook = pd.ExcelFile(uploaded_file)

        mode = st.radio(
            "How would you like to use this workbook?",
            (
                ["Analyse one sheet", "Connect two sheets"]
                if len(workbook.sheet_names) >= 2
                else ["Analyse one sheet"]
            ),
            horizontal=True,
        )

        if mode == "Analyse one sheet":
            sheet_name = st.selectbox(
                "Select sheet",
                workbook.sheet_names,
            )

            header_row = st.number_input(
                "Row containing column names",
                min_value=1,
                value=1,
                step=1,
                key="single_header",
            )

            df = prepare_sheet(
                pd.read_excel(
                    workbook,
                    sheet_name=sheet_name,
                    header=header_row - 1,
                    dtype=object,
                )
            )

        else:
            first, second = st.columns(2)

            with first:
                sheet_a = st.selectbox(
                    "First sheet: main records",
                    workbook.sheet_names,
                    key="sheet_a",
                )
                header_a = st.number_input(
                    "Header row in first sheet",
                    min_value=1,
                    value=1,
                    step=1,
                    key="header_a",
                )

            with second:
                sheet_b = st.selectbox(
                    "Second sheet: linked records",
                    [
                        name for name in workbook.sheet_names
                        if name != sheet_a
                    ],
                    key="sheet_b",
                )
                header_b = st.number_input(
                    "Header row in second sheet",
                    min_value=1,
                    value=1,
                    step=1,
                    key="header_b",
                )

            data_a = prepare_sheet(
                pd.read_excel(
                    workbook,
                    sheet_name=sheet_a,
                    header=header_a - 1,
                    dtype=object,
                )
            )
            data_b = prepare_sheet(
                pd.read_excel(
                    workbook,
                    sheet_name=sheet_b,
                    header=header_b - 1,
                    dtype=object,
                )
            )

            if data_a.empty or data_b.empty:
                st.warning(
                    "Both selected sheets must contain data."
                )
                st.stop()

            first, second = st.columns(2)

            with first:
                uid_a = st.selectbox(
                    "UID column in first sheet",
                    list(data_a.columns),
                    key="uid_a",
                )

            with second:
                uid_b = st.selectbox(
                    "UID column in second sheet",
                    list(data_b.columns),
                    key="uid_b",
                )

            st.caption(
                "Use a stable patient ID where possible. "
                "Names can be shared by different people. "
                "UID matching is exact after trimming spaces."
            )

            join_choice = st.selectbox(
                "Which records should be included?",
                [
                    "All records from first sheet",
                    "Only records matched in both sheets",
                ],
            )

            # Prefix columns so their source remains clear.
            left = data_a.add_prefix(f"{sheet_a} | ")
            right = data_b.add_prefix(f"{sheet_b} | ")

            # Find an internal key name that cannot overwrite
            # any source column.
            join_key = "__link_uid"
            while join_key in left.columns or join_key in right.columns:
                join_key += "_"

            left[join_key] = normalise_uid(data_a[uid_a])
            right[join_key] = normalise_uid(data_b[uid_b])

            left_keys = left[join_key].dropna()
            right_keys = right[join_key].dropna()

            duplicate_a = left_keys.duplicated().any()
            duplicate_b = right_keys.duplicated().any()

            if duplicate_a and duplicate_b:
                st.error(
                    "The UID repeats in both sheets. Joining "
                    "these sheets could multiply records and "
                    "inflate results. Use a unique record ID "
                    "or summarise one sheet to one row per UID."
                )
                st.stop()

            if duplicate_b:
                st.error(
                    "The second sheet has multiple rows per UID. "
                    "To preserve the first sheet's record count, "
                    "swap the sheets so the sheet with repeated "
                    "UIDs is first."
                )
                st.stop()

            missing_a = int(left[join_key].isna().sum())
            missing_b = int(right[join_key].isna().sum())

            if missing_a or missing_b:
                st.warning(
                    f"Missing UIDs: {missing_a:,} in the first "
                    f"sheet and {missing_b:,} in the second. "
                    "Missing UIDs are never matched."
                )

            # Remove missing right-side keys to prevent pandas
            # from matching missing identifiers with each other.
            right = right[right[join_key].notna()].copy()

            matched = left[join_key].isin(right[join_key])
            matched_count = int(matched.sum())

            st.info(
                f"{matched_count:,} of {len(left):,} first-sheet "
                "records have a matching UID in the second sheet."
            )

            how = (
                "left"
                if join_choice == "All records from first sheet"
                else "inner"
            )

            df = left.merge(
                right,
                on=join_key,
                how=how,
                validate="many_to_one",
            ).drop(columns=join_key)

            st.caption(
                "Each result row represents a first-sheet "
                "record, with matching second-sheet information "
                "attached. A second-sheet value may repeat "
                "across several first-sheet records."
            )

except Exception as error:
    st.error(f"Could not prepare the uploaded file: {error}")
    st.stop()

if df.empty:
    st.warning("No data rows are available.")
    st.stop()

st.caption(
    f"Before filtering: {len(df):,} rows | "
    f"{len(df.columns):,} columns"
)

with st.expander("Preview data before filtering"):
    st.dataframe(df.head(100), use_container_width=True)


# ===========================
# FILTERS
# ===========================

with st.sidebar:
    st.header("Filter data")

    st.subheader("Date range")

    date_column = st.selectbox(
        "Date column",
        ["None"] + list(df.columns),
        key="date_filter_column",
        help=(
            "Select a full date column for a date range. "
            "For labels such as January or Quarter II, "
            "use the value filters below."
        ),
    )

    if date_column != "None":
        date_format = st.selectbox(
            "Date format",
            [
                "Automatic: day first",
                "Automatic: month first",
                "YYYY-MM-DD",
                "DD/MM/YYYY",
                "MM/DD/YYYY",
            ],
            key="date_filter_format",
        )

        explicit_formats = {
            "YYYY-MM-DD": "%Y-%m-%d",
            "DD/MM/YYYY": "%d/%m/%Y",
            "MM/DD/YYYY": "%m/%d/%Y",
        }

        if date_format in explicit_formats:
            parsed_dates = pd.to_datetime(
                df[date_column],
                format=explicit_formats[date_format],
                errors="coerce",
            )
        else:
            parsed_dates = pd.to_datetime(
                df[date_column],
                errors="coerce",
                dayfirst=date_format == "Automatic: day first",
            )

        valid_dates = parsed_dates.dropna()

        if valid_dates.empty:
            st.warning(
                "No valid dates found. Check the selected "
                "column and date format."
            )
            st.stop()

        earliest = valid_dates.min().date()
        latest = valid_dates.max().date()

        # A changed file/column/range gets a fresh date selector.
        date_widget_key = (
            f"range_{uploaded_file.name}_{date_column}_"
            f"{date_format}_{earliest}_{latest}"
        )

        selected_range = st.date_input(
            "Include dates from / to",
            value=(earliest, latest),
            min_value=earliest,
            max_value=latest,
            key=date_widget_key,
        )

        if len(selected_range) != 2:
            st.info("Select both the start and end dates.")
            st.stop()

        start_date, end_date = selected_range

        if start_date > end_date:
            st.error("Start date must be before end date.")
            st.stop()

        missing_dates = int(parsed_dates.isna().sum())

        if missing_dates:
            st.caption(
                f"{missing_dates:,} rows with missing or "
                "invalid dates are excluded."
            )

        # Compare calendar dates so times on the end date
        # remain included.
        mask = (
            parsed_dates.notna()
            & (parsed_dates.dt.date >= start_date)
            & (parsed_dates.dt.date <= end_date)
        )
        df = df.loc[mask].copy()

    st.subheader("Value filters")

    filter_columns = st.multiselect(
        "Select columns to filter",
        list(df.columns),
        key="value_filter_columns",
        help=(
            "For example: township, gender, indicator, "
            "year, reporting month or quarter."
        ),
    )

    for position, column in enumerate(filter_columns):
        values = df[column].astype("string")
        options = sorted(values.dropna().unique().tolist())

        chosen_values = st.multiselect(
            f"Include values in {column}",
            options,
            default=options,
            key=f"value_filter_{position}_{column}",
        )

        include_missing = st.checkbox(
            f"Include missing values in {column}",
            value=True,
            key=f"missing_filter_{position}_{column}",
        )

        mask = values.isin(chosen_values)

        if include_missing:
            mask = mask | values.isna()

        df = df.loc[mask].copy()

if df.empty:
    st.warning("No records match the selected filters.")
    st.stop()

st.success(f"Records after filtering: {len(df):,}")

with st.expander("Preview filtered data"):
    st.dataframe(df.head(100), use_container_width=True)

st.download_button(
    "Download filtered data",
    data=df.to_csv(index=False).encode("utf-8"),
    file_name="filtered_data.csv",
    mime="text/csv",
)

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
