# CRT styling for the shelter terminal

## Overview

`CRTRenderer` (`rendering/crt.py`) is a **post-processor** applied to the composed
**800×480** UI frame after apps/chrome are drawn and **before** `Display.show`.

```
UI Apps + chrome → AppState.compose_frame() → CRTRenderer → Display
```

Effects are procedural (Pillow only). No Fallout assets or logos.

**Important:** there is **no barrel distortion / geometry warp**. Touch coordinates stay
`0…799 × 0…479` and match hitboxes. Convex-glass look comes from vignette, corner mask,
and glare only.

## Warning

Strong flicker can cause discomfort for some people. Default `subtle` uses a very low
flicker (or effectively mild). Prefer `off` or `subtle` for long sessions; use `strong`
only for demos.

## Configuration

In `config.yaml` / `config.example.yaml`:

```yaml
crt: !CrtConfig
  preset: subtle          # off | subtle | strong
  # Optional overrides (omit / null = preset default):
  # enabled: true
  # scanlines: 0.10
  # vignette: 0.20
  # grain: 0.025
  # glare: 0.08
  # flicker: 0.006
  # glow: 0.0
  # rounded_corners: 24
  # grain_fps: 5
  grain_seed: 42
```

| Preset | Intent |
|--------|--------|
| `off` | Pixel-identical copy of the UI frame |
| `subtle` | Default — readable on 5″; **glow=0** |
| `strong` | Demo look — heavier scanlines/vignette/grain; optional glow |

Numeric overrides are clamped to safe ranges.

## Effects

| Effect | Notes |
|--------|--------|
| Scanlines | Cached horizontal lines every 3 px |
| Vignette | Cached elliptical darkening; corners darker |
| Rounded mask | Cached; outside → black |
| Glare | Cached soft top-left glass highlight |
| Grain | Small tile scaled up; refreshed at `grain_fps` |
| Flicker | Tiny brightness sine; capped |
| Glow | Optional BoxBlur blend; **off in subtle** |

## Caching

Cached once per (resolution + settings fingerprint):

- scanlines, vignette, glare, corner mask
- grain tile / current grain frame (single buffer, replaced on fps tick)

No history of processed frames. No per-effect threads.

## Performance (Pi 3A+ / 512 MB)

Recommended for device:

```yaml
crt: !CrtConfig
  preset: subtle
  glow: 0
  grain_fps: 3
  flicker: 0.004
```

Or disable completely:

```yaml
crt: !CrtConfig
  preset: off
```

When CRT is **enabled**, AppState uses a **full-frame** present path (partial patches
cannot carry post-FX). When **off**, the previous partial-update path remains.

## Dev simulator

Right-hand panel buttons (do **not** receive CRT):

- `CRT off`
- `CRT subtle`
- `CRT strong`

Runtime switch applies to the current process only (not written to disk).

```bash
.venv/bin/python piboy_dev.py
```

## Disable

- Config: `preset: off`
- Dev: button **CRT off**

## Manual check (UTM)

Prefer **subtle** for first review; **strong** is demo-only.

- [ ] All six tabs in `off` / `subtle` / `strong`
- [ ] Russian text remains readable (especially ДОСТУП keypad)
- [ ] Selected / disabled states distinguishable
- [ ] Footer readable
- [ ] Taps center and near edges / rounded corners
- [ ] Runtime CRT switch without restart
- [ ] Simulator side panel has no CRT / no flicker
- [ ] No noticeable touch lag
- [ ] Clean exit (no hung threads)

## Benchmark

```bash
.venv/bin/python scripts/bench_crt.py
```
