"""
Streamlit GIS Format Converter — 80/20 Universal
Polished UI + Map Preview + Theme Toggle + EPSG Search + Reports ZIP + Size Guardrails + PostGIS (beta)
"""

from __future__ import annotations
import io, zipfile, tempfile
from pathlib import Path
from typing import Optional, Tuple, List, Dict

import streamlit as st
import geopandas as gpd
import pandas as pd
from shapely.geometry import Point

# Optional geometry repair (Shapely 2.x)
try:
    from shapely import make_valid
except Exception:
    make_valid = None

# Optional map preview deps
try:
    import folium
    from streamlit_folium import st_folium
except Exception:
    folium = None
    st_folium = None

# ===================== App Config & CSS =====================
st.set_page_config(page_title="GIS Format Converter — 80/20", page_icon="🗺️", layout="wide")

st.markdown(
    """
    <style>
      .block-container {max-width: 1200px; padding-top: 2.5rem;   /* ⬅️ was 0.6rem, now more */ padding-bottom: 1.5rem;}
      .st-card {background: #111418; border: 1px solid #2a2f36; border-radius: 14px; padding: 1rem 1.1rem;}
      .chip {display:inline-block; padding:4px 10px; border-radius:999px; border:1px solid #2a2f36; margin:0 6px 6px 0; font-size:0.85rem;
             background: linear-gradient(180deg,#1b1f27 0%, #141820 100%); box-shadow: 0 1px 0 rgba(255,255,255,0.04) inset;}
      .subtle {color:#9aa3af; font-size:0.9rem}
      .stButton>button, .stDownloadButton>button, .stToggle>div {border-radius: 10px; width:100%; font-weight:600}
      .stTabs [data-baseweb="tab"] {font-weight:600}
      .section-line { height:1px; background:#2a2f36; margin: 12px 0 18px 0; border-radius:1px; }
    </style>
    """,
    unsafe_allow_html=True,
)

# ===================== Formats =====================
VEC_INPUTS = {
    ".zip": "ESRI Shapefile (zipped)",
    ".geojson": "GeoJSON",
    ".json": "GeoJSON",
    ".kml": "KML",
    ".gpkg": "GeoPackage",
    ".gml": "GML (basic)",
    ".gpx": "GPX",
    ".dxf": "DXF (CAD basic)",
}
TAB_INPUTS = {".csv": "CSV", ".xlsx": "Excel"}
ALL_INPUTS = {**VEC_INPUTS, **TAB_INPUTS}
OUTPUTS = {
    "geojson": "GeoJSON (.geojson)",
    "shapefile": "ESRI Shapefile (.zip)",
    "kml": "KML (.kml)",
    "gpkg": "GeoPackage (.gpkg)",
    "gpx": "GPX (.gpx)",
}

# ===================== Header (Logo + Theme Toggle) =====================
if "_theme" not in st.session_state:
    st.session_state["_theme"] = "dark"

col_logo, col_title = st.columns([1, 6], vertical_alignment="center")
with col_logo:
    try:
        st.image("C:/Users/abhin/gis-format-converter/logo.png", width=56)
    except Exception:
        st.write("🗺️")
with col_title:
    st.markdown('<div class="page-title"><h1>GIS Format Converter — 80/20 Universal</h1></div>', unsafe_allow_html=True)
    st.markdown('<div class="page-sub">Drag & drop → preview → fix/simplify → pick CRS → download</div>', unsafe_allow_html=True)
    st.markdown(
        '<div>'
        '<span class="chip">Batch</span> '
        '<span class="chip">CSV→Points Wizard</span> '
        '<span class="chip">CRS Picker</span> '
        '<span class="chip">Geometry Fix</span> '
        '<span class="chip">Simplify</span> '
        '<span class="chip">Reports</span>'
        '</div>',
        unsafe_allow_html=True
    )
    st.toggle("Light theme", key="_light_toggle", value=(st.session_state["_theme"] == "light"))
    st.session_state["_theme"] = "light" if st.session_state["_light_toggle"] else "dark"
# ===== About Section =====
with st.container():
    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.markdown("### ℹ️ About this app")
    st.markdown(
        """
        This **GIS Format Converter — 80/20 Universal** helps you:

        - Convert between **Shapefile, GeoJSON, KML, GPKG, GPX**  
        - Turn **CSV/Excel tables → Points** (lat/lon)  
        - Reproject to any **EPSG code** (default WGS84:4326)  
        - Repair/simplify geometries for web maps  
        - Batch multiple files into a ZIP with reports  
        - (Beta) Read/write from **PostGIS**  

        ⚡ Quick format swaps without needing full GIS software.
        """
    )
    st.markdown('</div>', unsafe_allow_html=True)



