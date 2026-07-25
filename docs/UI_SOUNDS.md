# UI sounds

## Architecture

```
UI action → UiSoundService → UiSoundPort → Null | PyAudio (ALSA on Pi)
```

Apps never call PyAudio. Semantic events: `key`, `touch`, `confirm`, `back`, `denied`, `lock`, `boot`.
Disabled hits stay **silent**.

At startup (when `boot_splash: true`), the shell shows a POST splash and plays `boot.wav`
before entering the first tab app. Touch/key after ~1.5 s skips the splash and stops boot audio.

## Important: which config files are used

| File | Role |
|------|------|
| `config.ini` | **Logging only** (`fileConfig`). Never put audio settings here. |
| `config.yaml` | Runtime app config (gitignored). Created with defaults if missing. |
| `config.example.yaml` | **Documentation / template only — not loaded at runtime.** |
| `config.local.yaml` | Local overrides (gitignored). Preferred for `output_device_index`. |

Load order:

1. `config.yaml` (or built-in defaults)
2. `config.local.yaml` if present
3. `PIBOY_UI_SOUND_DEVICE_INDEX` / `PIBOY_UI_SOUND_DEVICE_NAME` (highest priority for device)

At startup the log shows:

- loaded config path(s);
- `UI sound device source=config|env|auto`;
- selected `index` / `name`.

## UTM: force ALSA device index 0

```bash
.venv/bin/python scripts/list_audio_devices.py
# find the line for HDA Intel … (hw:0,0) — usually index 0

cp config.local.example.yaml config.local.yaml
# ensure: output_device_index: 0

.venv/bin/python piboy_dev.py
```

Or without a file:

```bash
PIBOY_UI_SOUND_DEVICE_INDEX=0 .venv/bin/python piboy_dev.py
```

Panel → **Тест звука** calls `UiSoundService.play(CONFIRM)` (not log-only).

## Diagnose silent playback (UTM)

```bash
# Same backend as the app — should be audible on plughw:0,0 equivalent:
.venv/bin/python scripts/test_ui_sound_device.py --device 0

# Compare with ALSA:
aplay -D plughw:0,0 resources/sounds/confirm.wav
```

Enable DEBUG for worker/write tracing:

```bash
# in config.ini raise piboy.ui_sound to DEBUG, or:
PIBOY_UI_SOUND_DEVICE_INDEX=0 .venv/bin/python -c "
import logging; logging.basicConfig(level=logging.DEBUG)
from backend.ui_sound_pyaudio import PyAudioUiSoundBackend
...
"
```

## Device selection

JACK is not required. Order when resolving the PortAudio device:

1. Configured index (from local YAML or env)
2. Configured name substring
3. PortAudio default output
4. First real output (ALSA preferred over JACK)

Stream: typically stereo @ 44100/48000; mono 22050 assets converted once at preload.
Blocking `write` in one worker; stream stays open between short clicks. Long `boot`
playback can be interrupted via `stop_current()` when the splash is skipped.

## Full YAML example

```yaml
audio: !AudioConfig
  ui_sounds: !UiSoundsConfig
    enabled: true
    volume: 0.35
    clicks_during_call: false
    min_interval_ms: 30
    boot_splash: true
    output_device_index: 0
    output_device_name: null
```

## Assets

`resources/sounds/*.wav` — mono 16-bit PCM @ 22050 Hz.

`key_*.wav` / `touch_*.wav` are procedural **mechanical keyboard** clicks
(impact noise + short housing modes), not tonal beeps.

`boot.wav` (~7.2 s) — classic PC POST beep + floppy seek/read; played once at
startup splash (`UiSoundEvent.BOOT`). Regenerate:

```bash
.venv/bin/python scripts/generate_ui_sounds.py
```
