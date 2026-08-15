from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
import logging
import os

import yaml
from PIL import ImageFont
from yaml import Dumper, FullLoader, Loader, MappingNode, Node, UnsafeLoader

_log = logging.getLogger('piboy.config')


class BackendMode(str, Enum):
    SIMULATOR = 'simulator'
    RASPBERRY = 'raspberry'


# Preferred fonts with Cyrillic coverage (first existing wins).
_FONT_CANDIDATES = (
    'FreeSansBold.ttf',
    '/usr/share/fonts/truetype/freefont/FreeSansBold.ttf',
    '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',
    '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
    '/Library/Fonts/Arial Unicode.ttf',
    '/System/Library/Fonts/Supplemental/Arial Unicode.ttf',
    '/System/Library/Fonts/Supplemental/Arial.ttf',
)


def resolve_font_path(preferred: str | None = None) -> str:
    candidates = []
    if preferred:
        candidates.append(preferred)
    candidates.extend(_FONT_CANDIDATES)
    for path in candidates:
        if Path(path).is_file():
            return path
    # Last resort: Pillow default (may lack Cyrillic).
    return preferred or 'FreeSansBold.ttf'


@dataclass
class SPIConfig:
    bus: int
    device: int


@dataclass
class I2CConfig:
    port: int
    address: int


@dataclass
class SerialConfig:
    port: str
    baud_rate: int


@dataclass
class ColorConfig:
    background: tuple[int, int, int]
    accent: tuple[int, int, int]
    accent_dark: tuple[int, int, int]


@dataclass
class LayoutConfig:
    """Shared spacing / control sizes for 800×480 (and future) layouts."""
    gap: int = 12
    pad: int = 10
    line_height: int = 28
    button_min_height: int = 44
    button_min_width: int = 100
    list_row_height: int = 40
    footer_height: int = 28
    header_vertical_line: int = 5
    app_spacing: int = 24
    app_padding: int = 6


@dataclass
class SensorThresholdConfig:
    temperature_min: float = 10.0
    temperature_max: float = 35.0
    humidity_min: float = 0.20
    humidity_max: float = 0.80


@dataclass
class SimulatorConfig:
    """Demonstration-only simulator settings (not production secrets)."""
    lock_pulse_ms: int = 1500
    event_log_limit: int = 80
    connect_delay_s: float = 0.8


@dataclass
class TouchDeviceConfig:
    """Linux evdev touchscreen calibration (screen space is app_config resolution)."""
    device: str = '/dev/input/event0'
    width: int = 800
    height: int = 480
    abs_x_min: int | None = None
    abs_x_max: int | None = None
    abs_y_min: int | None = None
    abs_y_max: int | None = None
    swap_axes: bool = False
    invert_x: bool = False
    invert_y: bool = False
    rotation: int = 0
    debounce_ms: int = 40
    enabled: bool = True


@dataclass
class InputConfig:
    """
    mode:
      - keyboard — only keys / GPIO keypad
      - touch — touch only (still allows keyboard if present)
      - touch_keyboard — touch + keyboard (default)
    """
    mode: str = 'touch_keyboard'
    touch: TouchDeviceConfig = field(default_factory=TouchDeviceConfig)

    @property
    def touch_enabled(self) -> bool:
        return self.mode in ('touch', 'touch_keyboard') and self.touch.enabled

    @property
    def keyboard_enabled(self) -> bool:
        return self.mode in ('keyboard', 'touch_keyboard')


@dataclass
class CrtConfig:
    """Procedural CRT look. See docs/CRT.md. Default preset is subtle (glow off)."""
    enabled: bool | None = None
    preset: str = 'subtle'
    phosphor_floor: float | None = None
    scanlines: float | None = None
    vignette: float | None = None
    grain: float | None = None
    glare: float | None = None
    flicker: float | None = None
    glow: float | None = None
    rounded_corners: int | None = None
    bezel_inset: int | None = None
    curvature: float | None = None
    grain_fps: float | None = None
    grain_seed: int = 42


@dataclass
class UiSoundsConfig:
    """Short UI feedback beeps. See docs/UI_SOUNDS.md."""
    enabled: bool = True
    volume: float = 0.35
    clicks_during_call: bool = False
    min_interval_ms: int = 30
    output_device_index: int | None = None
    output_device_name: str | None = None
    boot_splash: bool = True
    audio_setup_done: bool = False


