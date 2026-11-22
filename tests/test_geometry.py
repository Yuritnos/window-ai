from pathlib import Path
import json
import tempfile
import unittest
from unittest.mock import patch
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from geometry import (DEFAULT_CORNERS, Point, clamp, interpolate, nearest_rail,
                      project, rail, seat_point, sprite_origin, validate_corners)
from preferences import Preferences, configuration_directory, load_preferences, save_preferences


class PlacementTests(unittest.TestCase):
    def test_upper_edge_tracks_the_sloping_wallpaper(self):
        point = seat_point(DEFAULT_CORNERS, "upper", .5, (0, 0, 1920, 1080))
        self.assertAlmostEqual(point.x, (1195 + 1540) / 2)
        self.assertAlmostEqual(point.y, (433 + 383) / 2)

    def test_lower_edge_and_endpoints(self):
        self.assertEqual(seat_point(DEFAULT_CORNERS, "lower", 0, (0, 0, 1920, 1080)), Point(1195, 690))
        self.assertAlmostEqual(seat_point(DEFAULT_CORNERS, "lower", 1, (0, 0, 1920, 1080)).y, 738)

    def test_monitor_offset_and_scaled_resolution(self):
        reference = seat_point(DEFAULT_CORNERS, "upper", .7, (0, 0, 1920, 1080))
        other = seat_point(DEFAULT_CORNERS, "upper", .7, (-1280, 100, 1280, 720))
        self.assertAlmostEqual(other.x, -1280 + reference.x * 2 / 3)
        self.assertAlmostEqual(other.y, 100 + reference.y * 2 / 3)

    def test_resize_keeps_the_same_seat_anchor(self):
        seat, anchor = Point(1500, 390), Point(.37, .84)
        for width, height in ((40, 60), (80, 120), (213, 320)):
            origin = sprite_origin(seat, anchor, width, height, 3)
            self.assertAlmostEqual(origin.x + anchor.x * width, seat.x)
            self.assertAlmostEqual(origin.y + anchor.y * height - 3, seat.y)

    def test_dragging_snaps_to_the_closest_rail(self):
        for edge in ("upper", "middle", "lower"):
            seat = seat_point(DEFAULT_CORNERS, edge, .4, (0, 0, 1920, 1080))
            selected, t, actual, distance = nearest_rail(Point(seat.x, seat.y + 2), DEFAULT_CORNERS, (0, 0, 1920, 1080))
            self.assertEqual(selected, edge)
            self.assertLess(distance, 2.01)
            self.assertAlmostEqual(t, .4, delta=.005)

    def test_projection_clamps_to_each_end(self):
        self.assertEqual(project(Point(-10, 5), Point(0, 0), Point(10, 0))[0], 0)
        self.assertEqual(project(Point(25, 5), Point(0, 0), Point(10, 0))[0], 1)

    def test_invalid_calibration_is_rejected(self):
        self.assertTrue(validate_corners(DEFAULT_CORNERS))
        self.assertFalse(validate_corners((Point(.8, .1), Point(.2, .1), Point(.2, .7), Point(.8, .7))))
        self.assertFalse(validate_corners((Point(float('nan'), .1), *DEFAULT_CORNERS[1:])))

    def test_zero_length_projection_is_safe(self):
        t, closest, distance = project(Point(3, 4), Point(0, 0), Point(0, 0))
        self.assertEqual((t, closest, distance), (0, Point(0, 0), 5))


class PreferenceTests(unittest.TestCase):
    def test_default_settings_fall_back_when_local_app_data_is_unwritable(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            blocked = root / "blocked"
            blocked.write_text("This is a file, not a writable directory.")
            with patch.dict("os.environ", {"LOCALAPPDATA": str(blocked)}):
                selected = configuration_directory(None, root / "portable")
            self.assertEqual(selected, (root / "portable" / "data").resolve())
            save_preferences(selected / "settings.json", Preferences(height=92))
            self.assertEqual(load_preferences(selected / "settings.json").height, 92)

    def test_writable_local_app_data_is_preferred(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            with patch.dict("os.environ", {"LOCALAPPDATA": str(root / "local")}):
                selected = configuration_directory(None, root / "portable")
            self.assertEqual(selected, (root / "local" / "WindowDragon").resolve())
            self.assertFalse((root / "portable").exists())

    def test_explicit_config_failure_does_not_silently_change_locations(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            blocked = root / "blocked"
            blocked.write_text("file")
            with self.assertRaises(OSError):
                configuration_directory(str(blocked / "settings"), root / "portable")

    def test_roundtrip_and_validated_values(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "settings.json"
            pref = Preferences(height=124, edge="lower", position=.23, skin="deepseek")
            save_preferences(path, pref)
            loaded = load_preferences(path)
            self.assertEqual((loaded.height, loaded.edge, loaded.position, loaded.skin), (124, "lower", .23, "deepseek"))
            self.assertFalse(path.with_suffix('.tmp').exists())

    def test_corrupt_or_unsupported_settings_use_safe_defaults(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "settings.json"
            path.write_text('{broken', encoding='utf-8')
            self.assertEqual(load_preferences(path), Preferences())
            path.write_text(json.dumps({'height': 5000, 'position': -3, 'skin': 'unknown', 'corners': [None] * 4}), encoding='utf-8')
            loaded = load_preferences(path)
            self.assertEqual((loaded.height, loaded.position, loaded.skin), (320, 0, 'gpt'))
            self.assertEqual(loaded.points(), DEFAULT_CORNERS)


if __name__ == '__main__':
    unittest.main()
