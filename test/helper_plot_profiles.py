from pathlib import Path
from typing import Optional, List
import base64
import numpy as np

import pandas as pd
import streamlit as st
import plotly
import plotly.graph_objects as go
import io
import os
import math
from PIL import Image

import matplotlib
matplotlib.use("Agg")
matplotlib.rc("font", family="Arial")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import FancyArrowPatch
from matplotlib.offsetbox import OffsetImage, AnnotationBbox
import matplotlib.image as mpimg
import numpy as np


COLORS = [
    "#e6194B",
    "#f58231",
    "#ffe119",
    "#3cb44b",
    "#4363d8",
    "#911eb4",
    "#f032e6",
]

FONT_FAMILY = "Arial"
MAX_ANNOTATIONS_PER_TRACE = 1000
MARKER_NAME_MAP = {
    "CCL2/MCP-1":               "MCP-1",
    "CD106/VCAM-1":             "VCAM-1",
    "CD141/Thrombomodulin":     "TM",
    "CD142/Tissue Factor":      "TF",
    "CD54/ICAM-1":              "ICAM-1",
    "CD62E/E-Selectin":         "Esel",
    "CD87/uPAR":                "uPAR",
    "CXCL8/IL-8":               "IL8",
    "CXCL9/MIG":                "MIG",
    "HLA-DR":                   "HLA-DR",
    "Proliferation":            "Prolif",
    "SRB":                      "SRB",
    "CCL26/Eotaxin-3":          "Eot3",
    "CD62P/P-selectin":         "Psel",
    "VEGFR2":                   "VEGFR2",
    "CD40":                     "CD40",
    "CD69":                     "CD69",
    "IL-1alpha":                "IL1a",
    "M-CSF":                    "M-CSF",
    "sPGE2":                    "sPGE2",
    "sTNF-alpha":               "sTNFa",
    "CD38":                     "CD38",
    "PBMC Cytotoxicity":        "Pcyto",
    "B cell Proliferation":     "Prolif",
    "Secreted IgG":             "sIgG",
    "sIL-17A":                  "sIL-17A",
    "sIL-17F":                  "sIL-17F",
    "sIL-2":                    "sIL-2",
    "sIL-6":                    "sIL-6",
    "IL-6":                     "IL6",
    "CD90":                     "CD90",
    "Keratin 8/18":             "Ker8/18",
    "MMP-1":                    "MMP1",
    "MMP-3":                    "MMP3",
    "MMP-9":                    "MMP9",
    "PAI-I":                    "PAI-I",
    "tPA":                      "tPA",
    "uPA":                      "uPA",
    "CXCL10/IP-10":             "IP-10",
    "CXCL11/I-TAC":             "ITAC",
    "EGFR":                     "EGFR",
    "LDLR":                     "LDLR",
    "Serum Amyloid A":          "SAA",
    "Collagen I":               "Col-I",
    "Collagen III":             "Col-III",
    "Proliferation_72hr":       "Prolif72",
    "TIMP-1":                   "TIMP1",
    "TIMP-2":                   "TIMP2",
    "alpha-SM Actin":           "aSMA",
    "bFGF":                     "bFGF",
    "Collagen IV":              "Col-IV",
    "Decorin":                  "Decorin",
    "CCL3/MIP-1alpha":          "MIP-1",
    "sIL-10":                   "sIL-10",
    "SRB-Mphg":                 "SRB-M",
}

def image_to_base64(path: Path) -> str:
    with open(path, "rb") as f:
        return "data:image/png;base64," + base64.b64encode(f.read()).decode()

#######################################################
###                 PROFILE PLOTTER                 ###
#######################################################