@dataclass
class AudioConfig:
    ui_sounds: UiSoundsConfig = field(default_factory=UiSoundsConfig)


@dataclass
class AppConfig:
    app_side_offset: int = 24
    app_top_offset: int = 40
    app_bottom_offset: int = 36
    font_name: str = 'FreeSansBold.ttf'
    font_header_size: int = 18
    font_standard_size: int = 16
    color_mode: int = 0
    width: int = 800
    height: int = 480
    modes: list[ColorConfig] = None
    layout: LayoutConfig = field(default_factory=LayoutConfig)
    # cached properties
    __font_header: ImageFont.FreeTypeFont | None = None
    __font_standard: ImageFont.FreeTypeFont | None = None
    __resolved_font: str | None = None

    def __post_init__(self):
        if self.modes is None:
            self.modes = [
                ColorConfig(
                    background=(0, 0, 0),
                    accent=(27, 251, 30),
                    accent_dark=(9, 64, 9)
                ),
                ColorConfig(
                    background=(0, 0, 0),
                    accent=(255, 245, 101),
                    accent_dark=(59, 45, 25)
                )
            ]
        if self.layout is None:
            self.layout = LayoutConfig()
        elif isinstance(self.layout, dict):
            self.layout = LayoutConfig(**self.layout)
        self.__resolved_font = resolve_font_path(self.font_name)

    @property
    def resolution(self) -> tuple[int, int]:
        return self.width, self.height

    @property
    def app_size(self) -> tuple[int, int]:
        return self.width - 2 * self.app_side_offset, self.height - self.app_top_offset - self.app_bottom_offset

    @property
    def font_path(self) -> str:
        if self.__resolved_font is None:
            self.__resolved_font = resolve_font_path(self.font_name)
        return self.__resolved_font

    @property
    def font_header(self) -> ImageFont.FreeTypeFont:
        if self.__font_header is None:
            self.__font_header = ImageFont.truetype(self.font_path, self.font_header_size)
        return self.__font_header

    @property
    def font_standard(self) -> ImageFont.FreeTypeFont:
        if self.__font_standard is None:
            self.__font_standard = ImageFont.truetype(self.font_path, self.font_standard_size)
        return self.__font_standard

    @property
    def background(self) -> tuple[int, int, int]:
        return self.modes[self.color_mode].background

    @property
    def accent(self) -> tuple[int, int, int]:
        return self.modes[self.color_mode].accent

    @property
    def accent_dark(self) -> tuple[int, int, int]:
        return self.modes[self.color_mode].accent_dark


@dataclass
class KeypadConfig:
    up_pin: int = 5
    down_pin: int = 6
    left_pin: int = 12
    right_pin: int = 13
    a_pin: int = 16
    b_pin: int = 26


@dataclass
class RotaryConfig:
    rotary_device: str = '/dev/input/event0'
    clk_pin: int = 22
    dt_pin: int = 23
    sw_pin: int = 27


@dataclass
class DisplayConfig:
    rst_pin: int = 25
    dc_pin: int = 24
    display_device: SPIConfig = field(default_factory=lambda: SPIConfig(0, 0))
    flip_display: bool = False
    cs_pin: int = 7
    irq_pin: int = 17
    touch_device: SPIConfig = field(default_factory=lambda: SPIConfig(0, 1))
    # auto | framebuffer | ili9486 — auto prefers /dev/fb0 when size matches app
    driver: str = 'auto'
    framebuffer_device: str = '/dev/fb0'


