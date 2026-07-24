import logging
import time
from datetime import datetime
from logging.config import fileConfig
from typing import Any, Callable, Generator, Self

from injector import Injector, Module, provider, singleton
from PIL import Image, ImageDraw

import environment
from app.AccessApp import AccessApp
from app.App import App
from app.DevicesApp import DevicesApp
from app.EventLogApp import EventLogApp
from app.IntercomApp import IntercomApp
from app.SensorsApp import SensorsApp
from app.SystemApp import SystemApp
from app.ui_kit import fit_text, make_hit
from backend.simulator import SimulatorBackend
from environment import AppConfig, BackendMode, Environment, force_simulator
from interaction.Display import Display
from interaction.Input import Input
from interaction.UnifiedInteraction import UnifiedInteraction
from interaction.touch.events import HitTarget, Rect, TouchEvent, hit_test
from interaction.touch.source import NullTouchSource, TouchSource
from ports.intercom import CallPhase
from ports.lock import LockState
from ports.status import LinkStatus
from services.event_log import EventLogService
from services.terminal import AccessService, DeviceService, IntercomService, SensorService, SystemService

fileConfig(fname='config.ini')
logger = logging.getLogger(__name__)


class AppState:

    __bit = 0

    def __init__(self, e: Environment,
                 intercom: IntercomService,
                 access: AccessService,
                 sensors: SensorService,
                 system: SystemService):
        self.__environment = e
        self.__intercom = intercom
        self.__access = access
        self.__sensors = sensors
        self.__system = system
        self.__image_buffer = self.__init_buffer()
        self.__apps: list[App] = []
        self.__active_app = 0
        self.__tab_hits: list[HitTarget] = []
        self.__footer_rect: Rect | None = None
        self.__display: Display | None = None
        self.__touch_source: TouchSource = NullTouchSource()

    def bind_display(self, display: Display) -> None:
        self.__display = display

    def bind_touch_source(self, source: TouchSource) -> None:
        self.__touch_source = source

    def stop_touch(self) -> None:
        self.__touch_source.stop()

    @property
    def touch_source(self) -> TouchSource:
        return self.__touch_source

    def set_footer_rect(self, rect: Rect) -> None:
        self.__footer_rect = rect

    def set_tab_hits(self, hits: list[HitTarget]) -> None:
        self.__tab_hits = hits

    def __init_buffer(self) -> Image.Image:
        return Image.new('RGB', self.__environment.app_config.resolution, self.__environment.app_config.background)

    def __tick(self):
        self.__bit ^= 1

    def clear_buffer(self) -> Image.Image:
        self.__image_buffer = self.__init_buffer()
        return self.__image_buffer

    def add_app(self, app: App) -> Self:
        self.__apps.append(app)
        return self

    @property
    def tick(self) -> int:
        return self.__bit

    @property
    def environment(self) -> Environment:
        return self.__environment

    @property
    def intercom(self) -> IntercomService:
        return self.__intercom

    @property
    def access(self) -> AccessService:
        return self.__access

    @property
    def sensors(self) -> SensorService:
        return self.__sensors

    @property
    def system(self) -> SystemService:
        return self.__system

    @property
    def image_buffer(self) -> Image.Image:
        return self.__image_buffer

    @property
    def apps(self) -> list[App]:
        return self.__apps

    @property
    def active_app(self) -> App:
        return self.__apps[self.__active_app]

    @property
    def active_app_index(self) -> int:
        return self.__active_app

    def next_app(self):
        self.__active_app += 1
        if not self.__active_app < len(self.__apps):
            self.__active_app = 0

    def previous_app(self):
        self.__active_app -= 1
        if self.__active_app < 0:
            self.__active_app = len(self.__apps) - 1

    def switch_to_app(self, index: int):
        if index < 0 or index >= len(self.__apps) or index == self.__active_app:
            return
        self.active_app.on_app_leave()
        self.__active_app = index
        self.active_app.on_app_enter()

    def app_content_origin(self) -> tuple[int, int]:
        cfg = self.__environment.app_config
        return cfg.app_side_offset, cfg.app_top_offset

    def on_touch_event(self, event: TouchEvent):
        """Handle a normalized screen-space tap (full 800×480)."""
        display = self.__display
        if display is None:
            return
        # Footer is non-interactive
        if self.__footer_rect is not None and self.__footer_rect.contains(event.x, event.y):
            return
        # Header tabs
        tab = hit_test(self.__tab_hits, event.x, event.y)
        if tab is not None and tab.action.startswith('tab:'):
            self.switch_to_app(int(tab.action.split(':', 1)[1]))
            self.update_display(display, partial=False)
            return
        # App content
        ox, oy = self.app_content_origin()
        cfg = self.__environment.app_config
        app_w, app_h = cfg.app_size
        local_x = event.x - ox
        local_y = event.y - oy
        if local_x < 0 or local_y < 0 or local_x >= app_w or local_y >= app_h:
            return
        if self.active_app.on_tap(local_x, local_y):
            self.update_display(display, partial=True)

    def on_digit_key(self, digit: str, display: Display):
        if self.active_app.on_digit(digit):
            self.update_display(display, partial=True)

    def on_backspace_key(self, display: Display):
        if self.active_app.on_backspace():
            self.update_display(display, partial=True)

    def on_clear_key(self, display: Display):
        # Delete / clear maps to B for AccessApp
        self.active_app.on_key_b()
        self.update_display(display, partial=True)

    def watch_function(self, display: Display):
        while True:
            now = datetime.now()
            time.sleep(1.0 - now.microsecond / 1000000.0)
            image, x0, y0 = draw_footer(self.image_buffer, self)
            display.show(image, x0, y0)
            self.__tick()

    def update_display(self, display: Display, partial=False):
        image = self.clear_buffer()
        app_bbox = (self.__environment.app_config.app_side_offset,
                    self.__environment.app_config.app_top_offset,
                    self.__environment.app_config.width - self.__environment.app_config.app_side_offset,
                    self.__environment.app_config.height - self.__environment.app_config.app_bottom_offset)
        x_offset, y_offset = app_bbox[0:2]
        if partial:
            for patch, x0, y0 in self.active_app.draw(image.crop(app_bbox), partial):
                display.show(patch, x0 + x_offset, y0 + y_offset)
        else:
            for patch, x0, y0 in draw_base(image, self):
                display.show(patch, x0, y0)
            for patch, x0, y0 in self.active_app.draw(image.crop(app_bbox), partial):
                image.paste(patch, (x0 + x_offset, y0 + y_offset))
            display.show(image.crop(app_bbox), x_offset, y_offset)

    def on_key_left(self, display: Display):
        self.active_app.on_key_left()
        self.update_display(display, partial=True)

    def on_key_right(self, display: Display):
        self.active_app.on_key_right()
        self.update_display(display, partial=True)

    def on_key_up(self, display: Display):
        self.active_app.on_key_up()
        self.update_display(display, partial=True)

    def on_key_down(self, display: Display):
        self.active_app.on_key_down()
        self.update_display(display, partial=True)

    def on_key_a(self, display: Display):
        self.active_app.on_key_a()
        self.update_display(display, partial=True)

    def on_key_b(self, display: Display):
        self.active_app.on_key_b()
        self.update_display(display, partial=True)

    def on_rotary_increase(self, display: Display):
        self.active_app.on_app_leave()
        self.next_app()
        self.active_app.on_app_enter()
        self.update_display(display, partial=False)

    def on_rotary_decrease(self, display: Display):
        self.active_app.on_app_leave()
        self.previous_app()
        self.active_app.on_app_enter()
        self.update_display(display, partial=False)


