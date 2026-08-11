from __future__ import annotations

from io import BytesIO
import hashlib
import math
import time

import pandas as pd
import pydeck as pdk
import streamlit as st

from core import fetch_osrm_geometry, geocode_address, plan_routes


st.set_page_config(page_title="Servis Rota Optimizasyonu", page_icon="🚌", layout="wide")

st.markdown(
    """
    <style>
    .block-container {padding-top: 2rem; padding-bottom: 3rem;}
    div[data-testid="stMetric"] {background:#F5F7FA; border:1px solid #E2E8F0; padding:14px; border-radius:12px;}
    .route-card {background:#FFFFFF; border:1px solid #E2E8F0; border-left:6px solid #285A84;
                 padding:16px 18px; border-radius:12px; margin:10px 0;}
    .muted {color:#64748B; font-size:0.92rem;}
    </style>
    """,
    unsafe_allow_html=True,
)

st.title("🚌 Servis Rota Optimizasyonu")
st.caption("Excel'i yükleyin; sistem kapasiteyi dikkate alarak rota sayısını, durak sırasını ve dolulukları oluştursun.")


ALIASES = {
    "id": ["calisan_id", "çalışan_id", "personel_sicil", "sicil", "id"],
    "name": ["ad_soyad", "ad soyad", "çalışanın_adı_soyad", "calisan_adi", "çalışan adı"],
    "type": ["tip", "lokasyon_tipi", "nokta_tipi"],
    "address": ["adres", "acik_adres", "açık_adres", "ikamet_adresi"],
    "lat": ["enlem", "latitude", "lat"],
    "lon": ["boylam", "longitude", "lon", "lng"],
    "active": ["aktif_mi", "aktif mi", "aktif"],
    "uses_service": ["servis_kullaniyor_mu", "servis kullanıyor mu", "servis_kullanimi", "servis"],
}


def normalize(value: object) -> str:
    table = str.maketrans("çğıöşüÇĞİÖŞÜ", "cgiosuCGIOSU")
    return str(value).strip().translate(table).casefold().replace(" ", "_")


def detect_column(columns, alias_key):
    normalized = {normalize(column): column for column in columns}
    for alias in ALIASES[alias_key]:
        match = normalized.get(normalize(alias))
        if match is not None:
            return match
    return None


def is_yes(value: object, default: bool = True) -> bool:
    if pd.isna(value) or str(value).strip() == "":
        return default
    return normalize(value) in {"evet", "e", "yes", "true", "1", "aktif", "kullaniyor"}


def is_factory(value: object) -> bool:
    text = normalize(value)
    return any(word in text for word in ("ofis", "fabrika", "depo", "is_yeri"))


def get_mapping(df: pd.DataFrame):
    columns = list(df.columns)
    none_label = "(Yok)"
    options = [none_label, *columns]

    def select(label, key, required=False):
        detected = detect_column(columns, key)
        default = options.index(detected) if detected in options else 0
        value = st.selectbox(label, options, index=default, key=f"map_{key}")
        if required and value == none_label:
            st.warning(f"'{label}' alanını seçmelisiniz.")
        return None if value == none_label else value

    with st.expander("Excel sütunlarını kontrol et", expanded=False):
        c1, c2, c3 = st.columns(3)
        with c1:
            id_col = select("Çalışan / sicil no", "id")
            name_col = select("Ad soyad", "name")
            type_col = select("Nokta tipi", "type")
        with c2:
            address_col = select("Adres", "address")
            lat_col = select("Enlem", "lat")
            lon_col = select("Boylam", "lon")
        with c3:
            active_col = select("Aktif mi?", "active")
            service_col = select("Servis kullanıyor mu?", "uses_service")
    return {
        "id": id_col,
        "name": name_col,
        "type": type_col,
        "address": address_col,
        "lat": lat_col,
        "lon": lon_col,
        "active": active_col,
        "uses_service": service_col,
    }


def standardize(df: pd.DataFrame, mapping: dict) -> pd.DataFrame:
    df = df.dropna(how="all").copy()
    out = pd.DataFrame(index=df.index)
    out["Calisan_ID"] = df[mapping["id"]] if mapping["id"] else range(len(df))
    out["Ad_Soyad"] = df[mapping["name"]].fillna("").astype(str) if mapping["name"] else ""
    out["Tip"] = df[mapping["type"]].fillna("Çalışan").astype(str) if mapping["type"] else "Çalışan"
    out["Adres"] = df[mapping["address"]].fillna("").astype(str) if mapping["address"] else ""
    out["Enlem"] = pd.to_numeric(df[mapping["lat"]], errors="coerce") if mapping["lat"] else math.nan
    out["Boylam"] = pd.to_numeric(df[mapping["lon"]], errors="coerce") if mapping["lon"] else math.nan
    out["Aktif_mi"] = df[mapping["active"]].apply(is_yes) if mapping["active"] else True
    out["Servis_Kullaniyor_mu"] = (
        df[mapping["uses_service"]].apply(is_yes) if mapping["uses_service"] else True
    )
    return out