@dataclass
class Environment:
    backend: str = BackendMode.SIMULATOR.value
    env_sensor_config: I2CConfig = field(default_factory=lambda: I2CConfig(1, 0x76))
    adc_config: I2CConfig = field(default_factory=lambda: I2CConfig(1, 0x48))
    gps_module_config: SerialConfig = field(default_factory=lambda: SerialConfig('/dev/serial0', 9600))
    app_config: AppConfig = field(default_factory=lambda: AppConfig())
    keypad_config: KeypadConfig = field(default_factory=lambda: KeypadConfig())
    rotary_config: RotaryConfig = field(default_factory=lambda: RotaryConfig())
    display_config: DisplayConfig = field(default_factory=lambda: DisplayConfig())
    sensor_thresholds: SensorThresholdConfig = field(default_factory=SensorThresholdConfig)
    simulator: SimulatorConfig = field(default_factory=SimulatorConfig)
    input: InputConfig = field(default_factory=InputConfig)
    crt: CrtConfig = field(default_factory=CrtConfig)
    audio: AudioConfig = field(default_factory=AudioConfig)
    # legacy field kept for YAML compatibility; prefer `backend`
    dev_mode: bool = True

    __is_raspberry_pi: bool | None = None

    def __post_init__(self):
        if isinstance(self.sensor_thresholds, dict):
            self.sensor_thresholds = SensorThresholdConfig(**self.sensor_thresholds)
        if isinstance(self.simulator, dict):
            self.simulator = SimulatorConfig(**self.simulator)
        if isinstance(self.input, dict):
            touch = self.input.get('touch')
            if isinstance(touch, dict):
                self.input = InputConfig(mode=self.input.get('mode', 'touch_keyboard'),
                                         touch=TouchDeviceConfig(**touch))
            else:
                self.input = InputConfig(**self.input)
        if isinstance(self.crt, dict):
            self.crt = CrtConfig(**self.crt)
        if isinstance(self.audio, dict):
            ui = self.audio.get('ui_sounds', self.audio)
            if isinstance(ui, dict):
                self.audio = AudioConfig(ui_sounds=UiSoundsConfig(**ui))
            else:
                self.audio = AudioConfig(ui_sounds=ui if isinstance(ui, UiSoundsConfig) else UiSoundsConfig())
        if self.app_config is not None and isinstance(self.app_config, dict):
            self.app_config = AppConfig(**self.app_config)

    @property
    def backend_mode(self) -> BackendMode:
        try:
            return BackendMode(self.backend)
        except ValueError:
            return BackendMode.SIMULATOR

    @property
    def use_simulator(self) -> bool:
        return self.backend_mode == BackendMode.SIMULATOR

    @property
    def is_raspberry_pi(self) -> bool:
        """Hardware probe only — do not use alone to choose backend."""
        if self.__is_raspberry_pi is None:
            try:
                with open('/sys/firmware/devicetree/base/model', 'r') as model_info:
                    self.__is_raspberry_pi = 'Raspberry Pi' in model_info.read()
            except FileNotFoundError:
                self.__is_raspberry_pi = False
        return self.__is_raspberry_pi


def _public_vars(data) -> dict:
    return {k: v for k, v in vars(data).items() if not k.startswith('_')}


def spi_config_constructor(loader: Loader | FullLoader | UnsafeLoader, node: Node) -> SPIConfig:
    if isinstance(node, MappingNode):
        return SPIConfig(**loader.construct_mapping(node))
    raise TypeError("node is not of type MappingNode")


def spi_config_representor(dumper: Dumper, data: SPIConfig) -> MappingNode:
    return dumper.represent_mapping('!SPIConfig', _public_vars(data))


def i2c_config_constructor(loader: Loader | FullLoader | UnsafeLoader, node: Node) -> I2CConfig:
    if isinstance(node, MappingNode):
        return I2CConfig(**loader.construct_mapping(node))
    raise TypeError("node is not of type MappingNode")


def i2c_config_representor(dumper: Dumper, data: I2CConfig) -> MappingNode:
    return dumper.represent_mapping('!I2CConfig', _public_vars(data))


def serial_config_constructor(loader: Loader | FullLoader | UnsafeLoader, node: Node) -> SerialConfig:
    if isinstance(node, MappingNode):
        return SerialConfig(**loader.construct_mapping(node))
    raise TypeError("node if not of type MappingNode")


def serial_config_representor(dumper: Dumper, data: SerialConfig) -> MappingNode:
    return dumper.represent_mapping('!SerialConfig', _public_vars(data))


def color_config_constructor(loader: Loader | FullLoader | UnsafeLoader, node: Node) -> ColorConfig:
    if isinstance(node, MappingNode):
        return ColorConfig(**loader.construct_mapping(node))
    raise TypeError("node is not of type MappingNode")


def color_config_representor(dumper: Dumper, data: ColorConfig) -> MappingNode:
    return dumper.represent_mapping('!ColorConfig', _public_vars(data))


def layout_config_constructor(loader: Loader | FullLoader | UnsafeLoader, node: Node) -> LayoutConfig:
    if isinstance(node, MappingNode):
        return LayoutConfig(**loader.construct_mapping(node))
    raise TypeError("node is not of type MappingNode")


def layout_config_representor(dumper: Dumper, data: LayoutConfig) -> MappingNode:
    return dumper.represent_mapping('!LayoutConfig', _public_vars(data))