class AppModule(Module):
    """DI module. Dev entry forces simulator; production respects Environment.backend."""

    __unified_instance: UnifiedInteraction | None = None
    __force_simulator: bool = False

    def register_external_tk_interaction(self, tk_instance: UnifiedInteraction):
        self.__unified_instance = tk_instance

    def set_force_simulator(self, value: bool = True):
        self.__force_simulator = value

    @staticmethod
    def __create_tk_interaction(state: AppState, app_config: AppConfig) -> UnifiedInteraction:
        try:
            from interaction.TkInteraction import TkInteraction
            return TkInteraction(state.on_key_left, state.on_key_right, state.on_key_up, state.on_key_down,
                                 state.on_key_a, state.on_key_b, state.on_rotary_increase, state.on_rotary_decrease,
                                 lambda _: None, app_config.resolution, app_config.background, app_config.accent_dark)
        except Exception as exc:  # noqa: BLE001 — headless / missing _tkinter
            logger.warning('Tk UI unavailable (%s); using NullInteraction', exc)
            from interaction.NullInteraction import NullInteraction
            return NullInteraction(app_config.resolution, app_config.background)

    @singleton
    @provider
    def provide_environment(self) -> Environment:
        environment.configure()
        try:
            env = environment.load()
        except FileNotFoundError:
            env = Environment()
            environment.save(env)
        if self.__force_simulator:
            force_simulator(env)
        # Ensure resolution defaults for shelter terminal if missing from old configs
        if env.app_config.width < 800 or env.app_config.height < 480:
            env.app_config.width = 800
            env.app_config.height = 480
        return env

    @singleton
    @provider
    def provide_app_config(self, e: Environment) -> AppConfig:
        return e.app_config

    @singleton
    @provider
    def provide_event_log(self, e: Environment) -> EventLogService:
        return EventLogService(e.simulator.event_log_limit)

    @singleton
    @provider
    def provide_simulator_backend(self, e: Environment, event_log: EventLogService) -> SimulatorBackend:
        thresholds = e.sensor_thresholds
        return SimulatorBackend(
            event_log=event_log,
            resolution=e.app_config.resolution,
            lock_pulse_ms=e.simulator.lock_pulse_ms,
            temp_min=thresholds.temperature_min,
            temp_max=thresholds.temperature_max,
            humidity_min=thresholds.humidity_min,
            humidity_max=thresholds.humidity_max,
            connect_delay_s=e.simulator.connect_delay_s,
        )

    @singleton
    @provider
    def provide_intercom_service(self, backend: SimulatorBackend) -> IntercomService:
        return IntercomService(backend)

    @singleton
    @provider
    def provide_access_service(self, backend: SimulatorBackend, event_log: EventLogService,
                               e: Environment) -> AccessService:
        return AccessService(backend, backend, event_log, e.simulator.lock_pulse_ms)

    @singleton
    @provider
    def provide_device_service(self, backend: SimulatorBackend) -> DeviceService:
        return DeviceService(backend)

    @singleton
    @provider
    def provide_sensor_service(self, backend: SimulatorBackend) -> SensorService:
        return SensorService(backend)

    @singleton
    @provider
    def provide_system_service(self, backend: SimulatorBackend, event_log: EventLogService) -> SystemService:
        return SystemService(backend, event_log)

    @singleton
    @provider
    def provide_app_state(self, e: Environment, intercom: IntercomService, access: AccessService,
                          sensors: SensorService, system: SystemService) -> AppState:
        return AppState(e, intercom, access, sensors, system)

    @singleton
    @provider
    def provide_draw_callback(self, state: AppState, display: Display) -> Callable[[bool], None]:
        return lambda partial: state.update_display(display, partial)

    @singleton
    @provider
    def provide_display(self, e: Environment, state: AppState) -> Display:
        if e.use_simulator or self.__force_simulator:
            if self.__unified_instance is None:
                self.__unified_instance = self.__create_tk_interaction(state, e.app_config)
            return self.__unified_instance
        if e.backend_mode == BackendMode.RASPBERRY:
            from interaction.ILI9486Display import ILI9486Display
            spi_device_config = e.display_config.display_device
            return ILI9486Display((spi_device_config.bus, spi_device_config.device),
                                  e.display_config.dc_pin, e.display_config.rst_pin, e.display_config.flip_display)
        if self.__unified_instance is None:
            self.__unified_instance = self.__create_tk_interaction(state, e.app_config)
        return self.__unified_instance

    @singleton
    @provider
    def provide_input(self, e: Environment, state: AppState, display: Display) -> Input:
        if e.use_simulator or self.__force_simulator:
            if self.__unified_instance is None:
                self.__unified_instance = self.__create_tk_interaction(state, e.app_config)
            return self.__unified_instance
        if e.backend_mode == BackendMode.RASPBERRY:
            from interaction.GPIOInput import GPIOInput
            from interaction.ILI9486Display import ILI9486Display

            def reset_and_init():
                if isinstance(display, ILI9486Display):
                    display.reset()
                display.show(state.clear_buffer(), 0, 0)

            return GPIOInput(e.keypad_config.left_pin, e.keypad_config.right_pin,
                             e.keypad_config.up_pin, e.keypad_config.down_pin,
                             e.keypad_config.a_pin, e.keypad_config.b_pin,
                             e.rotary_config.rotary_device, e.rotary_config.sw_pin,
                             lambda: state.on_key_left(display), lambda: state.on_key_right(display),
                             lambda: state.on_key_up(display), lambda: state.on_key_down(display),
                             lambda: state.on_key_a(display), lambda: state.on_key_b(display),
                             lambda: state.on_rotary_increase(display), lambda: state.on_rotary_decrease(display),
                             reset_and_init)
        if self.__unified_instance is None:
            self.__unified_instance = self.__create_tk_interaction(state, e.app_config)
        return self.__unified_instance