@st.cache_data(show_spinner=False, ttl=86400)
def cached_geocode(address: str, city: str):
    return geocode_address(address, city)


def result_workbook(result, employees: pd.DataFrame) -> bytes:
    summary_rows = []
    stop_rows = []
    for route in result.routes:
        summary_rows.append(
            {
                "Rota": f"Rota {route.vehicle_no}",
                "Yolcu": route.occupancy,
                "Mesafe_km": round(route.distance_km, 2),
                "Surus_dk": round(route.drive_minutes, 1),
                "Toplam_dk": round(route.total_minutes, 1),
                "Sure_Asimi": "Evet" if route.exceeds_limit else "Hayır",
            }
        )
        for order, matrix_index in enumerate(route.employee_indices, start=1):
            row = employees.iloc[matrix_index - 1]
            stop_rows.append(
                {
                    "Rota": f"Rota {route.vehicle_no}",
                    "Durak_Sirasi": order,
                    "Calisan_ID": row["Calisan_ID"],
                    "Ad_Soyad": row["Ad_Soyad"],
                    "Adres": row["Adres"],
                    "Enlem": row["Enlem"],
                    "Boylam": row["Boylam"],
                }
            )
    output = BytesIO()
    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
        pd.DataFrame(summary_rows).to_excel(writer, sheet_name="Rota_Ozeti", index=False)
        pd.DataFrame(stop_rows).to_excel(writer, sheet_name="Duraklar", index=False)
        workbook = writer.book
        header = workbook.add_format({"bold": True, "font_color": "white", "bg_color": "#285A84"})
        number = workbook.add_format({"num_format": "0.0"})
        for sheet_name, frame in (("Rota_Ozeti", pd.DataFrame(summary_rows)), ("Duraklar", pd.DataFrame(stop_rows))):
            sheet = writer.sheets[sheet_name]
            for col, name in enumerate(frame.columns):
                sheet.write(0, col, name, header)
                width = min(max(len(name) + 2, *(len(str(v)) + 2 for v in frame[name].head(200))), 42)
                sheet.set_column(col, col, width)
            sheet.freeze_panes(1, 0)
            sheet.autofilter(0, 0, max(len(frame), 1), max(len(frame.columns) - 1, 0))
        writer.sheets["Rota_Ozeti"].set_column("C:E", 12, number)
    return output.getvalue()


with st.sidebar:
    st.header("Planlama ayarları")
    mode_label = st.radio("Rota sayısı", ["Sabit 3 servis", "Otomatik (minimum)"])
    capacity = st.number_input("Araç kapasitesi", min_value=1, max_value=100, value=35, step=1)
    direction_label = st.radio("Sefer yönü", ["Sabah: çalışan → fabrika", "Akşam: fabrika → çalışan"])
    max_minutes = st.number_input("Maksimum rota süresi (0 = sınır yok)", min_value=0, max_value=240, value=0)
    wait_seconds = st.number_input("Durak başına bekleme (sn)", min_value=0, max_value=300, value=45, step=5)
    use_road = st.checkbox("Yol ağı sürelerini kullan", value=True)
    st.caption("Yol servisine ulaşılamazsa sistem yaklaşık mesafeyle çalışmaya devam eder.")

uploaded = st.file_uploader("Çalışan adres Excel'ini yükleyin", type=["xlsx", "xls"])

if uploaded is None:
    st.info("Başlamak için Excel dosyanızı yükleyin. Hazır şablon proje paketinin içindedir.")
    st.stop()

raw_bytes = uploaded.getvalue()
file_key = hashlib.sha256(raw_bytes).hexdigest()
if st.session_state.get("file_key") != file_key:
    st.session_state["file_key"] = file_key
    st.session_state["raw_df"] = pd.read_excel(BytesIO(raw_bytes))
    st.session_state.pop("result", None)
    st.session_state.pop("geocoded_employees", None)