def sensor_threshold_constructor(loader: Loader | FullLoader | UnsafeLoader, node: Node) -> SensorThresholdConfig:
    if isinstance(node, MappingNode):
        return SensorThresholdConfig(**loader.construct_mapping(node))
    raise TypeError("node is not of type MappingNode")


def sensor_threshold_representor(dumper: Dumper, data: SensorThresholdConfig) -> MappingNode:
    return dumper.represent_mapping('!SensorThresholdConfig', _public_vars(data))


def simulator_config_constructor(loader: Loader | FullLoader | UnsafeLoader, node: Node) -> SimulatorConfig:
    if isinstance(node, MappingNode):
        return SimulatorConfig(**loader.construct_mapping(node))
    raise TypeError("node is not of type MappingNode")


def simulator_config_representor(dumper: Dumper, data: SimulatorConfig) -> MappingNode:
    return dumper.represent_mapping('!SimulatorConfig', _public_vars(data))


def touch_device_constructor(loader: Loader | FullLoader | UnsafeLoader, node: Node) -> TouchDeviceConfig:
    if isinstance(node, MappingNode):
        return TouchDeviceConfig(**loader.construct_mapping(node))
    raise TypeError("node is not of type MappingNode")


def touch_device_representor(dumper: Dumper, data: TouchDeviceConfig) -> MappingNode:
    return dumper.represent_mapping('!TouchDeviceConfig', _public_vars(data))


def input_config_constructor(loader: Loader | FullLoader | UnsafeLoader, node: Node) -> InputConfig:
    if isinstance(node, MappingNode):
        values = loader.construct_mapping(node)
        touch = values.get('touch')
        if isinstance(touch, dict):
            values['touch'] = TouchDeviceConfig(**touch)
        return InputConfig(**values)
    raise TypeError("node is not of type MappingNode")


def input_config_representor(dumper: Dumper, data: InputConfig) -> MappingNode:
    return dumper.represent_mapping('!InputConfig', _public_vars(data))


def crt_config_constructor(loader: Loader | FullLoader | UnsafeLoader, node: Node) -> CrtConfig:
    if isinstance(node, MappingNode):
        return CrtConfig(**loader.construct_mapping(node))
    raise TypeError("node is not of type MappingNode")


def crt_config_representor(dumper: Dumper, data: CrtConfig) -> MappingNode:
    return dumper.represent_mapping('!CrtConfig', _public_vars(data))


def ui_sounds_config_constructor(loader: Loader | FullLoader | UnsafeLoader, node: Node) -> UiSoundsConfig:
    if isinstance(node, MappingNode):
        return UiSoundsConfig(**loader.construct_mapping(node))
    raise TypeError("node is not of type MappingNode")


def ui_sounds_config_representor(dumper: Dumper, data: UiSoundsConfig) -> MappingNode:
    return dumper.represent_mapping('!UiSoundsConfig', _public_vars(data))


def audio_config_constructor(loader: Loader | FullLoader | UnsafeLoader, node: Node) -> AudioConfig:
    if isinstance(node, MappingNode):
        values = loader.construct_mapping(node)
        ui = values.get('ui_sounds')
        if isinstance(ui, dict):
            values['ui_sounds'] = UiSoundsConfig(**ui)
        return AudioConfig(**values)
    raise TypeError("node is not of type MappingNode")


def audio_config_representor(dumper: Dumper, data: AudioConfig) -> MappingNode:
    return dumper.represent_mapping('!AudioConfig', _public_vars(data))


def app_config_constructor(loader: Loader | FullLoader | UnsafeLoader, node: Node) -> AppConfig:
    if isinstance(node, MappingNode):
        values = loader.construct_mapping(node)
        return AppConfig(**values)
    raise TypeError("node is not of type MappingNode")


def app_config_representor(dumper: Dumper, data: AppConfig) -> MappingNode:
    return dumper.represent_mapping('!AppConfig', _public_vars(data))


def keypad_config_constructor(loader: Loader | FullLoader | UnsafeLoader, node: Node) -> KeypadConfig:
    if isinstance(node, MappingNode):
        return KeypadConfig(**loader.construct_mapping(node))
    raise TypeError("node is not of type MappingNode")


def keypad_config_representor(dumper: Dumper, data: KeypadConfig) -> MappingNode:
    return dumper.represent_mapping('!KeypadConfig', _public_vars(data))