def draw_footer(image: Image.Image, state: AppState) -> tuple[Image.Image, int, int]:
    width, height = state.environment.app_config.resolution
    layout = state.environment.app_config.layout
    footer_height = layout.footer_height
    footer_bottom_offset = 4
    footer_side_offset = state.environment.app_config.app_side_offset
    font = state.environment.app_config.font_header
    draw = ImageDraw.Draw(image)
    accent = state.environment.app_config.accent
    dark = state.environment.app_config.accent_dark
    background = state.environment.app_config.background

    start = (footer_side_offset, height - footer_height - footer_bottom_offset)
    end = (width - footer_side_offset - 1, height - footer_bottom_offset - 1)
    state.set_footer_rect(Rect(start[0], start[1], end[0], end[1]))
    draw.rectangle(start + end, fill=dark)

    status = state.system.status()
    session = state.intercom.session()
    lock = state.access.lock_state()
    reading = state.sensors.reading()

    net = status.network.value
    if status.network == LinkStatus.OFFLINE:
        net = 'нет' if state.tick else 'НЕТ'

    call = {
        CallPhase.IDLE: 'свз:—',
        CallPhase.CALLING: 'свз:вызов',
        CallPhase.RINGING: 'свз:вход',
        CallPhase.CONNECTING: 'свз:соед',
        CallPhase.CONNECTED: 'свз:разг',
        CallPhase.ENDED: 'свз:конец',
    }.get(session.phase, 'свз:?')

    lock_txt = 'замок:имп' if lock == LockState.PULSING else 'замок:ok'
    warn = '!' if reading.warning else ''
    time_str = datetime.now().strftime('%H:%M:%S')
    line = f'{time_str}  {status.backend}  сеть:{net}  {call}  {lock_txt}{warn}'
    line = fit_text(font, line, end[0] - start[0] - 8)
    _, _, _, text_height = font.getbbox(line)
    text_padding = (footer_height - text_height) // 2
    draw.text((start[0] + 4, start[1] + text_padding), line, fill=accent, font=font)

    x0, y0 = start
    crop_end = end[0] + 1, end[1] + 1
    return image.crop(start + crop_end), x0, y0


