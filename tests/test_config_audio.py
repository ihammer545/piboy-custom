"""Tests for runtime YAML / env loading of UI sound device settings."""
from __future__ import annotations

import os
from pathlib import Path

import environment
from environment import Environment, UiSoundsConfig, apply_ui_sound_env_overrides, load_runtime_environment
from backend.ui_sound_device import AudioDeviceInfo, select_output_device


def test_load_runtime_applies_local_yaml(tmp_path: Path, monkeypatch):
    cfg = tmp_path / 'config.yaml'
    local = tmp_path / 'config.local.yaml'
    # Minimal base — defaults via Environment save/load path
    env0 = Environment()
    environment.configure()
    environment.save(env0, str(cfg))
    local.write_text(
        'output_device_index: 0\n'
        'output_device_name: "HDA Intel"\n',
        encoding='utf-8',
    )
    monkeypatch.delenv('PIBOY_UI_SOUND_DEVICE_INDEX', raising=False)
    monkeypatch.delenv('PIBOY_UI_SOUND_DEVICE_NAME', raising=False)
    env = load_runtime_environment(str(cfg), str(local), create_if_missing=False)
    assert env.audio.ui_sounds.output_device_index == 0
    assert env.audio.ui_sounds.output_device_name == 'HDA Intel'
    assert environment.RUNTIME.ui_sound_device_source == 'config'
    assert any('config.local.yaml' in p for p in environment.RUNTIME.paths)


def test_env_var_overrides_local_yaml(tmp_path: Path, monkeypatch):
    cfg = tmp_path / 'config.yaml'
    local = tmp_path / 'config.local.yaml'
    environment.configure()
    environment.save(Environment(), str(cfg))
    local.write_text('output_device_index: 0\n', encoding='utf-8')
    monkeypatch.setenv('PIBOY_UI_SOUND_DEVICE_INDEX', '3')
    env = load_runtime_environment(str(cfg), str(local), create_if_missing=False)
    assert env.audio.ui_sounds.output_device_index == 3
    assert environment.RUNTIME.ui_sound_device_source == 'env'


def test_missing_local_keeps_auto(tmp_path: Path, monkeypatch):
    cfg = tmp_path / 'config.yaml'
    environment.configure()
    environment.save(Environment(), str(cfg))
    monkeypatch.delenv('PIBOY_UI_SOUND_DEVICE_INDEX', raising=False)
    monkeypatch.delenv('PIBOY_UI_SOUND_DEVICE_NAME', raising=False)
    env = load_runtime_environment(str(cfg), str(tmp_path / 'missing.local.yaml'),
                                   create_if_missing=False)
    assert env.audio.ui_sounds.output_device_index is None
    assert environment.RUNTIME.ui_sound_device_source == 'auto'


def test_index_zero_reaches_selection_over_default_14():
    devices = [
        AudioDeviceInfo(0, 'HDA Intel: Generic Analog (hw:0,0)', 2, 2, 44100.0, 'ALSA', False),
        AudioDeviceInfo(14, 'default', 0, 2, 44100.0, 'ALSA', True),
    ]
    # Simulate what open_ui_sound_port receives after config.local / env
    ui = UiSoundsConfig(output_device_index=0)
    d, reason = select_output_device(
        devices,
        configured_index=ui.output_device_index,
        default_output_index=14,
    )
    assert d is not None and d.index == 0 and reason == 'configured_index'


def test_apply_env_override_helper(monkeypatch):
    env = Environment()
    monkeypatch.setenv('PIBOY_UI_SOUND_DEVICE_INDEX', '0')
    assert apply_ui_sound_env_overrides(env) == 'env'
    assert env.audio.ui_sounds.output_device_index == 0
