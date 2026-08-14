from __future__ import annotations

from io import BytesIO
import hashlib
import math

import pandas as pd
import pydeck as pdk
import streamlit as st

from core import (
    assign_common_stops_to_routes,
    cluster_common_stops,
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
    "ortak buluşma duraklarını, durak sırasını ve güzergâhları oluştursun."
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


def build_shared_routes(
    result,
    employees: pd.DataFrame,
    factory_coordinates: tuple[float, float],
    max_walk_m: int,
    direction: str,
    capacity: int,
    mode: str,
    wait_seconds_per_stop: int,
    max_route_minutes: int,
):
    """En az ortak durağı kurar; durak ataması ve sırasını birlikte optimize eder."""
    employee_coordinates = list(zip(employees["Enlem"].astype(float), employees["Boylam"].astype(float)))
    all_stops = cluster_common_stops(
        employee_coordinates,
        max_walk_m=max_walk_m,
        capacity=capacity,
        walking_factor=1.20,
    )
    coordinates = [factory_coordinates, *employee_coordinates]
    minimum_vehicle_count = math.ceil(len(employees) / capacity)
    vehicle_count = 3 if mode == "fixed" else minimum_vehicle_count
    if vehicle_count < minimum_vehicle_count:
        raise ValueError(
            f"3 araç yetersiz. Bu kapasiteyle en az {minimum_vehicle_count} araç gerekir."
        )

    # Otomatik modda kapasiteyi karşılayan en küçük sayıdan başlanır. Süre sınırı
    # sağlanmıyorsa araç sayısı birer artırılır.
    last_error: Exception | None = None
    maximum_vehicle_count = max(
        vehicle_count,
        min(len(all_stops), minimum_vehicle_count + 5),
    )
    while vehicle_count <= maximum_vehicle_count:
        try:
            allocated_routes = assign_common_stops_to_routes(
                all_stops,
                coordinates,
                vehicle_count,
                capacity,
                result.duration_matrix,
                direction,
                wait_seconds_per_stop=wait_seconds_per_stop,
                max_route_minutes=max_route_minutes,
            )
            break
        except ValueError as exc:
            last_error = exc
            if mode == "fixed":
                raise
            vehicle_count += 1
    else:
        raise ValueError(
            "Kapasite ve rota süresi sınırlarını birlikte sağlayan çözüm bulunamadı. "
            "Azami rota süresini artırın veya kapasiteyi kontrol edin."
        ) from last_error

    shared_routes = []
    for vehicle_no, allocated_stops in enumerate(allocated_routes, start=1):
        stops = []
        for stop in allocated_stops:
            anchor_employee_index = stop.anchor_index
            members = list(stop.member_indices)
            walk_by_employee = {
                employee_index: distance
                for employee_index, distance in zip(stop.member_indices, stop.walking_distances_m)
            }
            stops.append(
                {
                    "anchor_employee_index": anchor_employee_index,
                    "anchor_matrix_index": anchor_employee_index + 1,
                    "member_indices": members,
                    "walk_by_employee": walk_by_employee,
                    "passenger_count": len(members),
                    "max_walk_m": stop.max_walk_m,
                    "average_walk_m": stop.average_walk_m,
                }
            )

        ordered_stops = stops
        ordered_matrix_indices = [stop["anchor_matrix_index"] for stop in ordered_stops]
        path_indices = [*ordered_matrix_indices, 0] if direction == "morning" else [0, *ordered_matrix_indices]
        drive_seconds = sum(result.duration_matrix[a][b] for a, b in zip(path_indices, path_indices[1:]))
        distance_meters = sum(result.distance_matrix[a][b] for a, b in zip(path_indices, path_indices[1:]))
        all_walks = [
            distance
            for stop in ordered_stops
            for distance in stop["walk_by_employee"].values()
        ]
        shared_routes.append(
            {
                "vehicle_no": vehicle_no,
                "occupancy": sum(stop["passenger_count"] for stop in ordered_stops),
                "stops": ordered_stops,
                "path_indices": path_indices,
                "distance_km": distance_meters / 1000,
                "drive_minutes": drive_seconds / 60,
                "wait_minutes": len(ordered_stops) * wait_seconds_per_stop / 60,
                "total_minutes": drive_seconds / 60 + len(ordered_stops) * wait_seconds_per_stop / 60,
                "average_walk_m": sum(all_walks) / len(all_walks) if all_walks else 0,
                "max_walk_m": max(all_walks, default=0),
            }
        )
    return shared_routes, vehicle_count


def result_workbook(shared_routes, employees: pd.DataFrame, capacity: int) -> bytes:
    summary_rows = []
    stop_rows = []
    assignment_rows = []
    for route in shared_routes:
        summary_rows.append(
            {
                "Rota": f"Rota {route['vehicle_no']}",
                "Yolcu": route["occupancy"],
                "Kapasite": capacity,
                "Doluluk_Orani": route["occupancy"] / capacity,
                "Toplam_Durak_Sayisi": len(route["stops"]),
                "Coklu_Ortak_Durak": sum(stop["passenger_count"] > 1 for stop in route["stops"]),
                "Tekil_Durak": sum(stop["passenger_count"] == 1 for stop in route["stops"]),
                "Mesafe_km": round(route["distance_km"], 1),
                "Surus_Suresi_dk": round(route["drive_minutes"]),
                "Bekleme_Suresi_dk": round(route["wait_minutes"]),
                "Toplam_Sure_dk": round(route["total_minutes"]),
                "Ort_Yurume_m": round(route["average_walk_m"]),
                "En_Uzak_Yurume_m": round(route["max_walk_m"]),
            }
        )
        for order, stop in enumerate(route["stops"], start=1):
            anchor = employees.iloc[stop["anchor_employee_index"]]
            stop_rows.append(
                {
                    "Rota": f"Rota {route['vehicle_no']}",
                    "Durak_Sirasi": order,
                    "Durak_Adresi": anchor["Adres"],
                    "Durak_Turu": "Ortak" if stop["passenger_count"] > 1 else "Tekil",
                    "Yolcu_Sayisi": stop["passenger_count"],
                    "Enlem": anchor["Enlem"],
                    "Boylam": anchor["Boylam"],
                    "En_Uzak_Yurume_m": round(stop["max_walk_m"]),
                }
            )
            for employee_index in stop["member_indices"]:
                row = employees.iloc[employee_index]
                assignment_rows.append(
                    {
                        "Rota": f"Rota {route['vehicle_no']}",
                        "Durak_Sirasi": order,
                        "Calisan_ID": row["Calisan_ID"],
                        "Ad_Soyad": row["Ad_Soyad"],
                        "Ev_Adresi": row["Adres"],
                        "Durak_Adresi": anchor["Adres"],
                        "Yurume_Mesafesi_m": round(stop["walk_by_employee"][employee_index]),
                        "Durak_Enlem": anchor["Enlem"],
                        "Durak_Boylam": anchor["Boylam"],
                    }
                )
    output = BytesIO()
    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
        pd.DataFrame(summary_rows).to_excel(writer, sheet_name="Rota_Ozeti", index=False)
        pd.DataFrame(stop_rows).to_excel(writer, sheet_name="Ortak_Duraklar", index=False)
        pd.DataFrame(assignment_rows).to_excel(writer, sheet_name="Personel_Durak_Eslesmesi", index=False)
        workbook = writer.book
        header = workbook.add_format({"bold": True, "font_color": "white", "bg_color": "#285A84"})
        percent = workbook.add_format({"num_format": "0%"})
        frames = (
            ("Rota_Ozeti", pd.DataFrame(summary_rows)),
            ("Ortak_Duraklar", pd.DataFrame(stop_rows)),
            ("Personel_Durak_Eslesmesi", pd.DataFrame(assignment_rows)),
        )
        for sheet_name, frame in frames:
            sheet = writer.sheets[sheet_name]
            for col, name in enumerate(frame.columns):
                sheet.write(0, col, name, header)
                width = min(max(len(name) + 2, *(len(str(v)) + 2 for v in frame[name].head(200))), 42)
                sheet.set_column(col, col, width)
            sheet.freeze_panes(1, 0)
            sheet.autofilter(0, 0, max(len(frame), 1), max(len(frame.columns) - 1, 0))
        writer.sheets["Rota_Ozeti"].set_column("D:D", 15, percent)
        writer.sheets["Rota_Ozeti"].set_column("E:M", 18)
    return output.getvalue()


with st.sidebar:
    st.header("Planlama ayarları")
    mode_label = st.radio(
        "Rota sayısı",
        ["Sabit 3 servis", "Otomatik (kapasite + süreye göre)"],
        index=1,
    )
    capacity = st.number_input("Araç kapasitesi", min_value=1, max_value=100, value=40, step=1)
    max_walk_m = st.slider(
        "Azami yürüme mesafesi (metre)",
        min_value=200,
        max_value=1200,
        value=500,
        step=50,
        help="Yakın çalışanlar bu sınırı aşmayacak biçimde ortak bir durakta toplanır.",
    )
    max_route_minutes = st.slider(
        "Azami rota süresi (dakika)",
        min_value=60,
        max_value=180,
        value=120,
        step=5,
        help="Sürüş ve durak beklemelerinin toplamıdır. Otomatik mod bu sınır gerekirse araç ekler.",
    )
    wait_seconds_per_stop = st.number_input(
        "Durak başına bekleme (saniye)",
        min_value=0,
        max_value=180,
        value=45,
        step=15,
    )
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
    st.caption(
        "Mesai: 08.00–17.30 · Yakın çalışanlar ortak durakta buluşur · "
        "Sürüş ve durak beklemeleri birlikte sınırlandırılır."
    )

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
        st.session_state.pop("shared_routes", None)
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
    st.dataframe(working, width="stretch", hide_index=True)

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
            mode = "fixed" if mode_label.startswith("Sabit") else "auto"
            direction = "morning" if direction_label.startswith("Sabah") else "evening"
            shared_routes, optimized_vehicle_count = build_shared_routes(
                result=result,
                employees=employees,
                factory_coordinates=(factory_lat, factory_lon),
                max_walk_m=int(max_walk_m),
                direction=direction,
                capacity=int(capacity),
                mode=mode,
                wait_seconds_per_stop=int(wait_seconds_per_stop),
                max_route_minutes=int(max_route_minutes),
            )
            st.session_state["result"] = result
            st.session_state["shared_routes"] = shared_routes
            st.session_state["optimized_vehicle_count"] = optimized_vehicle_count
            st.session_state["result_employees"] = employees.copy()
            st.session_state["result_factory"] = (factory_lat, factory_lon, factory_address)
            st.session_state["result_direction"] = direction_label
            st.session_state["result_capacity"] = int(capacity)
            st.session_state["result_max_walk_m"] = int(max_walk_m)
            st.session_state["result_wait_seconds"] = int(wait_seconds_per_stop)
            st.session_state["result_max_route_minutes"] = int(max_route_minutes)
            st.session_state["result_mode"] = mode
        except Exception as exc:
            st.session_state.pop("result", None)
            st.session_state.pop("shared_routes", None)
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
result_max_walk_m = st.session_state.get("result_max_walk_m", 500)
direction = "morning" if result_direction.startswith("Sabah") else "evening"
shared_routes = st.session_state.get("shared_routes")
if shared_routes is None:
    st.error("Rota sonucu bulunamadı. Optimizasyonu yeniden çalıştırın.")
    st.stop()
optimized_vehicle_count = st.session_state.get("optimized_vehicle_count", result.vehicle_count)
result_wait_seconds = st.session_state.get("result_wait_seconds", 45)
result_max_route_minutes = st.session_state.get("result_max_route_minutes", 120)

st.subheader("3. Optimizasyon sonucu")
for warning in result.warnings:
    st.warning(warning)

nonempty_routes = [route for route in shared_routes if route["occupancy"]]
avg_fill = sum(route["occupancy"] for route in nonempty_routes) / (len(nonempty_routes) * result_capacity) if nonempty_routes else 0
total_stop_count = sum(len(route["stops"]) for route in nonempty_routes)
multi_stop_count = sum(
    stop["passenger_count"] > 1
    for route in nonempty_routes
    for stop in route["stops"]
)
single_stop_count = total_stop_count - multi_stop_count
r1, r2, r3, r4, r5, r6 = st.columns(6)
r1.metric("Önerilen servis", optimized_vehicle_count)
r2.metric("Toplam çalışan", len(employees))
r3.metric("Toplam durak", total_stop_count)
r4.metric("Çoklu ortak durak", multi_stop_count)
r5.metric("Tekil durak", single_stop_count)
r6.metric("Ortalama doluluk", f"%{avg_fill * 100:.0f}")
st.caption(
    f"Duraklar {result_max_walk_m} m azami tahmini yürüyüş sınırına göre optimize edildi. "
    "Tahmini yürüyüş, kuş uçuşu mesafeye %20 yol sapması eklenerek hesaplandı. "
    f"Durak başına {result_wait_seconds} sn bekleme ve {result_max_route_minutes} dk toplam rota sınırı kullanıldı. "
    "Sahada yaya geçidi, kaldırım ve güvenli bekleme alanı kontrolü yapılmalıdır."
)

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
    color = palette[(route["vehicle_no"] - 1) % len(palette)]
    ordered_coordinates = []
    stop_by_matrix_index = {stop["anchor_matrix_index"]: stop for stop in route["stops"]}
    stop_number_by_index = {
        stop["anchor_matrix_index"]: order for order, stop in enumerate(route["stops"], start=1)
    }
    for matrix_index in route["path_indices"]:
        if matrix_index == 0:
            ordered_coordinates.append((factory_lat, factory_lon))
        else:
            row = employees.iloc[matrix_index - 1]
            ordered_coordinates.append((float(row["Enlem"]), float(row["Boylam"])))
            stop = stop_by_matrix_index[matrix_index]
            stop_type = "Ortak" if stop["passenger_count"] > 1 else "Tekil"
            stop_label = str(row["Adres"] or f"{stop_type} Durak {stop_number_by_index[matrix_index]}")
            point_data.append(
                {
                    "lon": float(row["Boylam"]), "lat": float(row["Enlem"]),
                    "label": (
                        f"Rota {route['vehicle_no']} · {stop_type} Durak {stop_number_by_index[matrix_index]} · "
                        f"{stop['passenger_count']} yolcu · {stop_label}"
                    ),
                    "stop_no": str(stop_number_by_index[matrix_index]),
                    "color": color,
                    "radius": 95 + stop["passenger_count"] * 10,
                }
            )
    try:
        geometry = fetch_osrm_geometry(ordered_coordinates) if result.matrix_source.startswith("OSRM") else []
    except Exception:
        geometry = []
    if not geometry:
        geometry = [[lon, lat] for lat, lon in ordered_coordinates]
    path_data.append({"path": geometry, "color": color, "route": f"Rota {route['vehicle_no']}"})

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
st.pydeck_chart(deck, width="stretch")

for route in nonempty_routes:
    st.markdown(
        f"""<div class="route-card"><b>Rota {route['vehicle_no']}</b> · {route['occupancy']}/{result_capacity} yolcu ·
        {len(route['stops'])} durak · {route['distance_km']:.1f} km · {route['drive_minutes']:.0f} dk sürüş ·
        {route['total_minutes']:.0f} dk toplam ·
        ort. {route['average_walk_m']:.0f} m yürüme</div>""",
        unsafe_allow_html=True,
    )
    stop_rows = []
    if not result_direction.startswith("Sabah"):
        stop_rows.append({"Durak": "Başlangıç", "Sicil": "-", "Ad Soyad": "Fabrika", "Adres": factory_address})
    for order, stop in enumerate(route["stops"], start=1):
        row = employees.iloc[stop["anchor_employee_index"]]
        passenger_names = ", ".join(
            str(employees.iloc[index]["Ad_Soyad"] or employees.iloc[index]["Calisan_ID"])
            for index in stop["member_indices"]
        )
        stop_rows.append(
            {
                "Durak": str(order),
                "Durak Türü": "Ortak" if stop["passenger_count"] > 1 else "Tekil",
                "Yolcu": stop["passenger_count"],
                "Ortak Durak Adresi": row["Adres"],
                "En Uzak Yürüme": f"{stop['max_walk_m']:.0f} m",
                "Bu Durağa Gelecekler": passenger_names,
            }
        )
    if result_direction.startswith("Sabah"):
        stop_rows.append({"Durak": "Varış", "Sicil": "-", "Ad Soyad": "Fabrika", "Adres": factory_address})
    with st.expander(f"Rota {route['vehicle_no']} duraklarını ve yolcularını göster"):
        st.dataframe(pd.DataFrame(stop_rows), width="stretch", hide_index=True)

export_bytes = result_workbook(shared_routes, employees, result_capacity)
st.download_button(
    "📥 Rota sonuçlarını Excel olarak indir",
    data=export_bytes,
    file_name="servis_rota_sonuclari.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
)