# Apply light theme CSS (subtle)
if st.session_state["_theme"] == "light":
    st.markdown(
        """
        <style>
          body, .stApp { background: #fafafa; color:#111; }
          .st-card { background:#fff; border-color:#e5e7eb; }
          .chip { border-color:#e5e7eb; }
        </style>
        """,
        unsafe_allow_html=True,
    )


# ===================== Sidebar =====================
st.sidebar.header("⚙️ Options")

# CRS group with quick search
with st.sidebar.expander("CRS", expanded=True):
    target_epsg = st.text_input("Target EPSG", value="4326", help="4326=WGS84 lat/lon, 3857=Web Mercator")

    def find_epsg_guess(q: str) -> str | None:
        try:
            from pyproj import CRS
        except Exception:
            return None
        q = (q or "").strip()
        if not q:
            return None
        if q.isdigit():
            try:
                CRS.from_epsg(int(q)); return q
            except Exception:
                pass
        aliases = {
            "wgs84": "4326", "wgs 84": "4326",
            "web mercator": "3857", "pseudo mercator": "3857", "mercator": "3857",
            "utm 43n": "32643", "utm 44n": "32644",
        }
        if q.lower() in aliases:
            return aliases[q.lower()]
        try:
            crs = CRS.from_user_input(q)
            epsg = crs.to_epsg()
            return str(epsg) if epsg else None
        except Exception:
            return None

    epsg_query = st.text_input("Find EPSG (e.g., 'WGS84', 'Web Mercator', 'UTM 43N')")
    if epsg_query:
        guess = find_epsg_guess(epsg_query)
        if guess:
            st.success(f"Matched EPSG:{guess} → applying as target")
            target_epsg = guess
        else:
            st.warning("No EPSG match found. Try a different phrase or code.")

# Geometry quality group
with st.sidebar.expander("Geometry quality"):
    do_make_valid = st.checkbox("Fix invalid (make_valid)", value=True)
    use_buffer_fix = st.checkbox("Fallback buffer(0)")
    do_simplify = st.checkbox("Simplify geometry")
    simplify_tol = st.number_input("Tolerance", min_value=0.0, value=0.0, step=0.5, help="Units = layer CRS") if do_simplify else 0.0

# Output formatting
with st.sidebar.expander("Output formatting"):
    auto_rename_fields = st.checkbox("Auto-rename long fields (Shapefile)", value=True)
    preview_rows = st.number_input("Preview rows", min_value=1, max_value=200, value=10)

# PostGIS (beta)
with st.sidebar.expander("PostGIS (beta)"):
    st.caption("Read a table for conversion or write the last single-file layer to PostGIS.")
    pg_url = st.text_input("SQLAlchemy URL", placeholder="postgresql+psycopg2://user:pass@host:5432/dbname")
    pg_table = st.text_input("Table name")
    pg_geom = st.text_input("Geometry column", value="geom")
    colA, colB = st.columns(2)

    def _get_engine(url: str):
        from sqlalchemy import create_engine
        return create_engine(url, pool_pre_ping=True)

    def _read_postgis_table(url: str, table: str, geom_col: str = "geom") -> gpd.GeoDataFrame:
        eng = _get_engine(url)
        sql = f'SELECT * FROM "{table}"'
        return gpd.read_postgis(sql, eng, geom_col=geom_col)

    def _write_postgis(gdf: gpd.GeoDataFrame, url: str, table: str, if_exists: str = "replace"):
        eng = _get_engine(url)
        gdf.to_postgis(table, eng, if_exists=if_exists)

    with colA:
        if st.button("⬇️ Read table"):
            if not (pg_url and pg_table):
                st.warning("URL and table required.")
            else:
                try:
                    gdf_pg = _read_postgis_table(pg_url, pg_table, pg_geom)
                    st.session_state["_pg_gdf"] = gdf_pg
                    st.success(f"Loaded {len(gdf_pg)} features from PostGIS.")
                except Exception as e:
                    st.error(f"PostGIS read failed: {e}")
    with colB:
        if st.button("⬆️ Write last converted"):
            candidate = st.session_state.get("gdf_last_single")
            if candidate is None:
                st.warning("No layer in memory to write. Convert a file first.")
            elif not (pg_url and pg_table):
                st.warning("URL and table required.")
            else:
                try:
                    _write_postgis(candidate, pg_url, pg_table, if_exists="replace")
                    st.success(f"Wrote {len(candidate)} features to {pg_table}.")
                except Exception as e:
                    st.error(f"PostGIS write failed: {e}")

