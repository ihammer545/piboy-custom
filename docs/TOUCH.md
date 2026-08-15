# Touch input and calibration for the shelter terminal

## Input modes

Configure under `input` in `config.yaml` (see `config.example.yaml`):

```yaml
input: !InputConfig
  mode: touch_keyboard   # keyboard | touch | touch_keyboard
  touch: !TouchDeviceConfig
    device: /dev/input/event0
    width: 800
    height: 480
    swap_axes: false
    invert_x: false
    invert_y: false
    rotation: 0          # 0 | 90 | 180 | 270
    debounce_ms: 40
    enabled: true
```

| mode | Behaviour |
|------|-----------|
| `keyboard` | Keys / GPIO keypad only; touch backend not started |
| `touch` | Linux evdev touch (dev uses canvas tap); keyboard still works if present |
| `touch_keyboard` | Default: both |

Set `touch.enabled: false` or `mode: keyboard` to disable the touch backend.

Optional absolute ranges (`abs_x_min` / `abs_x_max` / `abs_y_min` / `abs_y_max`) override auto-detected ABS info when set.

## Development (UTM / Debian)

```bash
.venv/bin/python piboy_dev.py
```

- Main canvas is exactly **800×480**.
- **Left click** on the canvas = one finger tap (coordinates mapped to screen space).
- Clicks on the **right simulator panel** never reach the terminal UI.
- Keyboard: arrows, Enter=OK, Esc=Back, PgUp/PgDn=tabs, digits 0–9, Backspace, Delete=clear.
- No hover / wheel / right-click behaviour is used by the UI.

## Raspberry Pi (real panel)

1. Find the touch device:

```bash
sudo evtest
# or: ls -l /dev/input/by-path /dev/input/by-id
```

2. Put the path into `input.touch.device` (example `/dev/input/event2`).

3. Calibrate with `swap_axes`, `invert_x`, `invert_y`, `rotation` until the four corners match.

4. The process must be able to **read** `/dev/input/event*` (membership in group `input`, or a udev rule). The application does **not** change device permissions itself.

Example udev rule (apply manually if needed):

```
KERNEL=="event*", SUBSYSTEM=="input", MODE="0660", GROUP="input"
```

Then add the service user to group `input` and re-login.

5. Run:

```bash
.venv/bin/python piboy.py
```

If the device is missing or unreadable, the terminal logs a warning and continues with **keyboard fallback**.

## Architecture

```
Tk canvas / Linux evdev
  → TouchSource (SimulatorTouchInput | EvdevTouchInput)
  → TouchEvent (x, y in 800×480)
  → AppState (tabs / footer ignore / app content)
  → App.on_tap() → same service commands as keyboard
```

Hit targets share the same `Rect` used for drawing (`app/ui_kit.py`).
