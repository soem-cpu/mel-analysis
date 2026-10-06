import hashlib
from io import BytesIO

import pandas as pd
import plotly.express as px
import streamlit as st


st.set_page_config(
    page_title="M&E Data Analysis",
    page_icon="📊",
    layout="wide",
)


# ===========================
# HELPER FUNCTIONS
# ===========================

def prepare_sheet(frame):
    frame = frame.copy()
    frame.columns = [str(column).strip() for column in frame.columns]

    if frame.columns.duplicated().any():
        raise ValueError("Column names must be unique.")

    if len(frame.columns) == 0:
        raise ValueError("No columns found. Check the header row.")

    return frame.dropna(how="all").reset_index(drop=True)


def normalise_uid(series):
    values = series.astype("string").str.strip()
    return values.mask(values.eq(""))


def numeric_values(series):
    return pd.to_numeric(
        series.astype("string")
        .str.strip()
        .str.replace(",", "", regex=False),
        errors="coerce",
    )


def parse_dates(series, date_format):
    formats = {
        "YYYY-MM-DD": "%Y-%m-%d",
        "DD/MM/YYYY": "%d/%m/%Y",
        "MM/DD/YYYY": "%m/%d/%Y",
    }

    if date_format in formats:
        return pd.to_datetime(
            series,
            format=formats[date_format],
            errors="coerce",
        )

    return pd.to_datetime(
        series,
        format="mixed",
        errors="coerce",
        dayfirst=date_format == "Automatic: day first",
    )


def download_table(table, filename, label, key):
    st.download_button(
        label,
        data=table.to_csv(index=False).encode("utf-8-sig"),
        file_name=filename,
        mime="text/csv",
        key=key,
    )


def keep_first_uid(frame, uid_column, sheet_name, header_row):
    """Report all repeated UID rows and retain the first."""
    uid = normalise_uid(frame[uid_column])
    repeated = uid.notna() & uid.duplicated(keep=False)
    exclude = uid.notna() & uid.duplicated(keep="first")

    report = pd.DataFrame()

    if repeated.any():
        # Original Excel row numbers are retained in prepare_sheet.
        details = pd.DataFrame(
            {
                "Source sheet": sheet_name,
                "Excel row": frame.index + header_row + 1,
                "Matching UID": uid,
                "Action": exclude.map({
                    False: "Keep first occurrence",
                    True: "Exclude from analysis",
                }),
            },
            index=frame.index,
        )

        report = pd.concat(
            [
                details.loc[repeated],
                frame.loc[repeated].add_prefix("Source | "),
            ],
            axis=1,
        )

    return frame.loc[~exclude].copy(), report, int(exclude.sum())


def read_excel_sheet(content, sheet_name, header_row):
    # Keep original data-row positions for duplicate review.
    frame = pd.read_excel(
        BytesIO(content),
        sheet_name=sheet_name,
        header=header_row - 1,
        dtype=object,
    )
    frame.columns = [str(column).strip() for column in frame.columns]

    if len(frame.columns) == 0 or frame.columns.duplicated().any():
        raise ValueError("Check the header row and unique column names.")

    return frame.dropna(how="all")


def aggregate_table(table, dimensions, measures, method):
    if dimensions:
        grouped = table.groupby(dimensions, dropna=False, sort=False)[measures]
        result = (
            grouped.sum(min_count=1)
            if method == "sum"
            else grouped.mean()
        )
        return result.reset_index()

    return pd.DataFrame({
        column: [table[column].agg(method)]
        for column in measures
    })


def sort_table(table, name_column, value_columns, key):
    first, second = st.columns(2)

    with first:
        column = st.selectbox(
            "Sort by",
            [name_column] + value_columns,
            key=f"{key}_column",
        )

    with second:
        direction = st.selectbox(
            "Sort direction",
            ["Ascending", "Descending"],
            key=f"{key}_direction",
        )

    if column == name_column:
        # Case-insensitive alphabetical order.
        return table.sort_values(
            column,
            ascending=direction == "Ascending",
            key=lambda values: values.astype("string").str.casefold(),
            kind="stable",
            na_position="last",
        ).reset_index(drop=True)

    return table.sort_values(
        column,
        ascending=direction == "Ascending",
        kind="stable",
        na_position="last",
    ).reset_index(drop=True)


DATE_FORMATS = [
    "Automatic: day first",
    "Automatic: month first",
    "YYYY-MM-DD",
    "DD/MM/YYYY",
    "MM/DD/YYYY",
]