def draw_header(image: Image.Image, state: AppState) -> tuple[Image.Image, int, int]:
    width, height = state.environment.app_config.resolution
    layout = state.environment.app_config.layout
    vertical_line = layout.header_vertical_line
    header_top_offset = state.environment.app_config.app_top_offset - vertical_line
    header_side_offset = state.environment.app_config.app_side_offset
    app_spacing = layout.app_spacing
    app_padding = layout.app_padding
    draw = ImageDraw.Draw(image)
    color_background = state.environment.app_config.background
    color_accent = state.environment.app_config.accent

    start = (header_side_offset, header_top_offset + vertical_line)
    end = (header_side_offset, header_top_offset)
    draw.line(start + end, fill=color_accent)
    start = end
    end = (width - header_side_offset - 1, header_top_offset)
    draw.line(start + end, fill=color_accent)
    start = end
    end = (width - header_side_offset - 1, header_top_offset + vertical_line)
    draw.line(start + end, fill=color_accent)

    font = state.environment.app_config.font_header
    max_text_width = width - (2 * header_side_offset)
    app_text_width = sum(int(font.getbbox(app.title)[2]) for app in state.apps) + (len(state.apps) - 1) * app_spacing
    cursor = header_side_offset + max(0, (max_text_width - app_text_width) // 2)
    tab_hits: list[HitTarget] = []
    for index, app in enumerate(state.apps):
        _, _, text_width, text_height = map(int, font.getbbox(app.title))
        text_top = header_top_offset - text_height - app_padding
        draw.text((cursor, text_top), app.title, color_accent, font=font)
        tab_rect = Rect(cursor - app_padding, 0,
                        cursor + text_width + app_padding,
                        header_top_offset + vertical_line)
        # Expand for touch comfort without overlapping neighbors too aggressively
        tab_hits.append(make_hit(tab_rect, f'tab:{index}', min_w=44, min_h=44))
        if app is state.active_app:
            start = (cursor - app_padding, header_top_offset - vertical_line)
            end = (cursor - app_padding, header_top_offset)
            draw.line(start + end, fill=color_accent)
            start = end
            end = (cursor + text_width + app_padding, header_top_offset)
            draw.line(start + end, fill=color_background)
            start = end
            end = (cursor + text_width + app_padding, header_top_offset - vertical_line)
            draw.line(start + end, fill=color_accent)
        cursor = cursor + text_width + app_spacing
    state.set_tab_hits(tab_hits)

    partial_start = (header_side_offset, 0)
    partial_end = (width - header_side_offset, header_top_offset + vertical_line)
    x0, y0 = partial_start
    return image.crop(partial_start + partial_end), x0, y0


def draw_base(image: Image.Image, state: AppState) -> Generator[tuple[Image.Image, int, int], Any, None]:
    yield draw_header(image, state)
    yield draw_footer(image, state)


def register_shelter_apps(injector: Injector, app_state: AppState) -> AppState:
    return (app_state
            .add_app(injector.get(IntercomApp))
            .add_app(injector.get(AccessApp))
            .add_app(injector.get(SensorsApp))
            .add_app(injector.get(DevicesApp))
            .add_app(injector.get(EventLogApp))
            .add_app(injector.get(SystemApp)))


if __name__ == '__main__':
    module = AppModule()
    # Production entry uses config backend; default Environment is simulator.
    injector = Injector([module])
    app_state = injector.get(AppState)
    env = injector.get(Environment)
    DISPLAY = injector.get(Display)
    INPUT = injector.get(Input)
    app_state.bind_display(DISPLAY)

    register_shelter_apps(injector, app_state)

    touch_source: TouchSource = NullTouchSource()
    if env.input.touch_enabled and not env.use_simulator:
        from interaction.touch.evdev_source import open_touch_source
        from interaction.touch.transform import TouchTransform
        touch_cfg = env.input.touch
        transform = TouchTransform(
            screen_width=env.app_config.width,
            screen_height=env.app_config.height,
            raw_x_min=touch_cfg.abs_x_min if touch_cfg.abs_x_min is not None else 0,
            raw_x_max=touch_cfg.abs_x_max if touch_cfg.abs_x_max is not None else 4095,
            raw_y_min=touch_cfg.abs_y_min if touch_cfg.abs_y_min is not None else 0,
            raw_y_max=touch_cfg.abs_y_max if touch_cfg.abs_y_max is not None else 4095,
            swap_axes=touch_cfg.swap_axes,
            invert_x=touch_cfg.invert_x,
            invert_y=touch_cfg.invert_y,
            rotation=touch_cfg.rotation,
        )

        def _on_touch(event: TouchEvent):
            app_state.on_touch_event(event)

        touch_source = open_touch_source(
            touch_cfg.device if touch_cfg.enabled else None,
            transform,
            touch_cfg.debounce_ms,
            _on_touch,
            enabled=touch_cfg.enabled,
        )
        if isinstance(touch_source, NullTouchSource):
            logger.warning('Touch unavailable (%s); keyboard fallback active', touch_source.reason)
    app_state.bind_touch_source(touch_source)

    DISPLAY.show(app_state.image_buffer, 0, 0)
    app_state.update_display(DISPLAY)
    app_state.active_app.on_app_enter()

    try:
        app_state.watch_function(DISPLAY)
    except KeyboardInterrupt:
        pass
    finally:
        app_state.stop_touch()
        DISPLAY.close()
        INPUT.close()
