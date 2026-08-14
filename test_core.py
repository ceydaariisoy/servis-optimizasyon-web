import unittest

from core import (
    CommonStop,
    assign_common_stops_to_routes,
    build_estimated_matrices,
    cluster_common_stops,
    plan_routes,
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


if __name__ == "__main__":
    unittest.main()
