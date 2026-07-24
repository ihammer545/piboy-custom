#!/usr/bin/env python3
"""List PortAudio / PyAudio devices (no stream open probes)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.ui_sound_pyaudio import _suppress_alsa_enumeration_noise, enumerate_devices


def main() -> int:
    try:
        import pyaudio
    except ImportError as exc:
        print(f'pyaudio not available: {exc}', file=sys.stderr)
        return 1

    with _suppress_alsa_enumeration_noise():
        pa = pyaudio.PyAudio()
        try:
            devices, default_out = enumerate_devices(pa)
        finally:
            pa.terminate()

    print(f'device_count={len(devices)} default_output_index={default_out}')
    print(f'{"idx":>4}  {"in":>3}  {"out":>3}  {"rate":>8}  {"host":<16}  name')
    for d in devices:
        mark = ' DEFAULT OUTPUT' if d.is_default_output else ''
        print(
            f'{d.index:4d}  {d.max_input_channels:3d}  {d.max_output_channels:3d}  '
            f'{d.default_sample_rate:8.0f}  {d.host_api:<16.16}  {d.name}{mark}'
        )
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