def rotary_config_constructor(loader: Loader | FullLoader | UnsafeLoader, node: Node) -> RotaryConfig:
    if isinstance(node, MappingNode):
        return RotaryConfig(**loader.construct_mapping(node))
    raise TypeError("node is not of type MappingNode")


def rotary_config_representor(dumper: Dumper, data: RotaryConfig) -> MappingNode:
    return dumper.represent_mapping('!RotaryConfig', _public_vars(data))


def display_config_constructor(loader: Loader | FullLoader | UnsafeLoader, node: Node) -> DisplayConfig:
    if isinstance(node, MappingNode):
        return DisplayConfig(**loader.construct_mapping(node))
    raise TypeError("node is not of type MappingNode")


def display_config_representor(dumper: Dumper, data: DisplayConfig) -> MappingNode:
    return dumper.represent_mapping('!DisplayConfig', _public_vars(data))


def environment_constructor(loader: Loader | FullLoader | UnsafeLoader, node: Node) -> Environment:
    if isinstance(node, MappingNode):
        return Environment(**loader.construct_mapping(node))
    raise TypeError("node is not of type MappingNode")


def environment_representor(dumper: Dumper, data: Environment) -> MappingNode:
    return dumper.represent_mapping('!Environment', _public_vars(data))


def configure():
    yaml.add_constructor('!SPIConfig', spi_config_constructor)
    yaml.add_constructor('!I2CConfig', i2c_config_constructor)
    yaml.add_constructor('!SerialConfig', serial_config_constructor)
    yaml.add_constructor('!ColorConfig', color_config_constructor)
    yaml.add_constructor('!LayoutConfig', layout_config_constructor)
    yaml.add_constructor('!SensorThresholdConfig', sensor_threshold_constructor)
    yaml.add_constructor('!SimulatorConfig', simulator_config_constructor)
    yaml.add_constructor('!TouchDeviceConfig', touch_device_constructor)
    yaml.add_constructor('!InputConfig', input_config_constructor)
    yaml.add_constructor('!CrtConfig', crt_config_constructor)
    yaml.add_constructor('!UiSoundsConfig', ui_sounds_config_constructor)
    yaml.add_constructor('!AudioConfig', audio_config_constructor)
    yaml.add_constructor('!AppConfig', app_config_constructor)
    yaml.add_constructor('!KeypadConfig', keypad_config_constructor)
    yaml.add_constructor('!RotaryConfig', rotary_config_constructor)
    yaml.add_constructor('!DisplayConfig', display_config_constructor)
    yaml.add_constructor('!Environment', environment_constructor)
    yaml.add_representer(SPIConfig, spi_config_representor)
    yaml.add_representer(I2CConfig, i2c_config_representor)
    yaml.add_representer(SerialConfig, serial_config_representor)
    yaml.add_representer(ColorConfig, color_config_representor)
    yaml.add_representer(LayoutConfig, layout_config_representor)
    yaml.add_representer(SensorThresholdConfig, sensor_threshold_representor)
    yaml.add_representer(SimulatorConfig, simulator_config_representor)
    yaml.add_representer(TouchDeviceConfig, touch_device_representor)
    yaml.add_representer(InputConfig, input_config_representor)
    yaml.add_representer(CrtConfig, crt_config_representor)
    yaml.add_representer(UiSoundsConfig, ui_sounds_config_representor)
    yaml.add_representer(AudioConfig, audio_config_representor)
    yaml.add_representer(AppConfig, app_config_representor)
    yaml.add_representer(KeypadConfig, keypad_config_representor)
    yaml.add_representer(RotaryConfig, rotary_config_representor)
    yaml.add_representer(DisplayConfig, display_config_representor)
    yaml.add_representer(Environment, environment_representor)


def load(file_name: str = 'config.yaml') -> Environment:
    with open(file_name, 'r') as file:
        return yaml.load(file, FullLoader)


def save(environment: Environment, file_name: str = 'config.yaml'):
    with open(file_name, 'w') as file:
        yaml.dump(environment, file, sort_keys=False)


def force_simulator(environment: Environment) -> Environment:
    """Dev entrypoints always run with simulator backend."""
    environment.backend = BackendMode.SIMULATOR.value
    environment.dev_mode = True
    return environment


@dataclass
class RuntimeConfigInfo:
    """Non-persisted info about how Environment / UI sound device were resolved."""
    paths: list[str] = field(default_factory=list)
    ui_sound_device_source: str = 'auto'  # config | env | auto