# ===========================
# UPLOAD AND SHEET SELECTION
# ===========================

st.title("M&E Data Analysis")
st.write(
    "Analyse trends, compare groups and calculate target gaps. "
    "Connect two Excel sheets using a shared UID."
)

uploaded = st.file_uploader(
    "Upload Excel or CSV",
    type=["xlsx", "csv"],
)

if uploaded is None:
    st.info("Upload a file to begin.")
    st.stop()

content = uploaded.getvalue()
file_id = hashlib.sha256(content).hexdigest()[:12]

# Reset settings when a different file is uploaded.
if st.session_state.get("_current_file") != file_id:
    for key in list(st.session_state):
        if key.startswith("setting_"):
            del st.session_state[key]
    st.session_state["_current_file"] = file_id

try:
    if uploaded.name.lower().endswith(".csv"):
        df = prepare_sheet(
            pd.read_csv(BytesIO(content), dtype=object)
        )
    else:
        workbook = pd.ExcelFile(BytesIO(content))
        sheet_names = workbook.sheet_names

        modes = ["Analyse one sheet"]
        if len(sheet_names) >= 2:
            modes.append("Connect two sheets")

        mode = st.radio(
            "Workbook analysis",
            modes,
            horizontal=True,
            key="setting_mode",
        )

        if mode == "Analyse one sheet":
            sheet_name = st.selectbox(
                "Sheet",
                sheet_names,
                key="setting_sheet",
            )
            header_row = st.number_input(
                "Header row",
                min_value=1,
                value=1,
                step=1,
                key="setting_header",
            )
            df = read_excel_sheet(content, sheet_name, header_row)

        else:
            first, second = st.columns(2)

            with first:
                sheet_a = st.selectbox(
                    "First sheet",
                    sheet_names,
                    key="setting_sheet_a",
                )
                header_a = st.number_input(
                    "First sheet header row",
                    min_value=1,
                    value=1,
                    step=1,
                    key="setting_header_a",
                )

            with second:
                sheet_b = st.selectbox(
                    "Second sheet",
                    [name for name in sheet_names if name != sheet_a],
                    key="setting_sheet_b",
                )
                header_b = st.number_input(
                    "Second sheet header row",
                    min_value=1,
                    value=1,
                    step=1,
                    key="setting_header_b",
                )

            data_a = read_excel_sheet(content, sheet_a, header_a)
            data_b = read_excel_sheet(content, sheet_b, header_b)

            if data_a.empty or data_b.empty:
                st.warning("Both selected sheets must contain records.")
                st.stop()

            first, second = st.columns(2)

            with first:
                uid_a = st.selectbox(
                    "UID in first sheet",
                    list(data_a.columns),
                    key="setting_uid_a",
                )

            with second:
                uid_b = st.selectbox(
                    "UID in second sheet",
                    list(data_b.columns),
                    key="setting_uid_b",
                )

            st.caption(
                "UIDs match exactly after trimming spaces. "
                "Use patient ID where possible; names may not be unique."
            )

            join_choice = st.selectbox(
                "Include records",
                [
                    "All records from first sheet",
                    "Only records matched in both sheets",
                ],
                key="setting_join",
            )

            data_a, report_a, removed_a = keep_first_uid(
                data_a, uid_a, sheet_a, header_a
            )
            data_b, report_b, removed_b = keep_first_uid(
                data_b, uid_b, sheet_b, header_b
            )

            reports = [
                report for report in [report_a, report_b]
                if not report.empty
            ]

            if reports:
                duplicate_report = pd.concat(
                    reports, ignore_index=True, sort=False
                )

                st.warning(
                    "Repeated UIDs found. Only the first record "
                    "per UID in each sheet is used for analysis."
                )

                with st.expander("Duplicated UID records", expanded=True):
                    st.dataframe(
                        duplicate_report,
                        use_container_width=True,
                    )
                    download_table(
                        duplicate_report,
                        "duplicate_uid_report.csv",
                        "Download duplicate report",
                        "duplicate_download",
                    )

            st.caption(
                f"Duplicate rows excluded: {removed_a:,} from "
                f"{sheet_a}; {removed_b:,} from {sheet_b}. "
                "Deduplication happens before period filtering."
            )

            left = data_a.add_prefix(f"{sheet_a} | ")
            right = data_b.add_prefix(f"{sheet_b} | ")

            link_key = "__matching_uid"
            while link_key in left.columns or link_key in right.columns:
                link_key += "_"

            left[link_key] = normalise_uid(data_a[uid_a])
            right[link_key] = normalise_uid(data_b[uid_b])

            missing_a = int(left[link_key].isna().sum())
            missing_b = int(right[link_key].isna().sum())

            if missing_a or missing_b:
                st.caption(
                    f"Missing UIDs: {missing_a:,} in first sheet; "
                    f"{missing_b:,} in second. Missing UIDs never match."
                )

            # Prevent missing keys from matching each other.
            right = right[right[link_key].notna()].copy()

            match_count = int(left[link_key].isin(right[link_key]).sum())
            st.info(
                f"{match_count:,} of {len(left):,} retained first-sheet "
                "records match the second sheet."
            )

            df = left.merge(
                right,
                on=link_key,
                how=(
                    "left"
                    if join_choice == "All records from first sheet"
                    else "inner"
                ),
                validate="many_to_one",
            ).drop(columns=link_key)

