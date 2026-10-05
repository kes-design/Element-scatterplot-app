import streamlit as st
import pandas as pd
import plotly.express as px

st.set_page_config(page_title="ICPMS Scatterplot", layout="wide")

st.title("ICPMS Scatterplot")
st.caption(
    "Upload an Excel file where each sheet is a group (e.g. a brand) and rows contain "
    "ICPMS concentration data."
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Fixed colors for the known glass classes; anything else falls back to the pool below.
FIXED_CLASS_COLORS = {
    "PED glass": "green",
    "Container glass": "red",
    "Floatglass": "blue",
}
FALLBACK_COLOR_POOL = ["purple", "orange", "brown", "magenta", "gray", "teal", "gold"]

KNOWN_ELEMENT_COLS = [
    "Li7", "Na23", "Mg24", "Al27", "K39", "Ca42", "Ti49", "Mn55", "Fe57",
    "Rb85", "Sr88", "Zr90", "Sb121", "Ba137", "La139", "Ce140", "Nd146",
    "Hf180", "Pb208",
]


@st.cache_data(show_spinner=False)
def load_workbook(file) -> dict[str, pd.DataFrame]:
    """Read every sheet of the uploaded Excel file into a dict of DataFrames."""
    xls = pd.ExcelFile(file)
    return {sheet: pd.read_excel(xls, sheet_name=sheet) for sheet in xls.sheet_names}


def combine_sheets(sheets: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Stack all sheets into one DataFrame, tagging each row with its source sheet."""
    frames = []
    for name, df in sheets.items():
        df = df.copy()
        # Drop fully-empty / unnamed spacer columns (all-NaN)
        df = df.dropna(axis=1, how="all")
        df.insert(0, "Sheet", name)
        frames.append(df)
    combined = pd.concat(frames, ignore_index=True, sort=False)
    # Clean up leftover "Unnamed: N" columns that still have some data but no header
    rename_map = {}
    for col in combined.columns:
        if isinstance(col, str) and col.startswith("Unnamed"):
            rename_map[col] = f"Column_{col.split(': ')[-1]}"
    combined = combined.rename(columns=rename_map)
    return combined


def detect_element_columns(df: pd.DataFrame) -> list[str]:
    """Prefer the known element symbols if present, otherwise fall back to numeric columns."""
    present_known = [c for c in KNOWN_ELEMENT_COLS if c in df.columns]
    if present_known:
        return present_known
    numeric_cols = df.select_dtypes(include="number").columns.tolist()
    return numeric_cols


def detect_category_columns(df: pd.DataFrame, element_cols: list[str]) -> list[str]:
    candidates = [c for c in df.columns if c not in element_cols]
    # Keep only columns with a reasonably small number of unique values (good for coloring)
    return [c for c in candidates if df[c].nunique(dropna=True) <= 50]


def build_color_map(df: pd.DataFrame, color_col: str | None) -> dict[str, str]:
    """Map each category to a color: fixed colors for known glass classes,
    fallback pool colors for everything else."""
    if color_col is None or color_col not in df.columns:
        return {}
    categories = df[color_col].dropna().astype(str).unique()
    color_map, pool_idx = {}, 0
    for cat in categories:
        if cat in FIXED_CLASS_COLORS:
            color_map[cat] = FIXED_CLASS_COLORS[cat]
        else:
            color_map[cat] = FALLBACK_COLOR_POOL[pool_idx % len(FALLBACK_COLOR_POOL)]
            pool_idx += 1
    return color_map


# ---------------------------------------------------------------------------
# File upload
# ---------------------------------------------------------------------------

uploaded_file = st.file_uploader("Upload your Excel file (.xlsx)", type=["xlsx"])

if not uploaded_file:
    st.info("Upload an Excel file to get started.")
    st.stop()

sheets = load_workbook(uploaded_file)
df = combine_sheets(sheets)

element_cols = detect_element_columns(df)
category_cols = detect_category_columns(df, element_cols)

st.success(
    f"Loaded {len(sheets)} sheet(s): {', '.join(sheets.keys())} — "
    f"{len(df)} rows total, {len(element_cols)} element columns detected."
)

with st.expander("Preview combined data"):
    st.dataframe(df, use_container_width=True)

if len(element_cols) < 2:
    st.warning("Couldn't detect at least two numeric element columns in this file.")
    st.stop()

# ---------------------------------------------------------------------------
# Build a "Sample Number" column: x-axis = which sample, y-axis = concentration
# ---------------------------------------------------------------------------

df_indexed = df.reset_index(drop=True).copy()
df_indexed["Sample Number"] = df_indexed.index + 1

id_display_col = next((c for c in ["Unnamed: 0", "Column_0", "Sample ID"] if c in df_indexed.columns), None)

tab_single, tab_grid = st.tabs(["Single element", "All elements"])

# --- Single element scatterplot: sample number vs concentration -------------
with tab_single:
    col1, col2 = st.columns(2)
    with col1:
        elem = st.selectbox("Element", element_cols, index=0)
    with col2:
        color_options = ["(none)"] + category_cols
        color_choice = st.selectbox(
            "Color by",
            color_options,
            index=color_options.index("Sheet") if "Sheet" in color_options else 0,
        )

    log_y = st.checkbox("Log scale Y (concentration)", value=False)

    color_arg = None if color_choice == "(none)" else color_choice
    hover_cols = [c for c in [id_display_col, "Sheet", "Merk", "Product", "Model"] if c and c in df_indexed.columns]

    fig = px.scatter(
        df_indexed,
        x="Sample Number",
        y=elem,
        color=color_arg,
        hover_data=hover_cols,
        log_y=log_y,
        title=f"{elem} concentration across samples",
        height=600,
        color_discrete_map=build_color_map(df_indexed, color_arg),
    )
    fig.update_traces(marker=dict(size=9, opacity=0.8, line=dict(width=0.5, color="white")))
    st.plotly_chart(fig, use_container_width=True)

# --- Grid: one scatterplot per element, all with sample number on X --------
with tab_grid:
    st.write("Each panel shows one element: sample number on the X-axis, concentration on the Y-axis.")

    grid_color_options = ["(none)"] + category_cols
    grid_color_choice = st.selectbox(
        "Color by",
        grid_color_options,
        index=grid_color_options.index("Sheet") if "Sheet" in grid_color_options else 0,
        key="grid_color",
    )
    grid_log = st.checkbox("Log scale Y (concentration)", value=True, key="grid_log")

    id_vars = [c for c in df_indexed.columns if c not in element_cols]
    long_df = df_indexed.melt(
        id_vars=id_vars,
        value_vars=element_cols,
        var_name="Element",
        value_name="Concentration",
    )
    # Keep facets in the original element order rather than alphabetical
    long_df["Element"] = pd.Categorical(long_df["Element"], categories=element_cols, ordered=True)

    grid_color_arg = None if grid_color_choice == "(none)" else grid_color_choice

    fig_grid = px.scatter(
        long_df,
        x="Sample Number",
        y="Concentration",
        color=grid_color_arg,
        facet_col="Element",
        facet_col_wrap=4,
        log_y=grid_log,
        height=220 * ((len(element_cols) // 4) + 1),
        title="Concentration vs. sample number for each element",
        color_discrete_map=build_color_map(long_df, grid_color_arg),
    )
    fig_grid.update_traces(marker=dict(size=5, opacity=0.7))
    fig_grid.for_each_annotation(lambda a: a.update(text=a.text.split("=")[-1]))
    fig_grid.update_yaxes(matches=None)
    st.plotly_chart(fig_grid, use_container_width=True)

st.divider()
st.caption("Tip: use the log scale toggles when values span several orders of magnitude.")