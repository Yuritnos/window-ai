"""Exercise real Qt control signals and export the controls' own rendering."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import tempfile

os.environ["QT_QPA_PLATFORM"] = "offscreen"
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QFontDatabase, QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QCheckBox, QLineEdit, QSystemTrayIcon
from mascot import Controller, screen_rect
from geometry import Point, seat_point
from preferences import CHARACTER_LABELS, load_preferences, load_session


def check_contact(controller):
    mascot = controller.mascot
    seat = controller.seat()
    origin = controller.desktop.origin()
    assert abs(origin.x() + mascot.frame.anchor.x - seat.x) <= .51
    assert abs(origin.y() + mascot.frame.anchor.y
               - controller.pref.offset - seat.y) <= .51
    for contact in mascot.frame.contacts:
        distance = (origin.y() + contact.y - controller.pref.offset - seat.y
                    - controller.edge_slope() * (origin.x() + contact.x - seat.x))
        assert abs(distance) <= .75, distance
    assert mascot.mask().isEmpty(), "Binary masks destroy antialiased edges"


def scroll(widget, direction=1):
    center = widget.rect().center()
    event = QWheelEvent(QPointF(center), QPointF(widget.mapToGlobal(center)), QPoint(), QPoint(0, 120 * direction),
                        Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase,
                        False)
    QApplication.sendEvent(widget, event)


app = QApplication([])
app.setQuitOnLastWindowClosed(False)
app.setStyle("Fusion")
# The headless Qt platform does not discover installed Windows fonts itself.
for filename in ("segoeui.ttf", "seguisb.ttf", "segoeuib.ttf", "msyh.ttc"):
    QFontDatabase.addApplicationFont(str(Path(os.environ["SystemRoot"]) / "Fonts" / filename))
checks = []
with tempfile.TemporaryDirectory(prefix="window-ai-qa-") as config:
    args = argparse.Namespace(config_dir=config, status_file=None,
                              show_settings=False, no_settings=True, quit_after=0)
    controller = Controller(app, args)
    controls = controller.controls
    assert controls.windowTitle() == "window AI — Controls"
    assert not controls.isVisible()
    controls.showMinimized()
    QTest.mouseDClick(controller.mascot, Qt.MouseButton.LeftButton)
    assert controls.isVisible() and not controls.isMinimized()
    controls.close()
    assert not controls.isVisible() and controller.mascot.isVisible()
    controls.move(-20000, -20000)
    controller.tray.activated.emit(QSystemTrayIcon.ActivationReason.Trigger)
    assert controls.isVisible() and app.primaryScreen().availableGeometry().contains(controls.frameGeometry().topLeft())
    controls.hide()
    checks.append("Mascot double-click restores minimized controls; tray click restores hidden, off-screen controls")

    mascot = controller.mascot
    start_height, start_seat = controller.pref.height, controller.seat()
    center = mascot.rect().center()
    QTest.mousePress(mascot, Qt.MouseButton.LeftButton, pos=center)
    assert mascot.drag_offset is None
    QTest.mouseMove(mascot, center + QPoint(15, 5))
    QTest.mouseRelease(mascot, Qt.MouseButton.LeftButton)
    scroll(mascot)
    assert (controller.pref.height, controller.seat()) == (start_height, start_seat)
    closed_menu = controller.make_menu()
    assert not next(action for action in closed_menu.actions() if action.text() == "Larger").isEnabled()
    QTest.mouseDClick(mascot, Qt.MouseButton.LeftButton)
    scroll(mascot)
    assert controller.pref.height == start_height + 4
    open_menu = controller.make_menu()
    larger = next(action for action in open_menu.actions() if action.text() == "Larger")
    assert larger.isEnabled()
    QTest.mousePress(mascot, Qt.MouseButton.LeftButton, pos=mascot.rect().center())
    assert mascot.drag_offset is not None
    controls.showMinimized()
    assert mascot.drag_offset is None
    scroll(mascot)
    larger.trigger()
    assert controller.pref.height == start_height + 4 and controller.seat() == start_seat
    QTest.mouseRelease(mascot, Qt.MouseButton.LeftButton)
    controls.hide()
    checks.append("Desktop dragging, wheel and resize menu require open controls; minimizing cancels a drag")

    original_seat = controller.seat()
    for height in (32, 60, 120, 320):
        controls.size_number.setValue(height)
        assert controller.pref.height == controller.mascot.height() == height
        assert controls.size_slider.value() == height
        assert controller.seat() == original_seat
        check_contact(controller)
    checks.append("Size control: 32, 60, 120, 320 px; seat remains anchored")

    for edge in ("upper", "lower", "middle"):
        controls.edge.setCurrentIndex(controls.edge.findData(edge))
        for percent in (0, 25, 100):
            controls.position_number.setValue(percent)
            expected = seat_point(controller.pref.points(), edge, percent / 100,
                                  screen_rect(controller.screen()))
            assert controller.pref.edge == edge
            assert controller.seat() == expected
            assert controls.position_slider.value() == percent * 10
            check_contact(controller)
    checks.append("Upper, lower, middle: left endpoint, 25%, right endpoint")

    assert [controls.new_character.itemText(i) for i in range(controls.new_character.count())] == list(CHARACTER_LABELS.values())
    menu = controller.make_menu()
    characters = next(action.menu() for action in menu.actions() if action.text() == "Character")
    for skin in (*list(CHARACTER_LABELS)[1:], "gpt"):
        next(action for action in characters.actions() if action.text() == CHARACTER_LABELS[skin]).trigger()
        assert controller.pref.skin == controller.mascot.art.skin == skin
        assert controller.mascot.art.image.hasAlphaChannel()
        assert not controller.mascot.sprite.isNull()
        check_contact(controller)
    checks.append("All hand-drawn characters load and follow the rails")

    at = seat_point(controller.pref.points(), "lower", .4,
                    screen_rect(controller.screen()))
    controller.drag_to(Point(at.x, at.y + 2))
    assert controller.pref.edge == "lower"
    controller.drag_to(at, bypass_snap=True)
    assert controller.pref.edge == "free"
    assert not controls.position_number.isEnabled()
    checks.append("Dragging snaps to lower edge; Shift bypass uses free placement")

    controls.edge.setCurrentIndex(controls.edge.findData("lower"))
    controls.position_number.setValue(25)
    controls.size_number.setValue(120)
    controller.save()
    loaded = load_preferences(controller.path)
    assert (loaded.height, loaded.edge, loaded.position, loaded.skin) == (120, "lower", .25, "gpt")
    checks.append("Control changes persist and reload correctly")

    gpt = controller.active
    gpt.toggle_guide(True)
    controls.new_character.setCurrentIndex(controls.new_character.findData("claude"))
    controls.add_button.click()
    claude = controller.active
    controls.size_number.setValue(150)
    controls.visible.setChecked(False)
    controls.new_character.setCurrentIndex(controls.new_character.findData("deepseek"))
    controls.add_button.click()
    deepseek = controller.active
    controls.size_number.setValue(96)
    controls.edge.setCurrentIndex(controls.edge.findData("upper"))
    controls.position_number.setValue(60)
    assert len(controller.companions) == controls.instances.count() == 3
    assert [c.pref.skin for c in controller.companions] == ["gpt", "claude", "deepseek"]
    assert (gpt.pref.height, claude.pref.height, deepseek.pref.height) == (120, 150, 96)
    assert gpt.mascot.isVisible() and not claude.mascot.isVisible() and deepseek.mascot.isVisible()
    controls.instances.setCurrentIndex(controls.instances.findData(claude.id))
    assert controller.active is claude and controls.size_number.value() == 150
    assert gpt.guide.isVisible(), "Selecting another mascot must not change GPT's guide"
    controls.visible.setChecked(True)
    assert claude.mascot.isVisible()
    controls.instances.setCurrentIndex(controls.instances.findData(gpt.id))
    assert controls.guide.isChecked()
    controls.guide.setChecked(False)
    controls.instances.setCurrentIndex(controls.instances.findData(claude.id))
    controller.save()
    restored = load_session(controller.path)
    assert [c.preferences.skin for c in restored.mascots] == ["gpt", "claude", "deepseek"]
    assert [c.preferences.height for c in restored.mascots] == [120, 150, 96]
    assert restored.selected_id == claude.id
    checks.append("Add/select/hide/resize work independently for three simultaneous mascots; session round-trips")

    # A duplicate is allowed and removing it must leave the original group intact.
    controls.new_character.setCurrentIndex(controls.new_character.findData("deepseek"))
    controls.add_button.click()
    assert len(controller.companions) == 4
    controls.remove_button.click()
    assert len(controller.companions) == controls.instances.count() == 3
    assert [c.id for c in controller.companions] == [gpt.id, claude.id, deepseek.id]
    controller.select(claude.id)
    controller.save()
    checks.append("Duplicate character allowed; removing selected instance preserves the others")

    controls.resize(560, 880)
    controls.show()
    app.processEvents()
    assert abs(controls.remove_button.geometry().center().y() - controls.instances.geometry().center().y()) <= 1
    wheel_controls = (
        (controls.instances, controls.instances.currentIndex),
        (controls.new_character, controls.new_character.currentIndex),
        (controls.edge, controls.edge.currentIndex),
        (controls.size_slider, controls.size_slider.value),
        (controls.size_number, controls.size_number.value),
        (controls.position_slider, controls.position_slider.value),
        (controls.position_number, controls.position_number.value),
        (controls.offset, controls.offset.value),
    )
    for widget, value in wheel_controls:
        widget.setFocus()
        before = value()
        editor = widget.findChild(QLineEdit)
        for target in (widget, editor) if editor else (widget,):
            for direction in (1, -1):
                scroll(target, direction)
                assert value() == before, widget.accessibleName()
    checks.append("Wheel input leaves dropdowns, sliders and numeric fields unchanged")

    assert all(box.text() != "Launch at startup" for box in controls.findChildren(QCheckBox))
    checks.append("The control panel has no launch-at-startup checkbox")

    assert controls.grab().save(str(ROOT / "qa" / "controls-preview.png"))
    controls.hide()
    controller.quit()
    controller.mascot.close()

report = {"result": "passed", "checks": checks,
          "preview": "controls-preview.png", "method": "Qt signals and widget rendering"}
(ROOT / "qa" / "controls-verification.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
print(json.dumps(report, indent=2))
