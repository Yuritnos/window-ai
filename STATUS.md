# window AI — 22 November 2026

Continued from the project chat “Resume work from other chat.”

- The app ships eleven hand-drawn characters. Claude and Step use the artwork and seat anchors from before the GLM-style revision.
- Each sprite uses a seated anchor for wallpaper placement. Claude reads in a left-facing three-quarter pose. GLM also sits in a three-quarter pose and is mirrored so she faces left. Both seat anchors stay on the selected rail.
- Desktop dragging and resizing require a visible control panel. Hiding, closing, or minimizing the panel cancels a drag in progress and blocks the wheel and size shortcuts. Double-clicking a mascot still opens the controls.
- The controls let you add, select, resize, hide, and remove individual mascots. Multiple instances can share the desktop. The group and the selected mascot are saved when the app closes and restored on launch.
- Older artwork choices migrate to the hand-drawn GPT while retaining saved placement. Saved groups drop Mistral, 文心一言 and MiMo and preserve the other mascots. Previous art is archived outside the release.
- The control panel puts Remove selected beside On desktop. The wheel leaves panel values alone. Scrolling over a mascot still resizes it while the controls are open.

Run `dist/window AI/window AI.exe` with its `_internal` folder alongside it, or extract `dist/window AI.zip` on another computer. The ZIP excludes this computer’s settings.

The final PNGs are listed in `assets/artwork.json`. The built-in ImageGen prompts are in `assets/artwork-provenance.json` and `assets/sketch-generation.json`. The provenance file includes the full-body references and artist credits for the new sprites.

The 18 unit tests cover geometry, preferences and rendering. `qa/controls-verification.json` records the Qt control checks. `qa/packaged-verification.json` records saved group migration and restart, desktop attachment, portable settings fallback and ZIP integrity. `qa/repair-preview.png` shows the eleven rendered sprites on sample rails.

The control panel now opens on every normal launch. If it was minimized or moved offscreen, reopening from the executable, a mascot, or the tray restores it to a usable position. A second launch waits for the running app to confirm it opened the panel.
