# UI sounds

## Architecture

```
UI action → UiSoundService → UiSoundPort → Null | PyAudio (ALSA on Pi)
```

Apps never call PyAudio. Semantic events: `key`, `touch`, `confirm`, `back`, `denied`, `lock`.
Disabled hits stay **silent**.

## Device selection

JACK is **not** required. PortAudio may probe JACK during init; that chatter is
locally suppressed only around enumeration. Playback uses an explicit
`output_device_index` when possible.

Order:

1. `output_device_index` (if valid output)
2. `output_device_name` (case-insensitive substring, prefer ALSA)
3. PortAudio default output
4. First device with `maxOutputChannels > 0` (ALSA preferred over JACK)

Stream format: usually **stereo** + device default rate (often 44100/48000).
Assets are mono 22050; converted **once at preload** (no per-click resample).

Playback: one long-lived blocking stream, one worker, `stream.write(..., exception_on_underflow=False)`,
then `stop_stream` between clicks (no silence filler → no underrun spam).

## Config

```yaml
audio: !AudioConfig
  ui_sounds: !UiSoundsConfig
    enabled: true
    volume: 0.35
    clicks_during_call: false
    min_interval_ms: 30
    output_device_index: null   # or 0
    output_device_name: null    # e.g. "bcm2835" / "plughw"
```

## List devices (UTM)

```bash
.venv/bin/python scripts/list_audio_devices.py
```

Then set `output_device_index` to a device with `out > 0` that matches
`aplay -l` / working `plughw:0,0`.

## Dev panel

**Тест звука** logs the selected device and plays `confirm`.

## Assets

`resources/sounds/*.wav` — mono 16-bit PCM @ 22050 Hz, ~18 KB total.

```bash
.venv/bin/python scripts/generate_ui_sounds.py
```