# Process-wide last load metadata (not written to YAML).
RUNTIME = RuntimeConfigInfo()


def _merge_ui_sounds(dst: UiSoundsConfig, src: UiSoundsConfig) -> None:
    """Overlay non-default-ish fields from src onto dst (explicit local overrides)."""
    dst.enabled = src.enabled
    dst.volume = src.volume
    dst.clicks_during_call = src.clicks_during_call
    dst.min_interval_ms = src.min_interval_ms
    dst.boot_splash = src.boot_splash
    dst.audio_setup_done = src.audio_setup_done
    if src.output_device_index is not None:
        dst.output_device_index = src.output_device_index
    if src.output_device_name:
        dst.output_device_name = src.output_device_name


def _apply_local_yaml(env: Environment, local_path: str) -> None:
    """Apply config.local.yaml — full Environment, AudioConfig, or shorthand keys."""
    with open(local_path, 'r') as file:
        data = yaml.load(file, FullLoader)
    if data is None:
        return
    if isinstance(data, Environment):
        _merge_ui_sounds(env.audio.ui_sounds, data.audio.ui_sounds)
        return
    if isinstance(data, AudioConfig):
        _merge_ui_sounds(env.audio.ui_sounds, data.ui_sounds)
        return
    if isinstance(data, UiSoundsConfig):
        _merge_ui_sounds(env.audio.ui_sounds, data)
        return
    if isinstance(data, dict):
        # Shorthand: output_device_index / output_device_name at top level
        if 'output_device_index' in data and data['output_device_index'] is not None:
            env.audio.ui_sounds.output_device_index = int(data['output_device_index'])
        if data.get('output_device_name'):
            env.audio.ui_sounds.output_device_name = str(data['output_device_name'])
        audio = data.get('audio')
        if isinstance(audio, AudioConfig):
            _merge_ui_sounds(env.audio.ui_sounds, audio.ui_sounds)
        elif isinstance(audio, dict):
            ui = audio.get('ui_sounds', audio)
            if isinstance(ui, UiSoundsConfig):
                _merge_ui_sounds(env.audio.ui_sounds, ui)
            elif isinstance(ui, dict):
                if 'enabled' in ui:
                    env.audio.ui_sounds.enabled = bool(ui['enabled'])
                if 'volume' in ui:
                    env.audio.ui_sounds.volume = float(ui['volume'])
                if 'clicks_during_call' in ui:
                    env.audio.ui_sounds.clicks_during_call = bool(ui['clicks_during_call'])
                if 'min_interval_ms' in ui:
                    env.audio.ui_sounds.min_interval_ms = int(ui['min_interval_ms'])
                if 'boot_splash' in ui:
                    env.audio.ui_sounds.boot_splash = bool(ui['boot_splash'])
                if 'audio_setup_done' in ui:
                    env.audio.ui_sounds.audio_setup_done = bool(ui['audio_setup_done'])
                if ui.get('output_device_index') is not None:
                    env.audio.ui_sounds.output_device_index = int(ui['output_device_index'])
                if ui.get('output_device_name'):
                    env.audio.ui_sounds.output_device_name = str(ui['output_device_name'])
        if 'audio_setup_done' in data:
            env.audio.ui_sounds.audio_setup_done = bool(data['audio_setup_done'])


def apply_ui_sound_env_overrides(env: Environment) -> str | None:
    """
    Apply PIBOY_UI_SOUND_DEVICE_INDEX / PIBOY_UI_SOUND_DEVICE_NAME.
    Returns 'env' if either override was applied, else None.
    """
    applied = False
    raw_idx = os.environ.get('PIBOY_UI_SOUND_DEVICE_INDEX')
    if raw_idx is not None and str(raw_idx).strip() != '':
        env.audio.ui_sounds.output_device_index = int(raw_idx)
        applied = True
    raw_name = os.environ.get('PIBOY_UI_SOUND_DEVICE_NAME')
    if raw_name is not None and str(raw_name).strip() != '':
        env.audio.ui_sounds.output_device_name = str(raw_name).strip()
        applied = True
    return 'env' if applied else None


def resolve_ui_sound_device_source(env: Environment, env_override: str | None) -> str:
    if env_override == 'env':
        return 'env'
    ui = env.audio.ui_sounds
    if ui.output_device_index is not None or (ui.output_device_name and str(ui.output_device_name).strip()):
        return 'config'
    return 'auto'