except Exception as error:
    st.error(f"Could not prepare the file: {error}")
    st.stop()

df = df.reset_index(drop=True)

if df.empty:
    st.warning("No records available.")
    st.stop()

st.caption(f"Before filtering: {len(df):,} rows")

with st.expander("Preview source or joined data"):
    st.dataframe(df.head(100), use_container_width=True)


# ===========================
# DATE AND VALUE FILTERS
# ===========================

with st.sidebar:
    st.header("Filters")

    date_column = st.selectbox(
        "Date column for period filter",
        ["None"] + list(df.columns),
        key="setting_filter_date",
    )

    if date_column != "None":
        date_format = st.selectbox(
            "Date format",
            DATE_FORMATS,
            key="setting_filter_date_format",
        )

        dates = parse_dates(df[date_column], date_format)
        valid = dates.dropna()

        if valid.empty:
            st.warning("No valid dates. Check the column and format.")
            st.stop()

        earliest = valid.min().date()
        latest = valid.max().date()

        selected_range = st.date_input(
            "Start and end dates",
            value=(earliest, latest),
            min_value=earliest,
            max_value=latest,
            key=(
                f"setting_range_{file_id}_{date_column}_"
                f"{date_format}_{earliest}_{latest}"
            ),
        )

        if len(selected_range) != 2:
            st.info("Select both start and end dates.")
            st.stop()

        start, end = selected_range

        if start > end:
            st.error("Start date must be before end date.")
            st.stop()

        invalid = int(dates.isna().sum())
        if invalid:
            st.caption(
                f"{invalid:,} missing or invalid dates excluded."
            )

        mask = (
            dates.notna()
            & (dates.dt.date >= start)
            & (dates.dt.date <= end)
        )
        df = df.loc[mask].copy()

    filter_columns = st.multiselect(
        "Columns to filter",
        list(df.columns),
        key="setting_filter_columns",
        help="For example: township, gender, year, quarter or indicator.",
    )

    for column in filter_columns:
        values = df[column].astype("string")
        options = sorted(values.dropna().unique().tolist())

        selected = st.multiselect(
            f"Include: {column}",
            options,
            default=options,
            key=f"setting_values_{column}",
        )
        include_missing = st.checkbox(
            f"Include missing: {column}",
            value=True,
            key=f"setting_missing_{column}",
        )

        mask = values.isin(selected)
        if include_missing:
            mask = mask | values.isna()

        df = df.loc[mask].copy()

if df.empty:
    st.warning("No records match the filters.")
    st.stop()

st.success(f"Records after filtering: {len(df):,}")

with st.expander("Filtered data"):
    st.dataframe(df.head(100), use_container_width=True)

download_table(
    df,
    "filtered_data.csv",
    "Download filtered data",
    "filtered_download",
)


# ===========================
# ANALYSIS SETTINGS
# ===========================

st.subheader("Choose analysis settings")

columns = list(df.columns)
first, second = st.columns(2)

with first:
    actual_column = st.selectbox(
        "Actual/result column",
        columns,
        key="setting_actual",
    )
    aggregation = st.selectbox(
        "Combine results using",
        ["Sum", "Mean"],
        key="setting_aggregation",
    )
    period_column = st.selectbox(
        "Trend date or period column",
        ["None"] + columns,
        key="setting_period",
    )

with second:
    group_column = st.selectbox(
        "Group column",
        ["None"] + columns,
        key="setting_group",
    )
    target_column = st.selectbox(
        "Target column",
        ["None"] + [
            column for column in columns
            if column != actual_column
        ],
        key="setting_target",
    )

