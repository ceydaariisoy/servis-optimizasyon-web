import unittest

from core import (
    CommonStop,
    assign_common_stops_to_routes,
    build_estimated_matrices,
    cluster_common_stops,
    generate_candidate_stops,
    optimize_candidate_stops,
    plan_routes,
    update_routes_incrementally,
)


class RoutePlannerTests(unittest.TestCase):
    def setUp(self):
        self.coords = [
            (39.7760, 30.5200),
            (39.7820, 30.5050),
            (39.7850, 30.4730),
            (39.7641, 30.5233),
            (39.7900, 30.5100),
            (39.7800, 30.4900),
        ]

    def test_fixed_routes_cover_every_employee_once(self):
        result = plan_routes(self.coords, capacity=2, mode="fixed", fixed_vehicle_count=3, use_road_network=False)
        assigned = [idx for route in result.routes for idx in route.employee_indices]
        self.assertEqual(sorted(assigned), list(range(1, len(self.coords))))
        self.assertTrue(all(route.occupancy <= 2 for route in result.routes))

    def test_auto_uses_minimum_capacity_vehicle_count(self):
        result = plan_routes(self.coords, capacity=3, mode="auto", use_road_network=False)
        self.assertEqual(result.vehicle_count, 2)

    def test_morning_routes_end_at_factory(self):
        result = plan_routes(self.coords, capacity=3, mode="auto", direction="morning", use_road_network=False)
        self.assertTrue(all(route.path_indices[-1] == 0 for route in result.routes if route.path_indices))

    def test_capacity_error_is_clear(self):
        with self.assertRaisesRegex(ValueError, "en az 3 araç"):
            plan_routes(self.coords, capacity=2, mode="fixed", fixed_vehicle_count=2, use_road_network=False)

    def test_common_stop_model_minimizes_stop_count_and_assigns_once(self):
        close_coordinates = [
            (39.77600, 30.52000),
            (39.77630, 30.52025),
            (39.77575, 30.52035),
            (39.77615, 30.51970),
        ]
        stops = cluster_common_stops(
            close_coordinates,
            max_walk_m=500,
            capacity=10,
            time_limit_seconds=2,
        )
        assigned = [employee for stop in stops for employee in stop.member_indices]
        self.assertEqual(len(stops), 1)
        self.assertEqual(sorted(assigned), list(range(len(close_coordinates))))
        self.assertLessEqual(stops[0].max_walk_m, 500)

    def test_midpoint_candidate_can_cover_two_employees_with_one_stop(self):
        # Evler yaklaşık 600 m ayrı olsa da ortadaki ortak nokta iki çalışana da
        # 500 m sınırı içinde kalır. Sadece ev adreslerini aday alan model bunu
        # göremez; durak seçimi içeren modelin temel farkı budur.
        employee_coordinates = [
            (39.77600, 30.52000),
            (39.78140, 30.52000),
        ]
        candidates = generate_candidate_stops(
            employee_coordinates,
            max_walk_m=500,
            walking_factor=1.0,
        )
        stops, minimum_stop_count, minimum_proven = optimize_candidate_stops(
            employee_coordinates,
            candidates,
            max_walk_m=500,
            target_average_walk_m=500,
            walking_factor=1.0,
            time_limit_seconds=2,
        )
        assigned = [employee for stop in stops for employee in stop.member_indices]
        self.assertEqual(minimum_stop_count, 1)
        self.assertTrue(minimum_proven)
        self.assertEqual(len(stops), 1)
        self.assertEqual(sorted(assigned), [0, 1])
        self.assertEqual(stops[0].source, "Otomatik ortak nokta")
        self.assertLessEqual(stops[0].max_walk_m, 500)

    def test_ortools_routes_respect_capacity_without_splitting_stops(self):
        employee_coordinates = [
            (39.7820, 30.5050),
            (39.7822, 30.5052),
            (39.7850, 30.4730),
            (39.7852, 30.4732),
            (39.7641, 30.5233),
            (39.7643, 30.5235),
        ]
        coordinates = [(39.7760, 30.5200), *employee_coordinates]
        duration_matrix, _ = build_estimated_matrices(coordinates)
        stops = [
            CommonStop(0, [0, 1], [0, 25]),
            CommonStop(2, [2, 3], [0, 25]),
            CommonStop(4, [4, 5], [0, 25]),
        ]
        routes = assign_common_stops_to_routes(
            stops,
            coordinates,
            vehicle_count=2,
            capacity=4,
            duration_matrix=duration_matrix,
            direction="morning",
            wait_seconds_per_stop=45,
            max_route_minutes=120,
            time_limit_seconds=2,
        )
        assigned_anchors = [stop.anchor_index for route in routes for stop in route]
        self.assertEqual(sorted(assigned_anchors), [0, 2, 4])
        self.assertTrue(all(sum(stop.passenger_count for stop in route) <= 4 for route in routes))

    def test_approved_only_policy_does_not_generate_home_or_midpoint_candidates(self):
        employee_coordinates = [(39.7760, 30.5200), (39.7810, 30.5200)]
        candidates = generate_candidate_stops(
            employee_coordinates,
            max_walk_m=500,
            walking_factor=1.0,
            approved_candidates=[(39.7785, 30.5200, "Onaylı ortak durak")],
            allow_automatic_candidates=False,
        )
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].source, "Yüklenen aday durak")

    def test_incremental_update_adds_new_employee_to_existing_stop(self):
        employee_coordinates = [
            (39.77600, 30.52000),
            (39.78500, 30.50000),
            (39.77620, 30.52010),
        ]
        baseline_routes = [
            [
                CommonStop(
                    anchor_index=0,
                    member_indices=[0],
                    walking_distances_m=[0],
                    latitude=39.77600,
                    longitude=30.52000,
                    label="Mevcut durak 1",
                    source="Onaylı durak",
                )
            ],
            [
                CommonStop(
                    anchor_index=1,
                    member_indices=[1],
                    walking_distances_m=[0],
                    latitude=39.78500,
                    longitude=30.50000,
                    label="Mevcut durak 2",
                    source="Onaylı durak",
                )
            ],
        ]
        routes, _, _, meta = update_routes_incrementally(
            employee_coordinates=employee_coordinates,
            baseline_routes=baseline_routes,
            factory_coordinates=(39.7767, 30.5206),
            max_walk_m=500,
            target_average_walk_m=300,
            capacity=2,
            direction="morning",
            max_route_minutes=120,
            mode="auto",
            use_road_network=False,
        )
        assigned = [employee for route in routes for stop in route for employee in stop.member_indices]
        self.assertEqual(sorted(assigned), [0, 1, 2])
        self.assertEqual(meta["preserved_employee_count"], 2)
        self.assertEqual(meta["added_to_existing_count"], 1)
        self.assertEqual(meta["new_stop_count"], 0)

    def test_incremental_update_creates_only_local_change_when_needed(self):
        employee_coordinates = [
            (39.77600, 30.52000),
            (39.79000, 30.49000),
        ]
        baseline_routes = [
            [
                CommonStop(
                    anchor_index=0,
                    member_indices=[0],
                    walking_distances_m=[0],
                    latitude=39.77600,
                    longitude=30.52000,
                    label="Mevcut durak",
                    source="Onaylı durak",
                )
            ]
        ]
        routes, _, _, meta = update_routes_incrementally(
            employee_coordinates=employee_coordinates,
            baseline_routes=baseline_routes,
            factory_coordinates=(39.7767, 30.5206),
            max_walk_m=500,
            target_average_walk_m=300,
            capacity=4,
            direction="morning",
            max_route_minutes=120,
            mode="auto",
            use_road_network=False,
            allow_automatic_candidates=True,
        )
        assigned = [employee for route in routes for stop in route for employee in stop.member_indices]
        self.assertEqual(sorted(assigned), [0, 1])
        self.assertEqual(meta["preserved_employee_count"], 1)
        self.assertEqual(meta["new_stop_count"], 1)


if __name__ == "__main__":
    unittest.main()
