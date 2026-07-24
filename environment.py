from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

import yaml
from PIL import ImageFont
from yaml import Dumper, FullLoader, Loader, MappingNode, Node, UnsafeLoader


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
    # legacy field kept for YAML compatibility; prefer `backend`
    dev_mode: bool = True

    __is_raspberry_pi: bool | None = None

    def __post_init__(self):
        if isinstance(self.sensor_thresholds, dict):
            self.sensor_thresholds = SensorThresholdConfig(**self.sensor_thresholds)
        if isinstance(self.simulator, dict):
            self.simulator = SimulatorConfig(**self.simulator)
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
