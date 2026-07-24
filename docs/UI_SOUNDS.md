# UI sounds

## Architecture

```
UI action → UiSoundService → UiSoundPort → Null | PyAudio (ALSA on Pi)
```

Apps never call PyAudio. Semantic events: `key`, `touch`, `confirm`, `back`, `denied`, `lock`.
Disabled hits stay **silent**.

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

Panel → **Тест звука** (logs device + plays confirm).

## Device selection

JACK is not required. Order when resolving the PortAudio device:

1. Configured index (from local YAML or env)
2. Configured name substring
3. PortAudio default output
4. First real output (ALSA preferred over JACK)

Stream: typically stereo @ 44100/48000; mono 22050 assets converted once at preload.
Blocking `write` in one worker; `stop_stream` between clicks.

## Full YAML example

```yaml
audio: !AudioConfig
  ui_sounds: !UiSoundsConfig
    enabled: true
    volume: 0.35
    clicks_during_call: false
    min_interval_ms: 30
    output_device_index: 0
    output_device_name: null
```

## Assets

`resources/sounds/*.wav` — mono 16-bit PCM @ 22050 Hz.

```bash
.venv/bin/python scripts/generate_ui_sounds.py
```
