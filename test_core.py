import unittest

from core import plan_routes


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


if __name__ == "__main__":
    unittest.main()