class BioMAPProfilePlotter:

    def __init__(self, excel_path: str | Path, image_dir: str = "images/"):
        self.excel_path = Path(excel_path)
        self.image_dir = Path(image_dir)
        self.df = self._load_profile()

    def _load_profile(self) -> pd.DataFrame:
        xl = pd.ExcelFile(self.excel_path)
        if "Profile Data" not in xl.sheet_names:
            raise ValueError("Sheet 'Profile Data' not found")

        return pd.read_excel(self.excel_path, sheet_name="Profile Data")

    @staticmethod
    def parse_descriptor(text: str):
        parts = [p.strip() for p in str(text).split(", ")]
        compound = parts[0]
        marker_code = parts[1] if len(parts) > 2 else None
        dose = parts[-1]
        return compound, marker_code, dose

    def discover_profiles(self) -> pd.DataFrame:
        rows = []
        for idx, row in self.df.iterrows():
            compound, marker_code, dose = self.parse_descriptor(row.iloc[0])
            rows.append(
                dict(
                    row_idx=idx,
                    compound=compound,
                    marker_code=marker_code,
                    dose=dose,
                )
            )
        return pd.DataFrame(rows)


    def load_envelope(self) -> list[float] | None:
        xl = pd.ExcelFile(self.excel_path)
        if "Envelope" not in xl.sheet_names:
            return None
        env = pd.read_excel(self.excel_path, sheet_name="Envelope")
        return env.iloc[0, 1:].astype(float).tolist()
    
    def resolve_label_positions(self, labels: list[dict], min_gap: float = 0.1) -> list[dict]:
        """
        Avoid overlap in marker labels on plot
        """
        if not labels:
            return labels
        labels = sorted(labels, key=lambda d: d["x"])
        for i in range(1, len(labels)):
            prev = labels[i - 1]
            curr = labels[i]
            if curr["x"] - prev["x"] < min_gap:
                curr["x"] = prev["x"] + min_gap
        
        return labels

    def create_figure(self, selected_rows: List[int], y_range: tuple[float, float]) -> go.Figure:

        biomarker_cols = self.df.columns[1:]
        biomarkers = biomarker_cols.tolist()
        x = np.arange(len(biomarkers))

        fig = go.Figure()

        labeled_markers = {} #idx, marker

        # Envelope
        envelope = self.load_envelope()
        if envelope:
            env = np.array(envelope)
            fig.add_trace(go.Scatter(
                x=x,
                y=env,
                line=dict(color="rgba(0,0,0,0)"),
                showlegend=False,
                hoverinfo="skip",
            ))
            fig.add_trace(go.Scatter(
                x=x,
                y=-env,
                fill="tonexty",
                fillcolor="rgba(180,180,180,0.35)",
                line=dict(color="rgba(0,0,0,0)"),
                name="Envelope",
                hoverinfo="skip",
            ))

        # Profiles
        proliferation_hits = []
        srb_hits = []
        for i, row_idx in enumerate(selected_rows):
            row = self.df.loc[row_idx]
            _, _, dose = self.parse_descriptor(row.iloc[0])
            values = row.iloc[1:].astype(float).values

            fig.add_trace(go.Scatter(
                x=x,
                y=values,
                mode="lines",
                name=dose,
                line=dict(
                    color=COLORS[i % len(COLORS)],
                    width=2.5 if i == len(selected_rows) - 1 else 1.5,
                    shape="spline",
                    smoothing=0.35,
                ),
                hovertemplate="<b>%{text}</b><br>%{y:.2f}<extra></extra>",
                text=biomarkers,
            ))

            # Marker annotations
            if envelope:
                deltas = np.abs(values) - env
                top_idx = np.argsort(deltas)[-MAX_ANNOTATIONS_PER_TRACE:]

                for idx in top_idx:
                    if deltas[idx] > 0:
                        biomarker = biomarkers[idx]
                        marker_only = biomarker.split(":")[-1]
                        labeled_markers[idx] = [marker_only, values[idx]]
                        if "Proliferation" in biomarker:
                            proliferation_hits.append(idx)
                        if "SRB" in biomarker:
                            srb_hits.append(idx)
        # Arrows
        arrow_tip = y_range[0] + 0.50
        srb_tip = y_range[0] + 0.35
        arrow_base = y_range[0] + 0.05

        fig.add_trace(go.Scatter(
            x=x,
            y=values,
            mode="lines",
            name=dose,
            line=dict(
                color=COLORS[i % len(COLORS)],
                width=2.5 if i == len(selected_rows) - 1 else 1.5,
                shape="spline",
                smoothing=0.35,
            ),
            hovertemplate="<b>%{text}</b><br>%{y:.2f}<extra></extra>",
            text=biomarkers,
        ))
        # Thin arrow for SRB hits
        for idx in srb_hits:
            fig.add_annotation(
                x=idx,
                y=srb_tip,
                ax = idx,
                ay = arrow_base,
                xref="x",
                yref="y",
                axref="x",
                ayref="y",
                showarrow=True,
                arrowhead=3,
                arrowsize=1.8,
                arrowwidth=0.8,
                arrowcolor="#000000",
                text="",
            )
        # Thick arrow at Proliferation hits
        for idx in proliferation_hits:
            fig.add_annotation(
                x=idx,
                y=arrow_tip,
                ax = idx,
                ay = arrow_base,
                xref="x",
                yref="y",
                axref="x",
                ayref="y",
                showarrow=True,
                arrowhead=3,
                arrowsize=3,
                arrowwidth=1.2,
                arrowcolor="#a9a9a9",
                text="",
            )

        # Biomarker labels for hits
        label_annotations = []
        for idx, label in labeled_markers.items():
            if idx >= MAX_ANNOTATIONS_PER_TRACE:
                continue
            text_label = MARKER_NAME_MAP[label[0]]
            y_val = float(label[1])
            direction = "up" if y_val >= 0 else "down"
            y_offset = 0.08 if direction == "up" else -0.08
            label_annotations.append({
                "x": idx,
                "y": y_val + y_offset,
                "text": text_label,
                "direction": direction,
            })
        
        label_annotations = self.resolve_label_positions(label_annotations)

        for la in label_annotations:
            fig.add_annotation(
                x=la["x"],
                y=la["y"],
                text=la["text"],
                showarrow=False,
                font=dict(family="Arial", size=8, color="#1f2937"),
                xanchor="center",
                yanchor="bottom" if la["direction"] == "up" else "top"
            )

        # Line at zero
        fig.add_hline(y=0, line_width=1.5, line_color="black")

        # Systems
        systems = [b.split(":")[0] for b in biomarkers]
        sys_df = (
            pd.DataFrame({"system": systems, "idx": x})
            .groupby("system")
            .agg(start=("idx", "min"), end=("idx", "max"))
        )

        for system, row in sys_df.iterrows():
            # boundary line
            fig.add_vline(
                x=row["end"] + 0.5,
                line_color="rgba(120,120,120,0.30)",
                line_width=0.8,
            )

            # image
            icon_path = self.image_dir / f"{system}.png"
            center_x = (row["start"] + row["end"]) / 2

            if icon_path.exists():
                fig.add_layout_image(
                    dict(
                        source=image_to_base64(icon_path),
                        xref="x",
                        yref="paper",
                        x=center_x,
                        y=1.0,
                        sizex=8, 
                        sizey=0.15,
                        xanchor="center",
                        yanchor="bottom",
                        layer="above",
                    )
                )

            # system label (bold, below icon)
            label = system

            #italicize "l" in lmphg
            if system.lower() == "lmphg":
                label="<i>l</i>Mphg"

            fig.add_annotation(
                x=center_x,
                y=0.995,
                xref="x",
                yref="paper",
                text=f"<b>{label}</b>",
                showarrow=False,
                font=dict(
                    family=FONT_FAMILY,
                    size=16,
                    color="black",
                ),
            )

        # Layout
        fig.update_layout(
            width=2051,
            height=2076,
            plot_bgcolor="white",
            paper_bgcolor="white",
            margin=dict(l=110, r=50, t=120, b=260),
            font=dict(family=FONT_FAMILY),
            hovermode="x unified",

            xaxis=dict(
                tickmode="array",
                tickvals=x,
                ticktext=[b.split(":")[-1] for b in biomarkers],
                tickangle=90,
                tickfont=dict(
                    family=FONT_FAMILY,
                    size=7,
                    color="#000000",
                ),
                showgrid=False,
                linewidth=1,
                linecolor="#000000",
                ticks="outside",
                ticklen=4,
            ),

            yaxis=dict(
                title=dict(
                    text="Log Ratio vs Vehicle",
                    font=dict(family=FONT_FAMILY, size=16, color="#000000"),
                standoff=12,
                ),
                showgrid=False,
                range=y_range,
                zeroline=False,
                tickfont=dict(family=FONT_FAMILY, size=13, color="#000000"),
            ticks="outside", ticklen=6, tickwidth=1, linecolor="#000000"
            ),

            legend=dict(
                title=dict(text="Profiles", font=dict(family=FONT_FAMILY, size=13, color="#000000",)),
                font=dict(family=FONT_FAMILY, size=12, color="#000000"),
                x=0.99,
                y=0.05,
                xanchor="right",
                yanchor="bottom",
                bgcolor="rgba(255,255,255,0.9)",
                bordercolor="rgba(0,0,0,0.25)",
                borderwidth=1,
            ),
            title=None,  # no title
        )

        return fig
    
    def create_matplotlib_figure(self, selected_rows: list, y_range: tuple,) -> plt.Figure:

        """
        Matplotlib mirror of create_figure()
        Renders high-def graph with thick grey up-pointing arrows for Proliferation hits,
        thin black arrows for SRB hits, spline profiles, envelope, system dividers/labels, biomarker tick labels,
        and legend. 
        """

        matplotlib.rc("font", family="Arial")
        biomarker_cols = self.df.columns[1:]
        biomarkers = biomarker_cols.tolist()
        n = len(biomarkers)
        x = np.arange(n)

        # Figure size: 2051x1076 to fit perfectly into reports
        fig_w, fig_h = 2051 / 100, 1076 / 100 # inches at 100 dpi
        fig, ax = plt.subplots(figsize=(fig_w, fig_h))
        fig.patch.set_facecolor("white")
        ax.set_facecolor("white")

        # Envelope
        envelope = self.load_envelope()
        if envelope:
            env = np.array(envelope)
            ax.fill_between(x, env, -env,
                            color="gray",
                            facecolor=(0.706,0.706,0.706,0.35),
                            linewidth=0, label="Envelope")
        
        # Profile and hits detection
        proliferation_hits = []
        srb_hits = []
        labeled_markers = {}

        for i, row_idx in enumerate(selected_rows):
            row = self.df.loc[row_idx]
            _, _, dose = self.parse_descriptor(row.iloc[0])
            values = row.iloc[1:].astype(float).values

            lw = 2.5 if i == len(selected_rows) - 1 else 1.5
            color = COLORS[i % len(COLORS)]

            ax.plot(x, values, color=color, linewidth=lw, label=dose)

            # Detect hits outside envelope
            if envelope:
                deltas = np.abs(values) - env
                top_idx = np.argsort(deltas)
                for idx in top_idx:
                    if deltas[idx] > 0:
                        biomarker = biomarkers[idx]
                        marker_only = biomarker.split(":")[-1]
                        labeled_markers[idx] = [marker_only, values[idx]]
                        if "Proliferation" in biomarker:
                            proliferation_hits.append(idx)
                        if "SRB" in biomarker:
                            srb_hits.append(idx)
            
        # Zero line
        ax.axhline(0, color="k", linewidth=1.5)

        # Proliferation arrows: thick, grey, pointed up
        arrow_base = y_range[0] + 0.05
        prolif_tip = y_range[0] + 0.50
        srb_tip = y_range[0] + 0.35
        
        for idx in proliferation_hits:
            ax.annotate("",
                        xy=(idx, prolif_tip), # arrow tip
                        xytext=(idx, arrow_base), #arrow tail
                        arrowprops=dict(
                            arrowstyle="simple",
                            fc="#a9a9a9",
                            ec="#a9a9a9",
                            mutation_scale=40, #large arrowhead
                            shrinkA = 0,
                            shrinkB = 0,
                        ),)

        # SRB arrows: thin, black
        for idx in srb_hits:
            ax.annotate("",
                        xy=(idx, srb_tip),
                        xytext=(idx, arrow_base),
                        arrowprops=dict(
                            arrowstyle="-|>",
                            color="k",
                            lw=0.8,
                            mutation_scale=10,
                        ),)
        
        # Biomarker hit labels
        label_annotations = []
        for idx, label in labeled_markers.items():
            if idx >= MAX_ANNOTATIONS_PER_TRACE:
                continue
            text_label = MARKER_NAME_MAP[label[0]]
            y_val = float(label[1])
            direction = "up" if y_val >= 0 else "down"
            y_offset = 0.08 if direction == "up" else -0.08
            label_annotations.append({
                "x": float(idx),
                "y": y_val + y_offset,
                "text": text_label,
                "direction": direction,
            })
        
        label_annotations = self.resolve_label_positions(label_annotations)

        for la in label_annotations:
            va = "bottom" if la["direction"] == "up" else "top"
            ax.text(
                la["x"], la["y"], la["text"],
                ha = "center", va=va, fontsize=9,
                color="k"
            )
        
        # System dividers, labels, images
        systems = [b.split(":")[0] for b in biomarkers]
        sys_df = pd.DataFrame({"system": systems, "idx": x}).groupby("system").agg(start=("idx", "min"), end=("idx", "max"))
        for system, srow in sys_df.iterrows():
            # Vertical divider
            ax.axvline(srow["end"] + 0.5, color="gray", alpha=0.3, linewidth=0.8)
            center_x = (srow["start"] + srow["end"]) / 2
            icon_path = self.image_dir / f"{system}.png"
            if icon_path.exists():
                img = mpimg.imread(icon_path)
                imagebox = OffsetImage(img, zoom=1.0) #SYSTEM IMAGE SIZE CONTROLLER

                ab = AnnotationBbox(
                    imagebox,
                    (center_x, 1.07),
                    xycoords=ax.get_xaxis_transform(),
                    frameon=False,
                    box_alignment=(0.5, 0),
                )

                ax.add_artist(ab)
            #label = r"$\it{l}$Mphg" if system.lower() == "lmphg" else system
            label = "/Mphg" if system.lower() == "lmphg" else system
            

            ax.text(center_x, 1.01, label, transform=ax.get_xaxis_transform(), ha="center", va="bottom", fontsize=16, fontweight="bold", color="k")

        # Axes formatting
        ax.set_xlim(-0.5, n - 0.5)
        ax.set_ylim(y_range[0], y_range[1])

        ax.set_xticks(x)
        ax.set_xticklabels(
            [b.split(":")[-1] for b in biomarkers], rotation=90, fontsize=8, color="k",
        )

        ax.tick_params(axis="x", direction="out", length=4, width=1, colors="k")

        ax.yaxis.set_label_text("Log Ratio vs Vehicle", fontdict=dict(family="Arial", size=16, color="k", fontweight="bold"),)
        ax.tick_params(axis="y", direction="out", length=6, width=1, colors="k")
        for spine in ("top", "right"):
            ax.spines[spine].set_visible(False)
        for spine in ("left", "bottom"):
            ax.spines[spine].set_linewidth(1)

        ax.grid(False)

        legend = ax.legend(title="Profiles", loc="lower right", fontsize=12, title_fontsize=12, framealpha=0.9, edgecolor="white", fancybox=False)
        legend.get_frame().set_linewidth(1)

        fig.tight_layout(rect=[0,0,1,0.97])

        return fig

    