def load_runtime_environment(
    config_path: str = 'config.yaml',
    local_path: str = 'config.local.yaml',
    *,
    create_if_missing: bool = True,
) -> Environment:
    """
    Load application YAML config (not logging config.ini).

    Order:
      1. config.yaml if present, else defaults (+ optional save)
      2. config.local.yaml overlay if present (gitignored)
      3. PIBOY_UI_SOUND_DEVICE_* environment variables (highest priority for device)
    """
    configure()
    RUNTIME.paths = []
    if os.path.isfile(config_path):
        env = load(config_path)
        RUNTIME.paths.append(os.path.abspath(config_path))
    else:
        env = Environment()
        if create_if_missing:
            save(env, config_path)
            RUNTIME.paths.append(os.path.abspath(config_path) + ' (created)')
        else:
            RUNTIME.paths.append('(defaults)')

    if os.path.isfile(local_path):
        _apply_local_yaml(env, local_path)
        RUNTIME.paths.append(os.path.abspath(local_path))

    env_override = apply_ui_sound_env_overrides(env)
    RUNTIME.ui_sound_device_source = resolve_ui_sound_device_source(env, env_override)

    _log.info(
        'Loaded config paths: %s',
        ', '.join(RUNTIME.paths) if RUNTIME.paths else '(none)',
    )
    _log.info(
        'UI sound device source=%s index=%s name=%s',
        RUNTIME.ui_sound_device_source,
        env.audio.ui_sounds.output_device_index,
        env.audio.ui_sounds.output_device_name,
    )
    return env


def save_ui_sound_local(
    *,
    index: int | None = None,
    name: str | None = None,
    setup_done: bool = True,
    clear_index: bool = False,
    local_path: str = 'config.local.yaml',
    env: Environment | None = None,
) -> None:
    """
    Persist UI sound device choice into config.local.yaml (gitignored).

    Updates in-memory ``env.audio.ui_sounds`` when ``env`` is provided.
    """
    configure()
    data: dict = {}
    if os.path.isfile(local_path):
        try:
            with open(local_path, 'r') as f:
                loaded = yaml.load(f, FullLoader)
            if isinstance(loaded, dict):
                data = dict(loaded)
            elif isinstance(loaded, UiSoundsConfig):
                data = {
                    'output_device_index': loaded.output_device_index,
                    'output_device_name': loaded.output_device_name,
                    'audio_setup_done': loaded.audio_setup_done,
                }
            elif isinstance(loaded, AudioConfig):
                ui = loaded.ui_sounds
                data = {
                    'output_device_index': ui.output_device_index,
                    'output_device_name': ui.output_device_name,
                    'audio_setup_done': ui.audio_setup_done,
                }
            elif isinstance(loaded, Environment):
                ui = loaded.audio.ui_sounds
                data = {
                    'output_device_index': ui.output_device_index,
                    'output_device_name': ui.output_device_name,
                    'audio_setup_done': ui.audio_setup_done,
                }
        except Exception as exc:  # noqa: BLE001
            _log.warning('Could not read %s (%s); rewriting', local_path, exc)
            data = {}

    if clear_index:
        data.pop('output_device_index', None)
        data['output_device_index'] = None
    elif index is not None:
        data['output_device_index'] = int(index)
    if name is not None:
        data['output_device_name'] = str(name) if name else None
    data['audio_setup_done'] = bool(setup_done)

    # Keep a compact shorthand file for machine-local overrides.
    out = {
        'output_device_index': data.get('output_device_index'),
        'output_device_name': data.get('output_device_name'),
        'audio_setup_done': data.get('audio_setup_done', True),
    }
    with open(local_path, 'w') as f:
        yaml.dump(out, f, default_flow_style=False, allow_unicode=True)

    if env is not None:
        ui = env.audio.ui_sounds
        if clear_index:
            ui.output_device_index = None
        elif index is not None:
            ui.output_device_index = int(index)
        if name is not None:
            ui.output_device_name = str(name) if name else None
        ui.audio_setup_done = bool(setup_done)
        RUNTIME.ui_sound_device_source = resolve_ui_sound_device_source(env, None)

    _log.info(
        'Saved UI sound local device index=%s name=%s setup_done=%s → %s',
        out.get('output_device_index'), out.get('output_device_name'),
        out.get('audio_setup_done'), os.path.abspath(local_path),
    )
