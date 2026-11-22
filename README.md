# window AI

Eleven hand-drawn companions for the Windows desktop. Choose from GPT, Claude, DeepSeek, Gemini, GLM, Grok, Kimi, Qwen, Hunyuan, MiniMax and Step. Multiple mascots can stay on the desktop together, each with its own size, position, character, visibility and dragging lock.

## Start

Download the Windows ZIP under **Assets**, extract it, and double-click **window AI.exe**. Keep `_internal` beside the executable. No separate Python installation is needed. [Latest GitHub release](https://github.com/Yuritnos/window-ai/releases/latest)

Double-clicking the executable also brings back the control panel if window AI is already running. Local builds put the executable in `dist/window AI/`.

## Controls

- **On desktop:** select which mascot to adjust or use Remove selected on the same row. Clicking or dragging a mascot while the panel is open also selects it. At least one mascot remains.
- **Add mascot:** choose a character, then click Add mascot. Duplicate characters are allowed.
- **Size:** use the slider or number field, or scroll over the mascot while the panel is open. Each instance can be 32–320 pixels tall.
- **Sit on / Along edge:** choose the upper, middle or lower wallpaper rail and any position along it. The seated hips stay anchored while the hands can hold a book, wave or rest naturally.
- **Drag:** keep the panel open and drag a mascot directly. It snaps to nearby wallpaper rails. Hold Shift for free placement, or turn snapping off. Closing, hiding or minimizing the panel pauses desktop dragging and resizing.
- **Right-click menu:** change a mascot's character while keeping its placement and size.
- **Show this mascot:** hide or show the selected instance without removing its settings.
- **Align window outline:** drag the four corners onto the Windows symbol in your wallpaper. Apply saves; Escape or Cancel keeps the previous outline. Alignment belongs to the selected mascot.
- **Controls:** double-click a mascot, click its tray icon, or open the executable. An open panel appears on the Windows taskbar. Right-click a mascot or its tray icon for a quick menu.
- **Exit all mascots:** exits the app. Closing the controls keeps the companions running.

The rails refer to the Windows symbol in the wallpaper. Free placement is also available. Mascots stay above the desktop and behind ordinary application windows. They are static illustrated poses. The renderer preserves transparent antialiased edges at the display's pixel density. The mouse wheel leaves control values alone.

Settings save automatically in `%LOCALAPPDATA%\WindowDragon\settings.json`. If that folder is blocked, settings save in `data/settings.json` beside the executable. Older artwork choices migrate to the hand-drawn GPT, keeping their size and placement. Saved groups drop retired mascots and keep the rest of their layout. Launching the app again opens the existing instance's controls.

## Development

Use Python 3.13 on Windows. In PowerShell, run these commands from the repository folder.

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe .\mascot.py
.\build.ps1
```

`assets/artwork.json` records each sprite's crop and seated anchor. The alignment line represents the seated pose, independently of hand positions. `assets/artwork-provenance.json` records the ImageGen prompts and the original GPT prompt is in `assets/sketch-generation.json`.

Validation: `python -m unittest discover -s tests -v`, `python qa/verify_controls.py`, and (after building) `python qa/verify_package.py`. The control checks exercise multiple real Qt windows and control signals; the packaged checks cover all characters, simultaneous desktop windows, persistence after restarting, portable settings fallback and ZIP integrity.

The earlier sprites reference artwork by ZipZipPipe. [Pixiv art collection](https://www.pixiv.net/artworks/148186519) · [Bilibili showcase](https://www.bilibili.com/video/BV1tE9XBbErS/)

The Hunyuan and MiniMax designs are by ZipZipPipe. The Step design is by 甶丶. All three sprites are seated adaptations. Source and usage details are recorded in `assets/artwork-provenance.json`.

- Hunyuan by ZipZipPipe. [Bilibili post](https://www.bilibili.com/opus/1242184338245681157) · [Full-body portrait](https://github.com/HABAI182/ai-girls-atlas/blob/main/assets/zipzippipe/hunyuan/zipzippipe-pixiv-150718881-p03.jpg)
- MiniMax by ZipZipPipe. [Pixiv gallery](https://www.pixiv.net/artworks/148186519) · [Full-body portrait](https://github.com/HABAI182/ai-girls-atlas/blob/main/assets/zipzippipe/minimax/zipzippipe-pixiv-148186519-p15.jpg)
- Step by 甶丶. [Bilibili post](https://www.bilibili.com/opus/1250303372583501829) · [Full-body cube lantern portrait](https://xn--pssy23gqgbz2d718b.com/works/stepfun202609210001.html)