st.caption(
    "Analyse one indicator and unit at a time. "
    "Sum is suitable for additive counts or amounts. "
    "Rates may require weighted calculations. "
    "Actual and target values must use the same units and record level."
)

period_mode = "Keep labels"
trend_format = DATE_FORMATS[0]
frequency = "Monthly"

if period_column != "None":
    period_mode = st.radio(
        "Trend period format",
        ["Keep labels", "Dates"],
        horizontal=True,
        key="setting_period_mode",
    )

    if period_mode == "Dates":
        trend_format = st.selectbox(
            "Trend date format",
            DATE_FORMATS,
            key="setting_trend_format",
        )
        frequency = st.selectbox(
            "Trend frequency",
            ["Monthly", "Quarterly", "Yearly"],
            key="setting_frequency",
        )

data = pd.DataFrame(index=df.index)
data["Actual"] = numeric_values(df[actual_column])

invalid_actual = int(data["Actual"].isna().sum())
if invalid_actual:
    st.warning(
        f"{invalid_actual:,} rows with missing or non-numeric "
        "actual values excluded from analysis."
    )

data = data[data["Actual"].notna()].copy()

if data.empty:
    st.warning("No numeric actual values found.")
    st.stop()

if group_column != "None":
    group_values = df.loc[data.index, group_column].astype("string")
    data["Group"] = (
        group_values.str.strip()
        .replace("", pd.NA)
        .fillna("(Missing)")
    )

if target_column != "None":
    data["Target"] = numeric_values(df.loc[data.index, target_column])

if period_column != "None":
    source_period = df.loc[data.index, period_column]

    if period_mode == "Dates":
        dates = parse_dates(source_period, trend_format)
        code = {
            "Monthly": "M",
            "Quarterly": "Q",
            "Yearly": "Y",
        }[frequency]
        data["Period"] = dates.dt.to_period(code).dt.to_timestamp()
    else:
        data["Period"] = (
            source_period.astype("string")
            .str.strip()
            .replace("", pd.NA)
        )

method = aggregation.lower()

st.subheader("Overview")
first, second = st.columns(2)
first.metric("Rows analysed", f"{len(data):,}")
second.metric(
    f"{aggregation} of {actual_column}",
    f"{data['Actual'].agg(method):,.2f}",
)

trend_tab, group_tab, gap_tab = st.tabs(
    ["Trends", "Group comparisons", "Target gaps"]
)


# ===========================
# TREND ANALYSIS
# ===========================

with trend_tab:
    if period_column == "None":
        st.info("Select a trend period column.")
    else:
        trend_data = data.dropna(subset=["Period"])
        invalid_periods = len(data) - len(trend_data)

        if invalid_periods:
            st.caption(
                f"{invalid_periods:,} missing or invalid periods "
                "excluded from trends."
            )

        if trend_data.empty:
            st.warning("No valid trend periods.")
        else:
            dimensions = ["Period"]
            if group_column != "None":
                dimensions.append("Group")

            trend = aggregate_table(
                trend_data, dimensions, ["Actual"], method
            )

            if period_mode == "Dates":
                period_order = sorted(trend["Period"].unique())
                trend = trend.sort_values(dimensions)
            else:
                period_order = (
                    trend_data["Period"].drop_duplicates().tolist()
                )
                order = {
                    value: index
                    for index, value in enumerate(period_order)
                }
                trend["_order"] = trend["Period"].map(order)
                trend = trend.sort_values(
                    (["Group"] if group_column != "None" else [])
                    + ["_order"]
                ).drop(columns="_order")
                st.caption(
                    "Period labels follow their first appearance "
                    "in the filtered data."
                )

            chart = px.line(
                trend,
                x="Period",
                y="Actual",
                color="Group" if group_column != "None" else None,
                markers=True,
                category_orders={"Period": period_order},
                title=f"{actual_column}: trend",
            )
            st.plotly_chart(chart, use_container_width=True)
            st.dataframe(trend, use_container_width=True)

            st.markdown("**Calculated findings**")

            groups = (
                trend.groupby("Group", sort=False)
                if group_column != "None"
                else [("Overall", trend)]
            )

            for label, series in groups:
                if len(series) < 2:
                    continue

                initial = float(series.iloc[0]["Actual"])
                final = float(series.iloc[-1]["Actual"])
                difference = final - initial

                finding = (
                    f"{label}: first to last displayed period, "
                    f"{initial:,.2f} to {final:,.2f}. "
                    f"Change: {difference:+,.2f}."
                )
                if initial > 0:
                    finding += (
                        f" Relative change: "
                        f"{difference / initial * 100:+,.1f} percent."
                    )
                st.write(finding)

            download_table(
                trend,
                "trend_analysis.csv",
                "Download trend table",
                "trend_download",
            )


