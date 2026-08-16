# CRT styling for the shelter terminal

## Overview

`CRTRenderer` (`rendering/crt.py`) post-processes the composed **800×480** UI frame
before `Display.show` on the **simulator / framebuffer CPU path**.
On Raspberry Pi with `display_config.driver: gles`, the same look is applied in a
**GPU fragment shader** instead (see [GPU path](#gpu-path-on-raspberry-pi)).

```
UI Apps + chrome → AppState.compose_frame() → CRTRenderer → Display
display touch → CRTRenderer.display_to_ui → hit-test (logical 800×480)
```

All effects are procedural (Pillow). No Fallout assets.

## Black-frame flash (fixed)

Cause: `watch_function` ran on a **background thread** and called Tk
`PhotoImage` / `canvas.itemconfigure` directly (Tk is not thread-safe), while
UI input could compose/CRT in parallel and race `clear_buffer`.

Fix: `FramePresenter` (queue size 1) + `RenderGate`; all canvas swaps via
`root.after` on the Tk main thread; one permanent canvas image item; strong
`PhotoImage` ref; never clear to black between frames.

Temporary: preset `flicker: 0` so intentional brightness flicker is not confused
with this bug.


Pure `RGB(0,0,0)` made multiply/alpha overlays invisible. A tiny green-black
**phosphor floor** lifts blacks (e.g. ~`(0,4–8,1–3)`) so scanlines, grain,
vignette and glare read across the whole glass — not only on bright UI chrome.

## Warning

Strong flicker can cause discomfort. Prefer `subtle` for long sessions; use
`strong` for demos. Default flicker stays very low.

## Pipeline

```
UI frame
→ phosphor black level
→ optional glow
→ barrel distortion (cached mesh)
→ scanlines (multiply)
→ signed grain
→ vignette
→ glass glare (screen)
→ rounded glass mask / bezel + rim
→ output 800×480
```

## Configuration

```yaml
crt: !CrtConfig
  preset: subtle          # off | subtle | strong
  # phosphor_floor: 0.018
  # scanlines: 0.16
  # vignette: 0.42
  # grain: 0.045
  # glare: 0.14
  # flicker: 0.004
  # glow: 0.0
  # rounded_corners: 24
  # bezel_inset: 8
  # curvature: 0.009
  # grain_fps: 5
  grain_seed: 42
```

| Preset | Character |
|--------|-----------|
| `off` | Pixel-identical UI |
| `subtle` | Soft glass, light curvature, **glow=0** |
| `strong` | Decorative CRT; text still readable |

## Curvature & touch

`curvature > 0` applies a mild barrel-style warp (edges pull inward). The same
geometry module (`rendering/crt_geometry.py`) is used for:

- rendering (cached Pillow `MESH`);
- touch: **display → UI** via `CRTRenderer.display_to_ui`.

When `off` or `curvature: 0`, coordinates are unchanged.

## Dev simulator

Panel buttons (no CRT on the panel itself): **CRT off / subtle / strong**.

```bash
.venv/bin/python piboy_dev.py
```

Preview PNGs: `docs/crt/{off,subtle,strong,calibration}.png`

```bash
.venv/bin/python scripts/generate_crt_previews.py
.venv/bin/python scripts/bench_crt.py
```

## Pi 3A+ recommendation

**Framebuffer (CPU CRT)** — keep CRT light or off:

```yaml
display_config: !DisplayConfig
  driver: framebuffer
crt: !CrtConfig
  preset: off          # or subtle with curvature: 0, grain: 0 on slow Pi
```

**GPU CRT (OpenGL ES)** — after the KMS spike is green:

```yaml
display_config: !DisplayConfig
  driver: gles
crt: !CrtConfig
  preset: subtle
  glow: 0
```

Disable CRT entirely: `preset: off` (GPU passthrough or CPU identity).

## GPU path on Raspberry Pi

UI is still composed with Pillow. CRT runs in a **GLES fragment shader**
([`interaction/GlesCrtDisplay.py`](../interaction/GlesCrtDisplay.py),
[`rendering/shaders/crt.frag`](../rendering/shaders/crt.frag)).

```
compose_frame → GlesCrtDisplay staging → GL present thread → KMSDRM
touch → crt_geometry.display_to_ui (same barrel math as the shader)
```

### Dependencies

```bash
sudo apt-get install -y libsdl2-2.0-0 libegl1 libgles2 \
  libsdl2-dev libegl-dev libgles-dev   # if pygame builds from source
cd ~/piboy
.venv/bin/pip install -r requirements-pi.txt   # includes pygame, PyOpenGL
```

User groups: `video`, `render`, `input`.

### Hardware spike (required before trusting gles)

Stop piboy, then:

```bash
SDL_VIDEODRIVER=kmsdrm .venv/bin/python scripts/spike_gles_kms.py
```

| Result | Action |
|--------|--------|
| Green clear / pattern on panel, clean exit, fb piboy still works | set `driver: gles` |
| Black screen / hang / DRM busy | keep `driver: framebuffer` |

Document the outcome here as **Pi GLES status**: _pending on device_ (fill in after spike).

### systemd

See [`deploy/piboy.service`](../deploy/piboy.service): `SupplementaryGroups=video render input`,
`SDL_VIDEODRIVER=kmsdrm`, `ExecStartPre` hide-fb-cursor.

### Profiling

```bash
PIBOY_GL_PROFILE=1 .venv/bin/python piboy.py
```

### Acceptance checklist (GPU vs Mac Pillow subtle)

- [ ] Dark areas show phosphor / faint grain
- [ ] Header text readable
- [ ] Scanlines visible on mid-tones
- [ ] Vignette at corners
- [ ] Curvature at edges; corner tap hits the intended control
- [ ] Grain moves for ~1s without touching the screen
- [ ] `preset: off` looks flat; switching preset updates the panel

## Manual check (UTM)

- [ ] Black areas show faint grain / scanlines / glare
- [ ] Visible bezel + rounded glass
- [ ] Vignette: corners darker than center
- [ ] subtle vs strong clearly different
- [ ] Tabs / footer not clipped badly
- [ ] Edge and center taps land correctly with curvature
- [ ] ДОСТУП keypad readable
- [ ] Panel has no CRT flicker