raw_df = st.session_state["raw_df"]
mapping = get_mapping(raw_df)
working = standardize(raw_df, mapping)

valid_people = working[working["Aktif_mi"] & working["Servis_Kullaniyor_mu"]].copy()
factory_mask = valid_people["Tip"].apply(is_factory)
factory_rows = valid_people[factory_mask]
employees = valid_people[~factory_mask].reset_index(drop=True)

st.subheader("1. Veri kontrolü")
c1, c2, c3 = st.columns(3)
c1.metric("Aktif servis kullanıcısı", len(employees))
c2.metric("Eksik çalışan koordinatı", int(employees[["Enlem", "Boylam"]].isna().any(axis=1).sum()))
c3.metric("Fabrika satırı", "Bulundu" if not factory_rows.empty else "Elle girilecek")

with st.expander("Yüklenen veriyi göster", expanded=False):
    st.dataframe(working, use_container_width=True, hide_index=True)

st.markdown("#### Fabrika bilgisi")
if not factory_rows.empty and factory_rows[["Enlem", "Boylam"]].notna().all(axis=1).any():
    factory = factory_rows[factory_rows[["Enlem", "Boylam"]].notna().all(axis=1)].iloc[0]
    factory_lat = float(factory["Enlem"])
    factory_lon = float(factory["Boylam"])
    factory_address = factory["Adres"] or "Fabrika"
    st.success(f"Excel'den alındı: {factory_address} ({factory_lat:.5f}, {factory_lon:.5f})")
else:
    f1, f2, f3 = st.columns([2, 1, 1])
    factory_address = f1.text_input("Fabrika adresi", value="")
    factory_lat = f2.number_input("Fabrika enlem", value=39.776000, format="%.6f")
    factory_lon = f3.number_input("Fabrika boylam", value=30.520000, format="%.6f")
    st.caption("Yukarıdaki örnek koordinatları gerçek fabrikanın koordinatlarıyla değiştirin.")

missing_mask = employees[["Enlem", "Boylam"]].isna().any(axis=1)
if missing_mask.any():
    st.warning(f"{missing_mask.sum()} çalışanın koordinatı eksik. Adres sütunundan ücretsiz olarak tamamlayabilirsiniz.")
    city = st.text_input("Adres aramasında eklenecek şehir", value="Eskişehir, Türkiye")
    if st.button("Eksik koordinatları adresten bul"):
        progress = st.progress(0)
        failures = []
        missing_indices = list(employees.index[missing_mask])
        for count, idx in enumerate(missing_indices, start=1):
            address = employees.at[idx, "Adres"]
            if not address:
                failures.append(str(employees.at[idx, "Calisan_ID"]))
            else:
                try:
                    found = cached_geocode(address, city)
                except Exception:
                    found = None
                if found:
                    employees.at[idx, "Enlem"], employees.at[idx, "Boylam"] = found
                else:
                    failures.append(str(employees.at[idx, "Calisan_ID"]))
                time.sleep(1.05)
            progress.progress(count / len(missing_indices))
        st.session_state["geocoded_employees"] = employees
        if failures:
            st.warning("Koordinatı bulunamayan siciller: " + ", ".join(failures))
        else:
            st.success("Eksik koordinatlar tamamlandı.")

if "geocoded_employees" in st.session_state:
    employees = st.session_state["geocoded_employees"]

ready = not employees.empty and employees[["Enlem", "Boylam"]].notna().all(axis=1).all()
st.subheader("2. Rotaları oluştur")
if st.button("Optimizasyonu çalıştır", type="primary", disabled=not ready):
    coordinates = [(factory_lat, factory_lon)] + list(zip(employees["Enlem"], employees["Boylam"]))
    with st.spinner("Rotalar hesaplanıyor..."):
        try:
            result = plan_routes(
                coordinates=coordinates,
                capacity=int(capacity),
                mode="fixed" if mode_label.startswith("Sabit") else "auto",
                fixed_vehicle_count=3,
                direction="morning" if direction_label.startswith("Sabah") else "evening",
                wait_seconds_per_stop=int(wait_seconds),
                max_route_minutes=float(max_minutes),
                use_road_network=use_road,
            )
            st.session_state["result"] = result
            st.session_state["result_employees"] = employees.copy()
            st.session_state["result_factory"] = (factory_lat, factory_lon, factory_address)
            st.session_state["result_direction"] = direction_label
            st.session_state["result_capacity"] = int(capacity)
        except Exception as exc:
            st.error(str(exc))