st.divider()

# ===================== Helpers =====================

def _safe_mkdir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)


def _save_upload_to(temp_dir: Path, file) -> Path:
    out_path = temp_dir / file.name
    with open(out_path, "wb") as f:
        f.write(file.getbuffer())
    return out_path


def _unzip_if_shapefile(p: Path, work: Path) -> Optional[Path]:
    if p.suffix.lower() != ".zip":
        return None
    with zipfile.ZipFile(p, 'r') as zf:
        zf.extractall(work)
    return work


def _read_vector_any(path: Path) -> gpd.GeoDataFrame:
    if path.suffix.lower() == ".zip":
        shp_dir = _unzip_if_shapefile(path, path.parent / "unzipped")
        if not shp_dir:
            raise ValueError("Failed to unpack shapefile .zip")
        shp_files = list(shp_dir.rglob("*.shp"))
        if not shp_files:
            raise ValueError("No .shp found inside the uploaded .zip")
        return gpd.read_file(str(shp_files[0]))
    return gpd.read_file(str(path))


def _read_csv_points(path: Path, lat_col: str, lon_col: str, src_epsg: str) -> gpd.GeoDataFrame:
    if path.suffix.lower() == ".csv":
        df = pd.read_csv(path)
    else:
        try:
            df = pd.read_excel(path)  # needs openpyxl
        except ImportError:
            raise RuntimeError("Reading .xlsx needs 'openpyxl'. Install it or export CSV.")
    if lat_col not in df.columns or lon_col not in df.columns:
        raise ValueError("Selected Lat/Lon columns not found.")
    df = df.dropna(subset=[lat_col, lon_col]).copy()
    df[lat_col] = pd.to_numeric(df[lat_col], errors="coerce")
    df[lon_col] = pd.to_numeric(df[lon_col], errors="coerce")
    df = df.dropna(subset=[lat_col, lon_col])
    g = gpd.GeoDataFrame(
        df,
        geometry=[Point(xy) for xy in zip(df[lon_col], df[lat_col])],
        crs=f"EPSG:{src_epsg}"
    )
    return g


def _apply_repairs_and_ops(gdf: gpd.GeoDataFrame) -> Tuple[gpd.GeoDataFrame, List[str]]:
    notes: List[str] = []
    if do_make_valid and make_valid is not None:
        try:
            gdf["geometry"] = gdf.geometry.apply(make_valid)
            notes.append("Applied make_valid.")
        except Exception as e:
            notes.append(f"make_valid failed: {e}")
    if use_buffer_fix:
        try:
            gdf["geometry"] = gdf.buffer(0)
            notes.append("Applied buffer(0) fix.")
        except Exception as e:
            notes.append(f"buffer(0) failed: {e}")
    if do_simplify and simplify_tol > 0:
        try:
            gdf["geometry"] = gdf.geometry.simplify(simplify_tol, preserve_topology=True)
            notes.append(f"Simplified (tol={simplify_tol}).")
        except Exception as e:
            notes.append(f"Simplify failed: {e}")
    return gdf, notes


def _reproject(gdf: gpd.GeoDataFrame, epsg: str) -> Tuple[gpd.GeoDataFrame, Optional[str]]:
    try:
        tgt = int(epsg)
    except Exception:
        return gdf, "Invalid target EPSG; kept original CRS."
    try:
        if gdf.crs is None:
            return gdf, "Source CRS unknown; cannot reproject."
        if gdf.crs.to_epsg() == tgt:
            return gdf, None
        gdf = gdf.to_crs(tgt)
        return gdf, f"Reprojected to EPSG:{tgt}."
    except Exception as e:
        return gdf, f"Reprojection failed: {e}"


def _truncate_fields_for_shp(columns: List[str]) -> Tuple[Dict[str, str], List[str]]:
    mapping: Dict[str, str] = {}
    warnings: List[str] = []
    for c in columns:
        if len(c) > 10:
            newc = c[:10]
            mapping[c] = newc
            warnings.append(f"Field '{c}' → '{newc}' (Shapefile 10-char limit)")
    return mapping, warnings


