# UI sounds

## Architecture

```
UI action → UiSoundService → UiSoundPort → Null | PyAudio (ALSA on Pi)
```

Apps never call PyAudio. They (or `AppState`) emit semantic events:

| Event | Typical trigger |
|-------|-----------------|
| `key` | Digits, arrows |
| `touch` | Tabs, on-screen buttons |
| `confirm` | Enter / OK |
| `back` | Esc, Backspace, Сброс |
| `denied` | Access denied |
| `lock` | Successful lock pulse |
| Disabled hits | **silent** (uniform) |

## Config

```yaml
audio: !AudioConfig
  ui_sounds: !UiSoundsConfig
    enabled: true
    volume: 0.35
    clicks_during_call: false
    min_interval_ms: 30
```

During an active intercom call (`RINGING`…`CONNECTED`), click events (`key`/`touch`)
are suppressed when `clicks_during_call: false`. Confirm/denied/lock still play.

## Assets

`resources/sounds/*.wav` — mono 16-bit PCM @ 22050 Hz, ~20–80 ms, ~18 KB total.

Regenerate:

```bash
.venv/bin/python scripts/generate_ui_sounds.py
```

## Dev panel

- **UI sound on/off**
- **Volume − / +**
- **Тест звука** (confirm)

## Shutdown

`AppState.stop_touch()` closes the sound worker and PortAudio stream.

## UTM check

```bash
.venv/bin/python piboy_dev.py
```

Tap keypad / tabs; use **Тест звука**. If no audio device, app stays up (Null backend, one warning).