#######################################################
###                 TAB RENDERING                   ###
#######################################################

def render(df: pd.DataFrame, excel_path: Optional[str] = None):

    st.set_page_config(layout="wide")
    st.title("Profile Viewer")
    st.markdown("Select an existing file or upload your own, pick an agent, and view profiles.")

    source = st.radio(
        "Profile data source",
        ["Existing export", "Upload Excel file"],
        horizontal=True,
    )

    if source == "Existing export":
        exports = sorted(Path("exports").glob("*.xlsx"))
        if not exports:
            st.warning("No Excel files found in exports/")
            return
        excel_path = st.selectbox(
            "Select export file",
            exports,
            format_func=lambda p: p.name,
        )
    else:
        uploaded = st.file_uploader("Upload BioMAP Excel file", type=["xlsx"])
        if not uploaded:
            return
        excel_path = Path("tmp_uploaded.xlsx")
        excel_path.write_bytes(uploaded.read())

    st.markdown("**Y-axis Range**")
    y_min = st.number_input("Y min", value=-3.0, step=0.1, format="%.2f")
    y_max = st.number_input("Y max", value=2.0, step=0.1, format="%.2f")

    plotter = BioMAPProfilePlotter(excel_path)
    meta = plotter.discover_profiles()

    compound = st.selectbox(
        "Select compound",
        sorted(meta["compound"].unique()),
    )

    comp_df = meta[meta["compound"] == compound]

    selected_doses = st.multiselect(
        "Select doses",
        comp_df["dose"].tolist(),
        default=comp_df["dose"].tolist()[:2],
    )

    selected_rows = comp_df[
        comp_df["dose"].isin(selected_doses)
    ]["row_idx"].tolist()

    if not selected_rows:
        st.warning("No doses selected")
        return

    fig = plotter.create_figure(selected_rows,  y_range=(y_min, y_max))

    st.subheader("Interactive Plot")
    
    st.plotly_chart(fig, width="stretch",
                    config={
                        "displaylogo": False,
                        "modeBarButtonsToRemove": [
                            "zoom",
                            "pan",
                            "select",
                            "lasso2d",
                            "zoomIn",
                            "zoomOut",
                            "autoScale",
                            "resetScale"
                        ],
                        "toImageButtonOptions": {
                            "format": "png",
                            "filename": f"{compound}_profile",
                            "height": 1076,
                            "width": 2051,
                            "scale": 3
                            },
                        },)

    # Download profile plot
    st.markdown("### Download")
    st.markdown("To download graph as PNG, please click the Camera icon in the top-right of the plot.")

    html_bytes = fig.to_html(
        include_plotlyjs="cdn",
        full_html=True,
    ).encode("utf-8")

    st.download_button(
        label="Download Interactive HTML",
        data=html_bytes,
        file_name=f"{compound}_profile.html",
        mime="text/html",
    )

    st.subheader("Static Plot with thicker arrows")

    mpl_fig = plotter.create_matplotlib_figure(selected_rows, y_range=(y_min, y_max))
    st.pyplot(mpl_fig, clear_figure=False, dpi=300)

    png_buf = io.BytesIO()
    mpl_fig.savefig(png_buf, format="png", dpi=400, bbox_inches="tight", facecolor="white")
    plt.close(mpl_fig)
    png_buf.seek(0)

    st.download_button(label="Download PNG with Proliferation arrows", data=png_buf, file_name=f"{compound}_profile.png", mime="image/png")