import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtWidgets import QApplication
from rendering import Artwork
from preferences import CHARACTER_LABELS, load_preferences, load_session

APP = QApplication.instance() or QApplication([])


class RenderingTests(unittest.TestCase):
    def test_seated_axis_follows_slopes_at_every_size_and_dpi(self):
        for skin in CHARACTER_LABELS:
            art = Artwork(skin)
            for height in (32, 40, 60, 120, 158, 320):
                for dpr in (1, 1.25, 1.5, 2):
                    for slope in (-50 / 345, 0, 48 / 345):
                        with self.subTest(skin=skin, height=height, dpr=dpr, slope=slope):
                            frame = art.frame(height, dpr, slope)
                            self.assertEqual(frame.size.height(), height)
                            self.assertGreaterEqual(frame.pixmap.height(), round(height * dpr))
                            for point in frame.contacts:
                                error = point.y - frame.anchor.y - slope * (point.x - frame.anchor.x)
                                self.assertLess(abs(error), .15)

    def test_small_artwork_retains_partial_alpha(self):
        for skin in CHARACTER_LABELS:
            image = Artwork(skin).frame(40, 1.5, -.145).pixmap.toImage()
            alpha = bytes(image.constBits())[3::4]
            self.assertTrue(any(0 < value < 255 for value in alpha))
            self.assertIn(0, alpha)

    def test_legacy_topmost_and_seat_offset_are_migrated(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "settings.json"
            path.write_text(json.dumps(dict(height=158, position=.629, skin="pixel", on_top=True, offset=2)))
            pref = load_preferences(path)
            self.assertFalse(hasattr(pref, "on_top"))
            self.assertEqual(pref.offset, 0)
            self.assertEqual((pref.height, pref.position, pref.skin), (158, .629, "gpt"))

    def test_saved_sessions_restore_the_three_characters(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "settings.json"
            skins = ("mistral", "wenxin", "mimo")
            path.write_text(json.dumps({
                "selected_id": "old-wenxin",
                "mascots": [{"id": f"old-{skin}", "preferences": {"skin": skin}}
                            for skin in skins],
            }), encoding="utf-8")
            session = load_session(path)
            self.assertEqual([record.preferences.skin for record in session.mascots], list(skins))
            self.assertEqual(session.selected().preferences.skin, "wenxin")

    def test_all_hand_drawn_characters_are_active(self):
        assets = Path(__file__).resolve().parents[1] / "assets"
        metadata = json.loads((assets / "artwork.json").read_text(encoding="utf-8"))
        self.assertEqual(set(metadata), set(CHARACTER_LABELS))
        self.assertEqual(len(metadata), 14)
        self.assertEqual(metadata["gpt"]["file"], "sketch-seated.png")
        self.assertEqual(metadata["claude"]["file"], "claude-reading-sideways.png")
        self.assertEqual(metadata["glm"]["file"], "glm-seated-sideways.png")
        self.assertTrue(metadata["glm"]["mirror"])
        self.assertEqual(metadata["deepseek"]["file"], "deepseek-waving.png")
        self.assertEqual(metadata["hunyuan"]["file"], "hunyuan-seated.png")
        self.assertEqual(metadata["minimax"]["file"], "minimax-seated.png")
        self.assertEqual(metadata["stepfun"]["file"], "stepfun-seated.png")
        self.assertTrue(metadata["mistral"]["mirror"])
        self.assertFalse(list(assets.glob("*pixel*")))


if __name__ == "__main__":
    unittest.main()
