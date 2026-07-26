# UI sounds

## Architecture

```
UI action → UiSoundService → UiSoundPort → Null | PyAudio (ALSA on Pi)
```

Apps never call PyAudio. Semantic events: `key`, `touch`, `confirm`, `back`, `denied`, `lock`, `boot`.
Disabled hits stay **silent**.

## How the user picks a speaker (normal path)

1. **Auto ranking** prefers concrete devices (`hw:`, HDA, Analog, USB…) over silent PortAudio `default` / JACK.
2. After the boot splash (if enabled), a **first-run** screen asks «Слышите звук?»
   - **СЛЫШУ** — save device to `config.local.yaml`
   - **СЛЕДУЮЩЕЕ** — try the next ranked device + test tone
   - **ПРОПУСТИТЬ** — mark setup done; reconfigure later in **СЕРВ**
3. Tab **СЕРВ** always has **ЗВУК UI**: list, ТЕСТ, ВЫБРАТЬ, АВТО (persists to `config.local.yaml`).

Env vars / hand-edited YAML remain for debugging; they are not required for normal use.

At startup (when `boot_splash: true`), the shell shows a POST splash and plays `boot.wav`
before audio setup / the first tab app. Touch/key after ~1.5 s skips the splash.

## Important: which config files are used

| File | Role |
|------|------|
| `config.ini` | **Logging only** (`fileConfig`). Never put audio settings here. |
| `config.yaml` | Runtime app config (gitignored). Created with defaults if missing. |
| `config.example.yaml` | **Documentation / template only — not loaded at runtime.** |
| `config.local.yaml` | Local overrides (gitignored). Written by in-app setup (`output_device_index`, `audio_setup_done`). |

Load order:

1. `config.yaml` (or built-in defaults)
2. `config.local.yaml` if present
3. `PIBOY_UI_SOUND_DEVICE_INDEX` / `PIBOY_UI_SOUND_DEVICE_NAME` (highest priority for device; skips first-run wizard)

At startup the log shows:

- loaded config path(s);
- `UI sound device source=config|env|auto`;
- selected `index` / `name`.

## UTM / debug override

```bash
.venv/bin/python scripts/list_audio_devices.py
PIBOY_UI_SOUND_DEVICE_INDEX=0 .venv/bin/python piboy_dev.py
```

Or copy `config.local.example.yaml` → `config.local.yaml` with `output_device_index: 0` and `audio_setup_done: true`.

Panel → **Тест звука** calls `UiSoundService.play(CONFIRM)` (not log-only).

## Diagnose silent playback (UTM)

```bash
.venv/bin/python scripts/test_ui_sound_device.py --device 0
aplay -D plughw:0,0 resources/sounds/confirm.wav
```

## Device selection (auto)

1. Configured index / name (local YAML or env)
2. Ranked outputs: concrete ALSA/CoreAudio before abstract `default` / JACK
3. PortAudio default only if it is concrete (or nothing better exists)

Stream: typically stereo @ 44100/48000; mono 22050 assets converted once at preload.
Blocking `write` in one worker; stream stays open between short clicks. Long `boot`
playback can be interrupted via `stop_current()` when the splash is skipped.
`rebind_output()` swaps the PortAudio device at runtime (СЕРВ / first-run).

## Full YAML example

```yaml
audio: !AudioConfig
  ui_sounds: !UiSoundsConfig
    enabled: true
    volume: 0.35
    clicks_during_call: false
    min_interval_ms: 30
    boot_splash: true
    audio_setup_done: true
    output_device_index: 0
    output_device_name: null
```

## Assets

`resources/sounds/*.wav` — mono 16-bit PCM @ 22050 Hz.

`key_*.wav` / `touch_*.wav` are procedural **mechanical keyboard** clicks.
`boot.wav` (~7.2 s) — POST beep + floppy sequence for splash.

```bash
.venv/bin/python scripts/generate_ui_sounds.py
```