# ===========================
# GROUP COMPARISONS
# ===========================

with group_tab:
    if group_column == "None":
        st.info("Select a group column.")
    else:
        comparison = aggregate_table(
            data, ["Group"], ["Actual"], method
        )
        comparison = sort_table(
            comparison,
            "Group",
            ["Actual"],
            "setting_group_sort",
        )

        chart = px.bar(
            comparison,
            x="Group",
            y="Actual",
            category_orders={
                "Group": comparison["Group"].tolist()
            },
            title=f"{actual_column} by {group_column}",
        )
        st.plotly_chart(chart, use_container_width=True)
        st.dataframe(comparison, use_container_width=True)

        highest = comparison.loc[comparison["Actual"].idxmax()]
        lowest = comparison.loc[comparison["Actual"].idxmin()]

        st.write(
            f"Highest: {highest['Group']} "
            f"({highest['Actual']:,.2f}). "
            f"Lowest: {lowest['Group']} "
            f"({lowest['Actual']:,.2f}). "
            f"Difference: "
            f"{highest['Actual'] - lowest['Actual']:,.2f}."
        )

        st.caption(
            "These comparisons describe recorded results; "
            "they do not adjust for group population size."
        )

        download_table(
            comparison,
            "group_comparison.csv",
            "Download comparison",
            "group_download",
        )


# ===========================
# TARGET GAP ANALYSIS
# ===========================

with gap_tab:
    if target_column == "None":
        st.info("Select a target column.")
    else:
        st.caption(
            "Positive gap means below target; negative gap means "
            "above target. This assumes higher results are desirable."
        )

        paired = data.dropna(subset=["Target"]).copy()

        missing_targets = len(data) - len(paired)
        if missing_targets:
            st.caption(
                f"{missing_targets:,} rows without numeric targets "
                "excluded from gap analysis."
            )

        if paired.empty:
            st.warning("No records have both actual and target values.")
        else:
            available = []
            if group_column != "None":
                available.append("Group")
            if period_column != "None":
                available.append("Period")

            dimensions = st.multiselect(
                "Calculate gaps by",
                available,
                default=available,
                key="setting_gap_dimensions",
            )

            if dimensions:
                paired = paired.dropna(subset=dimensions)

            if paired.empty:
                st.warning("No valid records for these dimensions.")
            else:
                gaps = aggregate_table(
                    paired, dimensions, ["Actual", "Target"], method
                )

                gaps["Gap"] = gaps["Target"] - gaps["Actual"]
                gaps["Achievement (percent)"] = (
                    gaps["Actual"]
                    / gaps["Target"].where(gaps["Target"] > 0)
                    * 100
                )

                if dimensions:
                    gaps["Comparison"] = (
                        gaps[dimensions].astype(str)
                        .agg(" | ".join, axis=1)
                    )
                else:
                    gaps["Comparison"] = "Overall"

                gaps = sort_table(
                    gaps,
                    "Comparison",
                    [
                        "Actual",
                        "Target",
                        "Gap",
                        "Achievement (percent)",
                    ],
                    "setting_gap_sort",
                )

                chart_data = gaps.melt(
                    id_vars=["Comparison"],
                    value_vars=["Actual", "Target"],
                    var_name="Measure",
                    value_name="Value",
                )

                chart = px.bar(
                    chart_data,
                    x="Comparison",
                    y="Value",
                    color="Measure",
                    barmode="group",
                    category_orders={
                        "Comparison": gaps["Comparison"].tolist()
                    },
                    title="Actual versus target",
                )
                st.plotly_chart(chart, use_container_width=True)
                st.dataframe(gaps, use_container_width=True)

                shortfalls = gaps[gaps["Gap"] > 0]

                if shortfalls.empty:
                    st.success("No shortfalls in these comparisons.")
                else:
                    largest = shortfalls.loc[
                        shortfalls["Gap"].idxmax()
                    ]
                    st.write(
                        f"Largest shortfall: "
                        f"{largest['Comparison']}, "
                        f"gap {largest['Gap']:,.2f}."
                    )

                download_table(
                    gaps,
                    "target_gap_analysis.csv",
                    "Download gap table",
                    "gap_download",
                )
