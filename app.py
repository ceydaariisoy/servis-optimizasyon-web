from __future__ import annotations

from io import BytesIO
import hashlib
import math

import pandas as pd
import pydeck as pdk
import streamlit as st

from core import (
    fetch_osrm_geometry,
    plan_routes,
)


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
st.caption(
    "Enlem ve boylam içeren Excel'i yükleyin; sistem minimum servis sayısını, "
    "durak sırasını ve güzergâhları oluştursun."
)


FACTORY_ADDRESS = (
    "VitrA Karo Sanayi ve Ticaret A.Ş., 4 Eylül Mah. "
    "Osman Rusçuk Cd. No:13, Bozüyük, Bilecik"
)
# Kampüs merkezi için yaklaşık koordinat. Servis kapısı biliniyorsa arayüzden değiştirilebilir.
FACTORY_LAT = 39.903830
FACTORY_LON = 30.084850


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


def result_workbook(result, employees: pd.DataFrame, capacity: int) -> bytes:
    summary_rows = []
    stop_rows = []
    for route in result.routes:
        summary_rows.append(
            {
                "Rota": f"Rota {route.vehicle_no}",
                "Yolcu": route.occupancy,
                "Kapasite": capacity,
                "Doluluk_Orani": route.occupancy / capacity,
                "Mesafe_km": round(route.distance_km, 1),
                "Surus_Suresi_dk": round(route.drive_minutes),
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
        percent = workbook.add_format({"num_format": "0%"})
        for sheet_name, frame in (("Rota_Ozeti", pd.DataFrame(summary_rows)), ("Duraklar", pd.DataFrame(stop_rows))):
            sheet = writer.sheets[sheet_name]
            for col, name in enumerate(frame.columns):
                sheet.write(0, col, name, header)
                width = min(max(len(name) + 2, *(len(str(v)) + 2 for v in frame[name].head(200))), 42)
                sheet.set_column(col, col, width)
            sheet.freeze_panes(1, 0)
            sheet.autofilter(0, 0, max(len(frame), 1), max(len(frame.columns) - 1, 0))
        writer.sheets["Rota_Ozeti"].set_column("D:D", 15, percent)
        writer.sheets["Rota_Ozeti"].set_column("E:F", 18)
    return output.getvalue()


with st.sidebar:
    st.header("Planlama ayarları")
    mode_label = st.radio(
        "Rota sayısı",
        ["Sabit 3 servis", "Otomatik (minimum)"],
        index=1,
    )
    capacity = st.number_input("Araç kapasitesi", min_value=1, max_value=100, value=45, step=1)
    direction_label = st.radio(
        "Sefer yönü",
        ["Sabah (08.00 varış): çalışan → fabrika", "Akşam (17.30 çıkış): fabrika → çalışan"],
    )
    use_road_network = st.checkbox("Gerçek yol güzergâhını kullan", value=True)
    road_consent = False
    if use_road_network:
        road_consent = st.checkbox(
            "Koordinatların yol hesabı için açık OSRM servisine gönderilmesini onaylıyorum. "
            "İsim, sicil ve adres gönderilmez."
        )
    st.caption("Mesai: 08.00–17.30 · Durak başına bekleme süresi eklenmez.")

uploaded = st.file_uploader("Koordinatlı çalışan Excel'ini yükleyin", type=["xlsx", "xls"])

if uploaded is None:
    st.info("Başlamak için `Enlem` ve `Boylam` sütunları dolu olan Excel dosyanızı yükleyin.")
    st.stop()

raw_bytes = uploaded.getvalue()
file_key = hashlib.sha256(raw_bytes).hexdigest()
if st.session_state.get("file_key") != file_key:
    try:
        st.session_state["raw_df"] = pd.read_excel(BytesIO(raw_bytes))
        st.session_state["file_key"] = file_key
        st.session_state.pop("result", None)
    except Exception as exc:
        st.error(f"Excel dosyası okunamadı: {exc}")
        st.stop()

raw_df = st.session_state["raw_df"]
mapping = get_mapping(raw_df)
working = standardize(raw_df, mapping)

if mapping["lat"] is None or mapping["lon"] is None:
    st.error("Excel'de `Enlem` ve `Boylam` sütunları bulunamadı.")
    st.stop()

valid_people = working[working["Aktif_mi"] & working["Servis_Kullaniyor_mu"]].copy()
factory_mask = valid_people["Tip"].apply(is_factory)
factory_rows = valid_people[factory_mask]
employees = valid_people[~factory_mask].reset_index(drop=True)

st.subheader("1. Veri kontrolü")
c1, c2, c3 = st.columns(3)
c1.metric("Aktif servis kullanıcısı", len(employees))
c2.metric("Eksik çalışan koordinatı", int(employees[["Enlem", "Boylam"]].isna().any(axis=1).sum()))
c3.metric("Minimum servis", math.ceil(len(employees) / int(capacity)) if len(employees) else 0)

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
    factory_address = f1.text_input("Fabrika adresi", value=FACTORY_ADDRESS)
    factory_lat = f2.number_input("Fabrika enlem", value=FACTORY_LAT, format="%.6f")
    factory_lon = f3.number_input("Fabrika boylam", value=FACTORY_LON, format="%.6f")
    st.caption(
        "Koordinatlar VitrA Bozüyük kampüs merkezini yaklaşık gösterir. "
        "Servis araçlarının kullandığı kapının koordinatı biliniyorsa onunla değiştirin."
    )

missing_mask = employees[["Enlem", "Boylam"]].isna().any(axis=1)
if missing_mask.any():
    missing_rows = ", ".join(str(index + 2) for index in employees.index[missing_mask][:20])
    st.error(
        f"{int(missing_mask.sum())} çalışanın Enlem veya Boylam bilgisi eksik. "
        f"Excel satırlarını tamamlayıp dosyayı yeniden yükleyin: {missing_rows}"
    )
else:
    st.success(f"{len(employees)} personelin koordinatı hazır. Rota hesabına geçebilirsiniz.")

ready = not employees.empty and employees[["Enlem", "Boylam"]].notna().all(axis=1).all()
road_ready = not use_road_network or road_consent
st.subheader("2. Rotaları oluştur")
if use_road_network and not road_consent:
    st.info("Gerçek yol güzergâhı için sol menüdeki koordinat paylaşım onayını işaretleyin.")
if st.button("Optimizasyonu çalıştır", type="primary", disabled=not ready or not road_ready):
    coordinates = [(factory_lat, factory_lon)] + list(zip(employees["Enlem"], employees["Boylam"]))
    with st.spinner("Rotalar hesaplanıyor..."):
        try:
            result = plan_routes(
                coordinates=coordinates,
                capacity=int(capacity),
                mode="fixed" if mode_label.startswith("Sabit") else "auto",
                fixed_vehicle_count=3,
                direction="morning" if direction_label.startswith("Sabah") else "evening",
                wait_seconds_per_stop=0,
                max_route_minutes=0,
                use_road_network=bool(use_road_network),
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
r1, r2, r3 = st.columns(3)
r1.metric("Önerilen servis sayısı", result.vehicle_count)
r2.metric("Toplam çalışan", len(employees))
r3.metric("Ortalama doluluk", f"%{avg_fill * 100:.0f}")

palette = [
    [40, 90, 132], [213, 94, 0], [0, 140, 120], [163, 75, 148],
    [230, 159, 0], [86, 180, 233], [204, 121, 167], [0, 114, 178],
]
path_data = []
point_data = [
    {
        "lon": factory_lon,
        "lat": factory_lat,
        "label": "Fabrika",
        "stop_no": "F",
        "color": [196, 44, 44],
        "radius": 150,
    }
]

for route in nonempty_routes:
    color = palette[(route.vehicle_no - 1) % len(palette)]
    ordered_coordinates = []
    labels = []
    stop_number_by_index = {
        matrix_index: order
        for order, matrix_index in enumerate(route.employee_indices, start=1)
    }
    for matrix_index in route.path_indices:
        if matrix_index == 0:
            ordered_coordinates.append((factory_lat, factory_lon))
            labels.append("Fabrika")
        else:
            row = employees.iloc[matrix_index - 1]
            ordered_coordinates.append((float(row["Enlem"]), float(row["Boylam"])))
            labels.append(str(row["Adres"] or row["Ad_Soyad"] or row["Calisan_ID"]))
            point_data.append(
                {
                    "lon": float(row["Boylam"]), "lat": float(row["Enlem"]),
                    "label": f"Rota {route.vehicle_no} · Durak {stop_number_by_index[matrix_index]}: {labels[-1]}",
                    "stop_no": str(stop_number_by_index[matrix_index]),
                    "color": color,
                    "radius": 95,
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
    pdk.Layer(
        "TextLayer",
        point_data,
        get_position="[lon, lat]",
        get_text="stop_no",
        get_color=[255, 255, 255],
        get_size=11,
        get_alignment_baseline="center",
        get_text_anchor="middle",
        pickable=False,
    ),
]
all_lats = [factory_lat, *employees["Enlem"].astype(float).tolist()]
all_lons = [factory_lon, *employees["Boylam"].astype(float).tolist()]
view_state = pdk.ViewState(
    latitude=(min(all_lats) + max(all_lats)) / 2,
    longitude=(min(all_lons) + max(all_lons)) / 2,
    zoom=9.8,
    pitch=0,
)
deck = pdk.Deck(
    layers=layers,
    initial_view_state=view_state,
    map_style="https://basemaps.cartocdn.com/gl/positron-gl-style/style.json",
    tooltip={"text": "{label}{route}"},
)
st.pydeck_chart(deck, use_container_width=True)

for route in nonempty_routes:
    st.markdown(
        f"""<div class="route-card"><b>Rota {route.vehicle_no}</b> · {route.occupancy}/{result_capacity} yolcu ·
        {route.distance_km:.1f} km · {route.drive_minutes:.0f} dk</div>""",
        unsafe_allow_html=True,
    )
    stop_rows = []
    if not result_direction.startswith("Sabah"):
        stop_rows.append({"Durak": "Başlangıç", "Sicil": "-", "Ad Soyad": "Fabrika", "Adres": factory_address})
    for order, matrix_index in enumerate(route.employee_indices, start=1):
        row = employees.iloc[matrix_index - 1]
        stop_rows.append(
            {
                "Durak": order,
                "Sicil": row["Calisan_ID"],
                "Ad Soyad": row["Ad_Soyad"],
                "Adres": row["Adres"],
            }
        )
    if result_direction.startswith("Sabah"):
        stop_rows.append({"Durak": "Varış", "Sicil": "-", "Ad Soyad": "Fabrika", "Adres": factory_address})
    with st.expander(f"Rota {route.vehicle_no} durak listesini göster"):
        st.dataframe(pd.DataFrame(stop_rows), use_container_width=True, hide_index=True)

export_bytes = result_workbook(result, employees, result_capacity)
st.download_button(
    "📥 Rota sonuçlarını Excel olarak indir",
    data=export_bytes,
    file_name="servis_rota_sonuclari.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
)
