#!/usr/bin/env python3
"""Play a bundled UI WAV through PyAudioUiSoundBackend (same path as the app).

Usage (UTM):
  PIBOY_UI_SOUND_DEVICE_INDEX=0 .venv/bin/python scripts/test_ui_sound_device.py --device 0
  .venv/bin/python scripts/test_ui_sound_device.py --device 0 --wav resources/sounds/confirm.wav

Does not call aplay; uses PortAudio only.
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.ui_sound_pcm import prepare_pcm_for_device
from backend.ui_sound_pyaudio import PyAudioUiSoundBackend


def main() -> int:
    logging.basicConfig(level=logging.DEBUG, format='[%(levelname)s] %(name)s: %(message)s')
    parser = argparse.ArgumentParser(description='Test PyAudio UI sound backend')
    parser.add_argument('--device', type=int, default=None, help='PortAudio output device index')
    parser.add_argument('--wav', type=Path, default=ROOT / 'resources' / 'sounds' / 'confirm.wav')
    parser.add_argument('--repeat', type=int, default=2, help='How many times to play')
    parser.add_argument('--gap', type=float, default=0.4, help='Pause between plays (seconds)')
    args = parser.parse_args()

    if not args.wav.is_file():
        print(f'WAV not found: {args.wav}', file=sys.stderr)
        return 1

    backend = PyAudioUiSoundBackend(
        device_index=args.device,
        selection_source='env' if args.device is not None else 'auto',
    )
    if not backend.available:
        print('Backend unavailable (Null / open failed)', file=sys.stderr)
        backend.close()
        return 2

    print(f'device: {backend.describe_output()}')
    with wave.open(str(args.wav), 'rb') as wf:
        raw = wf.readframes(wf.getnframes())
        src_rate = wf.getframerate()
        src_ch = wf.getnchannels()
    pcm = prepare_pcm_for_device(
        raw,
        src_rate=src_rate,
        src_channels=src_ch,
        dst_rate=backend.output_rate,
        dst_channels=backend.output_channels,
    )
    print(
        f'pcm bytes={len(pcm)} rate={backend.output_rate} ch={backend.output_channels} '
        f'from {args.wav.name} ({src_rate}Hz/{src_ch}ch)'
    )

    for i in range(max(1, args.repeat)):
        print(f'play {i + 1}/{args.repeat} …')
        backend.play_pcm(pcm, backend.output_rate, backend.output_channels)
        # Allow worker + ALSA to drain (write returns when buffered, not when audible done)
        time.sleep(max(args.gap, len(pcm) / (backend.output_rate * 2 * backend.output_channels) + 0.15))

    print(f'writes={backend.write_count}')
    backend.close()
    print('done')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
