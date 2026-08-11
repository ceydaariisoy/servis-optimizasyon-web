"""Servis rota planlama motoru.

Harici bir optimizasyon paketi gerektirmeden, kapasite kısıtlı ve coğrafi olarak
tutarlı taslak rotalar üretir. Yol süreleri için önce OSRM denenir; servis
erişilemezse kuş uçuşu mesafe tabanlı tahmine otomatik geçilir.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import math
from typing import Iterable, Sequence
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen


EARTH_RADIUS_KM = 6371.0088


@dataclass
class RoutePlan:
    vehicle_no: int
    employee_indices: list[int]
    path_indices: list[int]
    occupancy: int
    distance_km: float
    drive_minutes: float
    total_minutes: float
    exceeds_limit: bool


@dataclass
class PlanResult:
    routes: list[RoutePlan]
    vehicle_count: int
    active_route_count: int
    matrix_source: str
    duration_matrix: list[list[float]]
    distance_matrix: list[list[float]]
    warnings: list[str]


def haversine_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    """İki (enlem, boylam) noktası arasındaki kuş uçuşu mesafeyi döndürür."""
    lat1, lon1 = map(math.radians, a)
    lat2, lon2 = map(math.radians, b)
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(h))


def build_estimated_matrices(
    coordinates: Sequence[tuple[float, float]], average_speed_kmh: float = 32.0
) -> tuple[list[list[float]], list[list[float]]]:
    """Yol ağı yoksa, mesafeyi 1,28 katsayısı ile yaklaşık yol mesafesine çevirir."""
    n = len(coordinates)
    distances = [[0.0] * n for _ in range(n)]
    durations = [[0.0] * n for _ in range(n)]
    for i in range(n):
        for j in range(i + 1, n):
            road_km = haversine_km(coordinates[i], coordinates[j]) * 1.28
            seconds = road_km / max(average_speed_kmh, 1.0) * 3600
            distances[i][j] = distances[j][i] = road_km * 1000
            durations[i][j] = durations[j][i] = seconds
    return durations, distances


def fetch_osrm_table(
    coordinates: Sequence[tuple[float, float]], timeout: int = 25
) -> tuple[list[list[float]], list[list[float]]]:
    """OSRM genel sunucusundan sürüş süresi ve yol mesafesi matrisi alır."""
    if len(coordinates) > 90:
        raise ValueError("OSRM genel sunucusu için tek seferde en fazla 90 nokta kullanılıyor.")
    coord_text = ";".join(f"{lon:.7f},{lat:.7f}" for lat, lon in coordinates)
    url = f"https://router.project-osrm.org/table/v1/driving/{coord_text}?annotations=duration,distance"
    request = Request(url, headers={"User-Agent": "Eskisehir-Servis-Optimizasyonu/1.0"})
    with urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if payload.get("code") != "Ok":
        raise RuntimeError(payload.get("message", "OSRM matrisi alınamadı."))
    durations = payload.get("durations")
    distances = payload.get("distances")
    if not durations or not distances or any(value is None for row in durations for value in row):
        raise RuntimeError("Bazı noktalar için yol süresi bulunamadı.")
    return durations, distances


def fetch_osrm_geometry(
    coordinates: Sequence[tuple[float, float]], timeout: int = 20
) -> list[list[float]]:
    """Haritada gerçek yol çizgisi için [boylam, enlem] noktalarını döndürür."""
    if len(coordinates) < 2:
        return [[coordinates[0][1], coordinates[0][0]]] if coordinates else []
    coord_text = ";".join(f"{lon:.7f},{lat:.7f}" for lat, lon in coordinates)
    url = (
        f"https://router.project-osrm.org/route/v1/driving/{coord_text}"
        "?overview=full&geometries=geojson&steps=false"
    )
    request = Request(url, headers={"User-Agent": "Eskisehir-Servis-Optimizasyonu/1.0"})
    with urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if payload.get("code") != "Ok" or not payload.get("routes"):
        raise RuntimeError("Rota geometrisi alınamadı.")
    return payload["routes"][0]["geometry"]["coordinates"]


def geocode_address(address: str, city: str = "Eskişehir, Türkiye", timeout: int = 15) -> tuple[float, float] | None:
    """Nominatim üzerinden API anahtarı olmadan tek bir adresi koordinata çevirir."""
    query = address.strip()
    if city and city.casefold() not in query.casefold():
        query = f"{query}, {city}"
    params = urlencode({"q": query, "format": "jsonv2", "limit": 1, "countrycodes": "tr"})
    request = Request(
        f"https://nominatim.openstreetmap.org/search?{params}",
        headers={"User-Agent": "Eskisehir-Servis-Optimizasyonu/1.0 (kurumsal-prototip)"},
    )
    with urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not payload:
        return None
    return float(payload[0]["lat"]), float(payload[0]["lon"])


def _route_path(employee_indices: Sequence[int], direction: str) -> list[int]:
    if direction == "morning":
        return [*employee_indices, 0]
    return [0, *employee_indices]


def _path_cost(employee_indices: Sequence[int], matrix: Sequence[Sequence[float]], direction: str) -> float:
    path = _route_path(employee_indices, direction)
    return sum(matrix[a][b] for a, b in zip(path, path[1:]))


def _nearest_neighbor(
    employee_indices: Sequence[int], matrix: Sequence[Sequence[float]], direction: str
) -> list[int]:
    remaining = set(employee_indices)
    if not remaining:
        return []
    if direction == "morning":
        current = max(remaining, key=lambda idx: matrix[idx][0])
    else:
        current = min(remaining, key=lambda idx: matrix[0][idx])
    route = [current]
    remaining.remove(current)
    while remaining:
        next_index = min(remaining, key=lambda idx: matrix[current][idx])
        route.append(next_index)
        remaining.remove(next_index)
        current = next_index
    return route


def _two_opt(route: list[int], matrix: Sequence[Sequence[float]], direction: str) -> list[int]:
    if len(route) < 3:
        return route
    best = route[:]
    best_cost = _path_cost(best, matrix, direction)
    improved = True
    while improved:
        improved = False
        for i in range(len(best) - 1):
            for j in range(i + 1, len(best)):
                candidate = best[:i] + list(reversed(best[i : j + 1])) + best[j + 1 :]
                candidate_cost = _path_cost(candidate, matrix, direction)
                if candidate_cost + 1e-9 < best_cost:
                    best, best_cost = candidate, candidate_cost
                    improved = True
        # Küçük veri için yeterli; gereksiz uzun aramayı engeller.
        if len(best) > 80:
            break
    return best


def _balanced_sizes(employee_count: int, vehicle_count: int, capacity: int) -> list[int]:
    if vehicle_count <= 0:
        raise ValueError("Araç sayısı en az 1 olmalıdır.")
    if vehicle_count * capacity < employee_count:
        raise ValueError(
            f"Kapasite yetersiz: {employee_count} çalışan için en az "
            f"{math.ceil(employee_count / capacity)} araç gerekir."
        )
    base, extra = divmod(employee_count, vehicle_count)
    sizes = [base + (1 if i < extra else 0) for i in range(vehicle_count)]
    if sizes and max(sizes) > capacity:
        raise ValueError("Rota büyüklüğü araç kapasitesini aşıyor.")
    return sizes


def _angular_clusters(
    coordinates: Sequence[tuple[float, float]],
    vehicle_count: int,
    capacity: int,
    duration_matrix: Sequence[Sequence[float]],
    direction: str,
) -> list[list[int]]:
    depot_lat, depot_lon = coordinates[0]
    employees = list(range(1, len(coordinates)))
    ordered = sorted(
        employees,
        key=lambda idx: math.atan2(coordinates[idx][0] - depot_lat, coordinates[idx][1] - depot_lon),
    )
    sizes = _balanced_sizes(len(employees), vehicle_count, capacity)
    if not employees:
        return [[] for _ in range(vehicle_count)]

    # Dairesel sıralamanın başlangıç açısını değiştirip en kısa bölünmeyi seçer.
    step = 1 if len(ordered) <= 60 else max(1, len(ordered) // 30)
    best_clusters: list[list[int]] | None = None
    best_score = math.inf
    for rotation in range(0, len(ordered), step):
        rotated = ordered[rotation:] + ordered[:rotation]
        clusters = []
        cursor = 0
        for size in sizes:
            raw = rotated[cursor : cursor + size]
            cursor += size
            route = _nearest_neighbor(raw, duration_matrix, direction)
            clusters.append(_two_opt(route, duration_matrix, direction))
        score = sum(_path_cost(route, duration_matrix, direction) for route in clusters)
        # Toplam süre yanında rotalar arası aşırı dengesizliği de azaltır.
        costs = [_path_cost(route, duration_matrix, direction) for route in clusters if route]
        if costs:
            score += (max(costs) - min(costs)) * 0.10
        if score < best_score:
            best_score, best_clusters = score, clusters
    return best_clusters or [[] for _ in range(vehicle_count)]


def plan_routes(
    coordinates: Sequence[tuple[float, float]],
    capacity: int,
    mode: str = "auto",
    fixed_vehicle_count: int = 3,
    direction: str = "morning",
    wait_seconds_per_stop: int = 45,
    max_route_minutes: float = 0,
    use_road_network: bool = True,
    average_speed_kmh: float = 32.0,
) -> PlanResult:
    """İlk koordinatı fabrika, diğerlerini çalışan kabul ederek rota üretir."""
    if len(coordinates) < 2:
        raise ValueError("En az bir fabrika ve bir çalışan noktası gerekir.")
    if capacity <= 0:
        raise ValueError("Araç kapasitesi sıfırdan büyük olmalıdır.")
    if direction not in {"morning", "evening"}:
        raise ValueError("Yön 'morning' veya 'evening' olmalıdır.")

    warnings: list[str] = []
    try:
        if not use_road_network:
            raise RuntimeError("Yol ağı seçimi kapalı.")
        duration_matrix, distance_matrix = fetch_osrm_table(coordinates)
        matrix_source = "OSRM yol ağı"
    except Exception as exc:
        duration_matrix, distance_matrix = build_estimated_matrices(coordinates, average_speed_kmh)
        matrix_source = "Yaklaşık mesafe"
        warnings.append(f"Yol ağı verisi kullanılamadı; yaklaşık mesafeye geçildi ({exc}).")

    employee_count = len(coordinates) - 1
    minimum_vehicles = math.ceil(employee_count / capacity)
    if mode == "fixed":
        vehicle_count = fixed_vehicle_count
        if vehicle_count < minimum_vehicles:
            raise ValueError(
                f"{fixed_vehicle_count} araç yetersiz. Bu kapasiteyle en az {minimum_vehicles} araç gerekir."
            )
    else:
        vehicle_count = minimum_vehicles

    while True:
        clusters = _angular_clusters(
            coordinates, vehicle_count, capacity, duration_matrix, direction
        )
        routes: list[RoutePlan] = []
        for vehicle_no, employee_indices in enumerate(clusters, start=1):
            path = _route_path(employee_indices, direction) if employee_indices else []
            drive_seconds = sum(duration_matrix[a][b] for a, b in zip(path, path[1:]))
            distance_meters = sum(distance_matrix[a][b] for a, b in zip(path, path[1:]))
            total_minutes = drive_seconds / 60 + len(employee_indices) * wait_seconds_per_stop / 60
            routes.append(
                RoutePlan(
                    vehicle_no=vehicle_no,
                    employee_indices=list(employee_indices),
                    path_indices=path,
                    occupancy=len(employee_indices),
                    distance_km=distance_meters / 1000,
                    drive_minutes=drive_seconds / 60,
                    total_minutes=total_minutes,
                    exceeds_limit=bool(max_route_minutes and total_minutes > max_route_minutes),
                )
            )

        exceeds = any(route.exceeds_limit for route in routes)
        if mode != "auto" or not max_route_minutes or not exceeds or vehicle_count >= employee_count:
            break
        vehicle_count += 1

    if any(route.exceeds_limit for route in routes):
        warnings.append("Bazı rotalar belirlenen maksimum rota süresini aşıyor.")
    return PlanResult(
        routes=routes,
        vehicle_count=vehicle_count,
        active_route_count=sum(bool(route.employee_indices) for route in routes),
        matrix_source=matrix_source,
        duration_matrix=duration_matrix,
        distance_matrix=distance_matrix,
        warnings=warnings,
    )