result = st.session_state.get("result")
if result is None:
    if not ready:
        st.error("Optimizasyonu çalıştırmak için tüm aktif çalışanların enlem ve boylamı bulunmalı.")
    st.stop()

employees = st.session_state["result_employees"]
factory_lat, factory_lon, factory_address = st.session_state["result_factory"]
result_direction = st.session_state["result_direction"]
result_capacity = st.session_state["result_capacity"]

st.subheader("3. Optimizasyon sonucu")
for warning in result.warnings:
    st.warning(warning)

nonempty_routes = [route for route in result.routes if route.occupancy]
avg_fill = sum(route.occupancy for route in nonempty_routes) / (len(nonempty_routes) * result_capacity) if nonempty_routes else 0
r1, r2, r3, r4 = st.columns(4)
r1.metric("Planlanan servis", result.vehicle_count)
r2.metric("Ortalama doluluk", f"%{avg_fill * 100:.0f}")
r3.metric("En uzun rota", f"{max((r.total_minutes for r in nonempty_routes), default=0):.0f} dk")
r4.metric("Hesaplama kaynağı", result.matrix_source)

palette = [
    [40, 90, 132], [213, 94, 0], [0, 140, 120], [163, 75, 148],
    [230, 159, 0], [86, 180, 233], [204, 121, 167], [0, 114, 178],
]
path_data = []
point_data = [{"lon": factory_lon, "lat": factory_lat, "label": "Fabrika", "color": [196, 44, 44], "radius": 150}]

for route in nonempty_routes:
    color = palette[(route.vehicle_no - 1) % len(palette)]
    ordered_coordinates = []
    labels = []
    for matrix_index in route.path_indices:
        if matrix_index == 0:
            ordered_coordinates.append((factory_lat, factory_lon))
            labels.append("Fabrika")
        else:
            row = employees.iloc[matrix_index - 1]
            ordered_coordinates.append((float(row["Enlem"]), float(row["Boylam"])))
            labels.append(str(row["Ad_Soyad"] or row["Adres"] or row["Calisan_ID"]))
            point_data.append(
                {
                    "lon": float(row["Boylam"]), "lat": float(row["Enlem"]),
                    "label": f"Rota {route.vehicle_no} · {labels[-1]}", "color": color, "radius": 95,
                }
            )
    try:
        geometry = fetch_osrm_geometry(ordered_coordinates) if result.matrix_source.startswith("OSRM") else []
    except Exception:
        geometry = []
    if not geometry:
        geometry = [[lon, lat] for lat, lon in ordered_coordinates]
    path_data.append({"path": geometry, "color": color, "route": f"Rota {route.vehicle_no}"})

layers = [
    pdk.Layer("PathLayer", path_data, get_path="path", get_color="color", get_width=6, width_min_pixels=3, pickable=True),
    pdk.Layer(
        "ScatterplotLayer", point_data, get_position="[lon, lat]", get_fill_color="color",
        get_radius="radius", radius_min_pixels=5, radius_max_pixels=13, pickable=True,
    ),
]
view_state = pdk.ViewState(latitude=factory_lat, longitude=factory_lon, zoom=11.2, pitch=0)
deck = pdk.Deck(
    layers=layers,
    initial_view_state=view_state,
    map_style="https://basemaps.cartocdn.com/gl/positron-gl-style/style.json",
    tooltip={"text": "{label}{route}"},
)
st.pydeck_chart(deck, use_container_width=True)

for route in nonempty_routes:
    stop_names = []
    for matrix_index in route.employee_indices:
        row = employees.iloc[matrix_index - 1]
        stop_names.append(str(row["Ad_Soyad"] or row["Adres"] or row["Calisan_ID"]))
    if result_direction.startswith("Sabah"):
        sequence = " → ".join([*stop_names, "Fabrika"])
    else:
        sequence = " → ".join(["Fabrika", *stop_names])
    status = " · ⚠️ Süre sınırı aşıldı" if route.exceeds_limit else ""
    st.markdown(
        f"""<div class="route-card"><b>Rota {route.vehicle_no}</b> · {route.occupancy}/{result_capacity} yolcu ·
        {route.distance_km:.1f} km · {route.total_minutes:.0f} dk{status}<br>
        <span class="muted">{sequence}</span></div>""",
        unsafe_allow_html=True,
    )

export_bytes = result_workbook(result, employees)
st.download_button(
    "📥 Rota sonuçlarını Excel olarak indir",
    data=export_bytes,
    file_name="servis_rota_sonuclari.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
)