def _gdf_to_bytes(gdf: gpd.GeoDataFrame, out_fmt: str, base: str) -> Tuple[bytes, str, List[str]]:
    out_fmt = out_fmt.lower()
    msgs: List[str] = []

    if out_fmt == "geojson":
        return gdf.to_json().encode("utf-8"), f"{base}.geojson", msgs

    out_dir = Path(tempfile.mkdtemp(prefix="gisconv_out_"))

    if out_fmt == "gpkg":
        path = out_dir / f"{base}.gpkg"
        gdf.to_file(path, driver="GPKG")
        return path.read_bytes(), path.name, msgs

    if out_fmt == "kml":
        path = out_dir / f"{base}.kml"
        try:
            if gdf.crs is None or gdf.crs.to_epsg() != 4326:
                gdf = gdf.set_crs(4326, allow_override=True)
        except Exception:
            pass
        try:
            gdf.to_file(path, driver="KML")
        except Exception as e:
            msgs.append(f"KML write failed ({e}); use GeoJSON/GPKG instead.")
            raise
        return path.read_bytes(), path.name, msgs

    if out_fmt == "gpx":
        path = out_dir / f"{base}.gpx"
        try:
            gdf.to_file(path, driver="GPX")
        except Exception as e:
            msgs.append(f"GPX write failed ({e}); use GeoJSON/GPKG instead.")
            raise
        return path.read_bytes(), path.name, msgs

    if out_fmt == "shapefile":
        mapping, warns = _truncate_fields_for_shp(list(gdf.columns))
        if auto_rename_fields and mapping:
            gdf = gdf.rename(columns=mapping)
            msgs.extend(warns)
        shp_folder = out_dir / f"{base}_shp"
        _safe_mkdir(shp_folder)
        shp_path = shp_folder / f"{base}.shp"
        gdf.to_file(shp_path, driver="ESRI Shapefile")
        zip_bytes = io.BytesIO()
        with zipfile.ZipFile(zip_bytes, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
            for p in shp_folder.iterdir():
                zf.write(p, arcname=p.name)
        return zip_bytes.getvalue(), f"{base}.zip", msgs

    raise ValueError(f"Unsupported output format: {out_fmt}")

# ===================== Tabs =====================
convert_tab, reports_tab, help_tab = st.tabs(["🔄 Convert", "📑 Reports", "❓ Help"])

# ===================== Convert Tab =====================
with convert_tab:
    st.markdown("### Upload files")
    uploaded_files = st.file_uploader(
        "Upload GIS files (.zip Shapefile, .geojson/.json, .kml, .gpkg, .gpx, .gml, .dxf, .csv, .xlsx)",
        type=[ext.strip('.') for ext in ALL_INPUTS.keys()],
        accept_multiple_files=True,
    )

    # Size guardrails
    if uploaded_files:
        big_files = [(f.name, getattr(f, "size", 0)) for f in uploaded_files if getattr(f, "size", 0) >= 50*1024*1024]
        if big_files:
            st.warning(
                "Large files detected (≥50 MB): " + ", ".join(f"{n} ({round(s/1024/1024)} MB)" for n, s in big_files)
                + ". Tip: prefer GPKG output, and enable Simplify for lighter GeoJSON/KML."
            )

    # CSV/XLSX wizard (only when a single tabular file is uploaded)
    lat_col = lon_col = None
    src_epsg_for_csv = "4326"
    if uploaded_files and len(uploaded_files) == 1 and Path(uploaded_files[0].name).suffix.lower() in TAB_INPUTS:
        st.info("Tabular file detected. Use the wizard below to create points.")
        with st.expander("CSV/XLSX ➜ Points (Wizard)", expanded=True):
            tmp_dir = Path(tempfile.mkdtemp(prefix="csvwiz_"))
            p = _save_upload_to(tmp_dir, uploaded_files[0])
            try:
                if p.suffix.lower() == ".csv":
                    df_preview = pd.read_csv(p, nrows=200)
                else:
                    df_preview = pd.read_excel(p, nrows=200)
            except Exception as e:
                st.error(f"Could not read file: {e}")
                df_preview = pd.DataFrame()
            if not df_preview.empty:
                st.dataframe(df_preview.head(10))
                guess_lat = next((c for c in df_preview.columns if str(c).lower() in ("lat","latitude","y")), None)
                guess_lon = next((c for c in df_preview.columns if str(c).lower() in ("lon","longitude","lng","x")), None)
                lat_col = st.selectbox("Latitude column", options=list(df_preview.columns), index=(list(df_preview.columns).index(guess_lat) if guess_lat in df_preview.columns else 0))
                lon_col = st.selectbox("Longitude column", options=list(df_preview.columns), index=(list(df_preview.columns).index(guess_lon) if guess_lon in df_preview.columns else 0))
                src_epsg_for_csv = st.text_input("Source CRS EPSG", value="4326")
            else:
                st.warning("No preview available; please ensure the file is valid.")

    st.markdown("---")
    st.markdown("### Settings & Convert")
    out_fmt = st.selectbox("Output format", options=list(OUTPUTS.keys()), format_func=lambda k: OUTPUTS[k])
    do_batch = st.button("🔄 Convert (all uploaded files)", type="primary", use_container_width=True)

    if "_last_reports" not in st.session_state:
        st.session_state["_last_reports"] = []

    if do_batch:
        if not uploaded_files:
            st.warning("Please upload at least one file.")
        else:
            overall_zip = io.BytesIO()
            reports: List[Tuple[str, str]] = []
            with st.spinner("Converting… this may take a moment for large files"):
                with zipfile.ZipFile(overall_zip, mode="w", compression=zipfile.ZIP_DEFLATED) as z:
                    for uf in uploaded_files:
                        temp_dir = Path(tempfile.mkdtemp(prefix="gisconv_batch_"))
                        src_path = _save_upload_to(temp_dir, uf)
                        name_stem = Path(uf.name).stem
                        report_lines: List[str] = []
                        try:
                            ext = src_path.suffix.lower()
                            if ext in TAB_INPUTS:
                                report_lines.append("Skipped: CSV/XLSX needs column mapping in single-file wizard mode.")
                                rep_text = ("\n".join(report_lines) or "No details.").encode("utf-8")
                                rep_name = f"{name_stem}_report.txt"
                                z.writestr(rep_name, rep_text)
                                reports.append((rep_name, rep_text.decode("utf-8", errors="ignore")))
                                continue
                            gdf = _read_vector_any(src_path)
                            report_lines.append(f"Loaded vector with {len(gdf)} features. CRS={gdf.crs}.")
                            gdf, notes = _apply_repairs_and_ops(gdf)
                            report_lines.extend(notes)
                            gdf, reproj_note = _reproject(gdf, target_epsg)
                            if reproj_note:
                                report_lines.append(reproj_note)
                            out_bytes, out_name, msgs = _gdf_to_bytes(gdf, out_fmt, name_stem)
                            report_lines.extend(msgs)
                            z.writestr(out_name, out_bytes)
                            report_lines.append(f"Exported: {out_name}")
                        except Exception as e:
                            report_lines.append(f"Read/Process failed: {e}")
                        # Write per-file report
                        rep_text = ("\n".join(report_lines) or "No details.").encode("utf-8")
                        rep_name = f"{name_stem}_report.txt"
                        z.writestr(rep_name, rep_text)
                        reports.append((rep_name, rep_text.decode("utf-8", errors="ignore")))
            st.session_state["_last_reports"] = reports
            st.success("Batch conversion complete.")
            st.download_button(
                label=f"📦 Download results ZIP ({OUTPUTS[out_fmt]})",
                data=overall_zip.getvalue(),
                file_name="converted_outputs.zip",
                mime="application/zip",
                use_container_width=True,
            )

    # Single-file preview & convert
    if uploaded_files and len(uploaded_files) == 1:
        uf = uploaded_files[0]
        tdir = Path(tempfile.mkdtemp(prefix="gisconv_single_"))
        p = _save_upload_to(tdir, uf)
        try:
            if p.suffix.lower() in TAB_INPUTS:
                if not (lat_col and lon_col):
                    st.info("Select Lat/Lon columns in the wizard above, then press Convert.")
                    gdf = None
                else:
                    gdf = _read_csv_points(p, lat_col, lon_col, src_epsg_for_csv or "4326")
                    st.success(f"CSV/XLSX ➜ points using lat={lat_col}, lon={lon_col}, srcEPSG={src_epsg_for_csv}.")
            else:
                gdf = _read_vector_any(p)
        except Exception as e:
            st.error(f"Could not read file: {e}")
            gdf = None

        if gdf is not None:
            st.session_state["gdf_last_single"] = gdf
            left, right = st.columns([2.2, 1])
            with left:
                st.markdown("#### Preview")
                st.dataframe(gdf.head(preview_rows))

                # Map preview (if deps installed)
                if folium is not None and st_folium is not None:
                    try:
                        disp = gdf.copy()
                        try:
                            if disp.crs is not None and disp.crs.to_epsg() != 4326:
                                disp = disp.to_crs(4326)
                        except Exception:
                            pass
                        if len(disp):
                            minx, miny, maxx, maxy = disp.total_bounds
                            center = [(miny + maxy) / 2.0, (minx + maxx) / 2.0]
                        else:
                            center = [20.0, 0.0]
                        st.markdown("#### Map Preview")
                        m = folium.Map(location=center, zoom_start=3)
                        folium.GeoJson(disp.to_json(), name="layer").add_to(m)
                        st_folium(m, width=700, height=460)
                    except Exception as e:
                        st.info(f"Map preview not available: {e}")
                else:
                    st.caption("(Install folium & streamlit-folium for an interactive map preview)")

            with right:
                st.markdown("#### Layer info")
                bbox = gdf.total_bounds if len(gdf) else None
                st.json({
                    "features": int(len(gdf)),
                    "geometry_type": str(gdf.geom_type.mode().iat[0]) if len(gdf) else None,
                    "crs": str(gdf.crs) if gdf.crs else None,
                    "bbox": bbox.tolist() if bbox is not None else None,
                })

            st.markdown("---")
            if st.button("⬇️ Convert this file only", type="secondary", use_container_width=True):
                with st.spinner("Converting…"):
                    gdf2, notes = _apply_repairs_and_ops(gdf)
                    gdf2, reproj_note = _reproject(gdf2, target_epsg)
                    if reproj_note:
                        notes.append(reproj_note)
                    base_default = Path(uf.name).stem
                    try:
                        out_bytes, out_name, msgs = _gdf_to_bytes(gdf2, out_fmt, base_default)
                        notes.extend(msgs)
                        st.download_button(
                            label=f"Download {OUTPUTS[out_fmt]}",
                            data=out_bytes,
                            file_name=out_name,
                            mime=(
                                "application/geo+json" if out_fmt == "geojson"
                                else "application/zip" if out_fmt == "shapefile"
                                else "application/vnd.google-earth.kml+xml" if out_fmt == "kml"
                                else "application/gpkg" if out_fmt == "gpkg"
                                else "application/gpx+xml"
                            ),
                            use_container_width=True,
                        )
                        if notes:
                            st.code("\n".join(notes)[:4000])
                        st.success("Conversion ready.")
                    except Exception as e:
                        st.error(f"Conversion failed: {e}")

# ===================== Reports Tab =====================
with reports_tab:
    st.markdown("### Recent reports")
    if st.session_state.get("_last_reports"):
        for name, content in st.session_state["_last_reports"][-5:]:
            with st.expander(name, expanded=False):
                st.code(content[:8000])
        # Download all reports as ZIP
        if st.session_state.get("_last_reports"):
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
                for name, content in st.session_state["_last_reports"]:
                    z.writestr(name, content)
            st.download_button(
                "⬇️ Download reports-only ZIP",
                data=buf.getvalue(),
                file_name="conversion_reports.zip",
                mime="application/zip",
                use_container_width=True,
            )
    else:
        st.info("Run a conversion to see per-file logs and warnings here.")

# ===================== Help Tab =====================
with help_tab:
    st.markdown("### About & Help")
    st.markdown(
        """
**What this tool does**  
- Convert between Shapefile/GeoJSON/KML/GPKG/GPX (+ CSV/XLSX → Points)  
- Reproject to any EPSG (default 4326)  
- Fix invalid geometries and simplify for web sharing  
- Batch multiple files into one ZIP and emit per-file reports

**Tips**  
- Shapefile limits: 10-char field names, 255 fields, ~2 GB → app can auto-rename.  
- KML/GPX depend on GDAL build. If writing fails, choose GeoJSON/GPKG.  
- For large layers, use GPKG or enable Simplify to keep files light.

**Privacy**  
Files are handled in temporary folders and not persisted.
        """
    )
    st.caption("Built with GDAL/Fiona/GeoPandas/Shapely • Streamlit single-file app ✨")
