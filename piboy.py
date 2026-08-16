import logging
import os
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
from app.audio_setup import AudioSetupSession
from app.boot_sequence import BootSequence
from app.ui_kit import fit_text, make_hit
from backend.simulator import SimulatorBackend
from environment import AppConfig, BackendMode, Environment, force_simulator
import environment
from interaction.Display import Display
from interaction.Input import Input
from interaction.UnifiedInteraction import UnifiedInteraction
from interaction.touch.events import HitTarget, Rect, TouchEvent, hit_test
from interaction.touch.source import NullTouchSource, TouchSource
from ports.intercom import CallPhase
from ports.lock import LockState
from ports.status import LinkStatus
from interaction.frame_presenter import RenderGate
from rendering.crt import CRTRenderer, resolve_crt_settings
from services.event_log import EventLogService
from services.terminal import AccessService, DeviceService, IntercomService, SensorService, SystemService
from services.ui_sound import UiSoundService, UiSoundSettings, open_ui_sound_port

fileConfig(fname='config.ini')
logger = logging.getLogger(__name__)


class AppState:

    __bit = 0

    def __init__(self, e: Environment,
                 intercom: IntercomService,
                 access: AccessService,
                 sensors: SensorService,
                 system: SystemService,
                 sounds: UiSoundService):
        self.__environment = e
        self.__intercom = intercom
        self.__access = access
        self.__sensors = sensors
        self.__system = system
        self.__sounds = sounds
        self.__image_buffer = self.__init_buffer()
        self.__apps: list[App] = []
        self.__active_app = 0
        self.__tab_hits: list[HitTarget] = []
        self.__footer_rect: Rect | None = None
        self.__display: Display | None = None
        self.__touch_source: TouchSource = NullTouchSource()
        crt_cfg = e.crt
        self.__crt = CRTRenderer(resolve_crt_settings(
            preset=crt_cfg.preset,
            enabled=crt_cfg.enabled,
            phosphor_floor=crt_cfg.phosphor_floor,
            scanlines=crt_cfg.scanlines,
            vignette=crt_cfg.vignette,
            grain=crt_cfg.grain,
            glare=crt_cfg.glare,
            flicker=crt_cfg.flicker,
            glow=crt_cfg.glow,
            rounded_corners=crt_cfg.rounded_corners,
            bezel_inset=crt_cfg.bezel_inset,
            curvature=crt_cfg.curvature,
            grain_fps=crt_cfg.grain_fps,
            grain_seed=crt_cfg.grain_seed,
            width=e.app_config.width,
            height=e.app_config.height,
        ))
        self.__render_gate = RenderGate()
        self.__boot: BootSequence | None = None
        self.__boot_entered = False
        self.__audio_setup: AudioSetupSession | None = None

    @property
    def crt(self) -> CRTRenderer:
        return self.__crt

    @property
    def sounds(self) -> UiSoundService:
        return self.__sounds

    @property
    def boot_active(self) -> bool:
        return self.__boot is not None

    @property
    def boot_sequence(self) -> BootSequence | None:
        return self.__boot

    @property
    def audio_setup_active(self) -> bool:
        return self.__audio_setup is not None

    @property
    def render_gate(self) -> RenderGate:
        return self.__render_gate

    def set_crt_preset(self, preset: str) -> None:
        """Runtime CRT switch for the current process (not persisted)."""
        settings = self.__crt.apply_preset(preset)
        display = self.__display
        set_settings = getattr(display, 'set_crt_settings', None) if display is not None else None
        if callable(set_settings):
            set_settings(settings)
        if display is not None:
            self.update_display(display, partial=False)

    def bind_display(self, display: Display) -> None:
        self.__display = display

    def bind_touch_source(self, source: TouchSource) -> None:
        self.__touch_source = source

    def stop_touch(self) -> None:
        self.__touch_source.stop()
        self.__render_gate.shutdown()
        self.__sounds.close()

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
        self.__sounds.touch()

    def app_content_origin(self) -> tuple[int, int]:
        cfg = self.__environment.app_config
        return cfg.app_side_offset, cfg.app_top_offset

    def on_touch_event(self, event: TouchEvent):
        """Handle a display-space tap; inverse-CRT to logical 800×480 UI coords."""
        display = self.__display
        if display is None:
            return
        if self.__try_skip_boot(display):
            return
        ux, uy = self.__crt.display_to_ui(event.x, event.y)
        if self.__audio_setup is not None:
            action = self.__audio_setup.handle_tap(ux, uy)
            if action:
                self.__handle_audio_setup_action(action, display)
            return
        # Footer is non-interactive
        if self.__footer_rect is not None and self.__footer_rect.contains(ux, uy):
            return
        # Header tabs
        tab = hit_test(self.__tab_hits, ux, uy)
        if tab is not None and tab.action.startswith('tab:'):
            self.switch_to_app(int(tab.action.split(':', 1)[1]))
            self.update_display(display, partial=False)
            return
        # App content
        ox, oy = self.app_content_origin()
        cfg = self.__environment.app_config
        app_w, app_h = cfg.app_size
        local_x = ux - ox
        local_y = uy - oy
        if local_x < 0 or local_y < 0 or local_x >= app_w or local_y >= app_h:
            return
        if self.active_app.on_tap(local_x, local_y):
            if self.active_app.emits_tap_sound:
                self.__sounds.touch()
            self.update_display(display, partial=True)

    def on_digit_key(self, digit: str, display: Display):
        if self.__try_skip_boot(display):
            return
        if self.__audio_setup is not None:
            return
        if self.active_app.on_digit(digit):
            if self.active_app.emits_tap_sound:
                self.__sounds.key()
            self.update_display(display, partial=True)

    def on_backspace_key(self, display: Display):
        if self.__try_skip_boot(display):
            return
        if self.__audio_setup is not None:
            self.__handle_audio_setup_action('skip', display)
            return
        if self.active_app.on_backspace():
            if self.active_app.emits_tap_sound:
                self.__sounds.back()
            self.update_display(display, partial=True)

    def on_clear_key(self, display: Display):
        if self.__try_skip_boot(display):
            return
        if self.__audio_setup is not None:
            return
        # Delete / clear maps to B for AccessApp
        self.active_app.on_key_b()
        if self.active_app.emits_tap_sound:
            self.__sounds.back()
        self.update_display(display, partial=True)

    def watch_function(self, display: Display):
        """Background timer: only schedules work — never touches Tk directly."""
        while True:
            now = datetime.now()
            time.sleep(1.0 - now.microsecond / 1000000.0)
            call_soon = getattr(display, 'call_soon', None)
            if callable(call_soon):
                call_soon(lambda d=display: self.__watch_tick(d))
            else:
                self.__watch_tick(display)

    def __watch_tick(self, display: Display) -> None:
        if self.__boot is not None:
            if self.__boot.is_done():
                self.finish_boot_sequence(display)
            else:
                self.update_display(display, partial=False)
            return
        if self.__audio_setup is not None:
            self.update_display(display, partial=False)
            return
        # Full CRT recompose every second makes touch feel ~1s late on Pi framebuffer.
        # With CRT on, refresh chrome only when UI actually changes (tap/key).
        if self.__crt.enabled:
            self.__tick()
            return
        image, x0, y0 = draw_footer(self.image_buffer, self)
        display.show(image, x0, y0)
        self.__tick()

    def compose_frame(self) -> Image.Image:
        """Build a full logical UI frame (no CRT) into a fresh buffer."""
        image = self.clear_buffer()
        cfg = self.__environment.app_config
        if self.__boot is not None:
            self.__boot.render(
                image,
                accent=cfg.accent,
                font=cfg.font_standard,
                background=cfg.background,
            )
            return image.copy()
        if self.__audio_setup is not None:
            self.__audio_setup.render(
                image,
                accent=cfg.accent,
                accent_dark=cfg.accent_dark,
                font=cfg.font_standard,
                header=cfg.font_header,
                background=cfg.background,
            )
            return image.copy()
        app_bbox = (cfg.app_side_offset,
                    cfg.app_top_offset,
                    cfg.width - cfg.app_side_offset,
                    cfg.height - cfg.app_bottom_offset)
        x_offset, y_offset = app_bbox[0:2]
        for _patch, _x0, _y0 in draw_base(image, self):
            pass
        for patch, x0, y0 in self.active_app.draw(image.crop(app_bbox), False):
            image.paste(patch, (x0 + x_offset, y0 + y_offset))
        return image.copy()

    def update_display(self, display: Display, partial=False):
        """
        Compose (and CRT-process) a complete frame, then hand it to Display.show.
        Concurrent callers coalesce via RenderGate — no parallel CRT passes.
        """
        def _render():
            begin = getattr(display, 'begin_update', None)
            end = getattr(display, 'end_update', None)
            if callable(begin):
                begin()
            try:
                # GPU path applies CRT in-shader — never run Pillow process().
                if getattr(display, 'applies_crt', False):
                    display.show(self.compose_frame(), 0, 0)
                    return

                overlay = self.__boot is not None or self.__audio_setup is not None
                if overlay or self.__crt.enabled:
                    frame = self.compose_frame()
                    if self.__crt.enabled:
                        frame = self.__crt.process(frame, ui_changed=True)
                    display.show(frame, 0, 0)
                    return

                app_bbox = (self.__environment.app_config.app_side_offset,
                            self.__environment.app_config.app_top_offset,
                            self.__environment.app_config.width - self.__environment.app_config.app_side_offset,
                            self.__environment.app_config.height - self.__environment.app_config.app_bottom_offset)
                x_offset, y_offset = app_bbox[0:2]
                if partial:
                    # Reuse buffer — avoid full black clear on every tap (costly on Pi).
                    image = self.image_buffer
                    for patch, x0, y0 in self.active_app.draw(image.crop(app_bbox), partial):
                        display.show(patch, x0 + x_offset, y0 + y_offset)
                else:
                    image = self.clear_buffer()
                    for patch, x0, y0 in draw_base(image, self):
                        display.show(patch, x0, y0)
                    for patch, x0, y0 in self.active_app.draw(image.crop(app_bbox), partial):
                        image.paste(patch, (x0 + x_offset, y0 + y_offset))
                    display.show(image.crop(app_bbox), x_offset, y_offset)
            finally:
                if callable(end):
                    end()

        call_soon = getattr(display, 'call_soon', None)
        is_main = getattr(display, 'is_main_thread', None)
        if callable(call_soon) and callable(is_main) and not is_main():
            call_soon(lambda: self.__render_gate.request(_render))
            return
        self.__render_gate.request(_render)

    def __try_skip_boot(self, display: Display) -> bool:
        """If splash is active, attempt skip (after min time). Returns True if input consumed."""
        boot = self.__boot
        if boot is None:
            return False
        if boot.skip():
            self.__sounds.stop_current()
            self.finish_boot_sequence(display)
        return True

    def __needs_audio_setup(self) -> bool:
        ui = self.__environment.audio.ui_sounds
        if ui.audio_setup_done:
            return False
        if environment.RUNTIME.ui_sound_device_source == 'env':
            return False
        return True

    def begin_audio_setup(self, display: Display) -> None:
        if self.__audio_setup is not None:
            return
        devices = self.__sounds.list_output_devices()
        start = self.__sounds.current_device_index()
        self.__audio_setup = AudioSetupSession(devices, start_index=start)
        logger.info('Audio setup started (%s devices)', len(devices))
        self.update_display(display, partial=False)
        self.__sounds.test_confirm()

    def finish_audio_setup(self, display: Display) -> None:
        self.__audio_setup = None
        self.__enter_main_ui(display)

    def __handle_audio_setup_action(self, action: str, display: Display) -> None:
        session = self.__audio_setup
        if session is None:
            return
        if action == 'hear':
            cur = session.current
            environment.save_ui_sound_local(
                index=cur.index if cur else None,
                name=cur.name if cur else None,
                setup_done=True,
                env=self.__environment,
            )
            session.mark_hear()
            self.finish_audio_setup(display)
            return
        if action == 'next':
            nxt = session.next_device()
            if nxt is not None:
                self.__sounds.rebind_output(nxt.index, selection_source='config')
                self.__sounds.test_confirm()
            self.update_display(display, partial=False)
            return
        if action == 'skip':
            environment.save_ui_sound_local(setup_done=True, env=self.__environment)
            session.mark_skip()
            self.finish_audio_setup(display)

    def __enter_main_ui(self, display: Display) -> None:
        self.update_display(display, partial=False)
        if not self.__boot_entered and self.__apps:
            self.__boot_entered = True
            self.active_app.on_app_enter()
            logger.info('Main UI entered → %s', self.active_app.title)

    def begin_boot_sequence(self) -> None:
        """Start POST splash + boot.wav (idempotent while already active)."""
        if self.__boot is not None:
            return
        self.__boot = BootSequence()
        self.__boot_entered = False
        self.__sounds.boot()
        logger.info('Boot splash started (duration=%.1fs)', self.__boot.duration_s)

    def finish_boot_sequence(self, display: Display) -> None:
        """Leave splash; maybe audio setup; then enter first app once."""
        if self.__boot is None and self.__boot_entered and self.__audio_setup is None:
            return
        self.__boot = None
        if self.__needs_audio_setup():
            self.begin_audio_setup(display)
            return
        self.__enter_main_ui(display)

    def arm_boot_scheduler(self, display: Display, interval_ms: int = 80) -> None:
        """Schedule splash redraws on Tk (call_later) until done."""
        def tick():
            if self.__boot is None:
                return
            if self.__boot.is_done():
                self.finish_boot_sequence(display)
                return
            self.update_display(display, partial=False)
            call_later = getattr(display, 'call_later', None)
            if callable(call_later):
                call_later(interval_ms, tick)
            else:
                call_soon = getattr(display, 'call_soon', None)
                if callable(call_soon):
                    call_soon(tick)

        call_later = getattr(display, 'call_later', None)
        if callable(call_later):
            call_later(0, tick)
        else:
            call_soon = getattr(display, 'call_soon', None)
            if callable(call_soon):
                call_soon(tick)

    def on_key_left(self, display: Display):
        if self.__try_skip_boot(display):
            return
        if self.__audio_setup is not None:
            self.__handle_audio_setup_action(self.__audio_setup.handle_key_left(), display)
            return
        self.__sounds.key()
        self.active_app.on_key_left()
        self.update_display(display, partial=True)

    def on_key_right(self, display: Display):
        if self.__try_skip_boot(display):
            return
        if self.__audio_setup is not None:
            self.__handle_audio_setup_action(self.__audio_setup.handle_key_right(), display)
            return
        self.__sounds.key()
        self.active_app.on_key_right()
        self.update_display(display, partial=True)

    def on_key_up(self, display: Display):
        if self.__try_skip_boot(display):
            return
        if self.__audio_setup is not None:
            return
        self.__sounds.key()
        self.active_app.on_key_up()
        self.update_display(display, partial=True)

    def on_key_down(self, display: Display):
        if self.__try_skip_boot(display):
            return
        if self.__audio_setup is not None:
            return
        self.__sounds.key()
        self.active_app.on_key_down()
        self.update_display(display, partial=True)

    def on_key_a(self, display: Display):
        if self.__try_skip_boot(display):
            return
        if self.__audio_setup is not None:
            self.__handle_audio_setup_action(self.__audio_setup.handle_key_a(), display)
            return
        self.active_app.on_key_a()
        if self.active_app.emits_tap_sound:
            self.__sounds.confirm()
        self.update_display(display, partial=True)

    def on_key_b(self, display: Display):
        if self.__try_skip_boot(display):
            return
        if self.__audio_setup is not None:
            self.__handle_audio_setup_action(self.__audio_setup.handle_key_b(), display)
            return
        self.active_app.on_key_b()
        if self.active_app.emits_tap_sound:
            self.__sounds.back()
        self.update_display(display, partial=True)

    def on_rotary_increase(self, display: Display):
        if self.__try_skip_boot(display):
            return
        if self.__audio_setup is not None:
            self.__handle_audio_setup_action('next', display)
            return
        self.active_app.on_app_leave()
        self.next_app()
        self.active_app.on_app_enter()
        self.__sounds.touch()
        self.update_display(display, partial=False)

    def on_rotary_decrease(self, display: Display):
        if self.__try_skip_boot(display):
            return
        if self.__audio_setup is not None:
            self.__handle_audio_setup_action('next', display)
            return
        self.active_app.on_app_leave()
        self.previous_app()
        self.active_app.on_app_enter()
        self.__sounds.touch()
        self.update_display(display, partial=False)


def run_boot_then_enter(app_state: AppState, display: Display) -> None:
    """
    Show POST splash + boot.wav, then enter the first app.
    Tk displays schedule ticks asynchronously (must call before mainloop).
    Other displays block until the sequence finishes.
    """
    if not app_state.environment.audio.ui_sounds.boot_splash:
        app_state.finish_boot_sequence(display)
        return
    app_state.begin_boot_sequence()
    app_state.update_display(display, partial=False)
    if callable(getattr(display, 'call_later', None)) or callable(getattr(display, 'call_soon', None)):
        app_state.arm_boot_scheduler(display)
        return
    while app_state.boot_active:
        seq = app_state.boot_sequence
        if seq is None or seq.is_done():
            break
        time.sleep(0.08)
        app_state.update_display(display, partial=False)
    app_state.finish_boot_sequence(display)


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
        # Loads config.yaml (+ optional config.local.yaml + PIBOY_UI_SOUND_*).
        # Note: config.ini is logging-only and is never used here.
        env = environment.load_runtime_environment()
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
    def provide_ui_sound_service(self, e: Environment, intercom: IntercomService) -> UiSoundService:
        cfg = e.audio.ui_sounds
        settings = UiSoundSettings(
            enabled=cfg.enabled,
            volume=cfg.volume,
            clicks_during_call=cfg.clicks_during_call,
            min_interval_ms=cfg.min_interval_ms,
            output_device_index=cfg.output_device_index,
            output_device_name=cfg.output_device_name,
        )
        port = open_ui_sound_port(
            prefer_pyaudio=True,
            device_index=cfg.output_device_index,
            device_name=cfg.output_device_name,
            selection_source=environment.RUNTIME.ui_sound_device_source,
        )
        return UiSoundService(
            port=port,
            settings=settings,
            call_phase_fn=lambda: intercom.session().phase,
        )

    @singleton
    @provider
    def provide_app_state(self, e: Environment, intercom: IntercomService, access: AccessService,
                          sensors: SensorService, system: SystemService,
                          sounds: UiSoundService) -> AppState:
        return AppState(e, intercom, access, sensors, system, sounds)

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
            return self.__create_raspberry_display(e)
        if self.__unified_instance is None:
            self.__unified_instance = self.__create_tk_interaction(state, e.app_config)
        return self.__unified_instance

    @staticmethod
    def __create_raspberry_display(e: Environment) -> Display:
        from interaction.FramebufferDisplay import FramebufferDisplay, read_fb_size
        from interaction.ILI9486Display import ILI9486Display
        from rendering.crt import resolve_crt_settings

        driver = (e.display_config.driver or 'auto').strip().lower()
        fb_dev = e.display_config.framebuffer_device or '/dev/fb0'
        app_w, app_h = e.app_config.width, e.app_config.height
        crt_cfg = e.crt

        def make_fb() -> Display:
            logger.info('Using FramebufferDisplay %s (%sx%s)', fb_dev, app_w, app_h)
            return FramebufferDisplay(fb_dev, width=app_w, height=app_h)

        def use_fb() -> bool:
            if not os.path.exists(fb_dev):
                return False
            fb_w, fb_h = read_fb_size(fb_dev)
            return fb_w == app_w and fb_h == app_h

        def try_gles() -> Display | None:
            try:
                from interaction.GlesCrtDisplay import GlesCrtDisplay
                settings = resolve_crt_settings(
                    preset=crt_cfg.preset,
                    enabled=crt_cfg.enabled,
                    phosphor_floor=crt_cfg.phosphor_floor,
                    scanlines=crt_cfg.scanlines,
                    vignette=crt_cfg.vignette,
                    grain=crt_cfg.grain,
                    glare=crt_cfg.glare,
                    flicker=crt_cfg.flicker,
                    glow=crt_cfg.glow,
                    rounded_corners=crt_cfg.rounded_corners,
                    bezel_inset=crt_cfg.bezel_inset,
                    curvature=crt_cfg.curvature,
                    grain_fps=crt_cfg.grain_fps,
                    grain_seed=crt_cfg.grain_seed,
                    width=app_w,
                    height=app_h,
                )
                logger.info('Using GlesCrtDisplay (CRT on GPU)')
                return GlesCrtDisplay(width=app_w, height=app_h, crt_settings=settings)
            except Exception as exc:  # noqa: BLE001
                logger.warning('GLES display unavailable (%s); falling back', exc)
                return None

        # Manual gles only until hardware spike is green; auto stays fb/ili for safety.
        if driver == 'gles':
            gles = try_gles()
            if gles is not None:
                return gles
            if use_fb():
                return make_fb()

        if driver == 'framebuffer' or (driver == 'auto' and use_fb()):
            return make_fb()

        logger.info('Using ILI9486Display (SPI)')
        spi_device_config = e.display_config.display_device
        return ILI9486Display(
            (spi_device_config.bus, spi_device_config.device),
            e.display_config.dc_pin,
            e.display_config.rst_pin,
            e.display_config.flip_display,
        )

    @singleton
    @provider
    def provide_input(self, e: Environment, state: AppState, display: Display) -> Input:
        if e.use_simulator or self.__force_simulator:
            if self.__unified_instance is None:
                self.__unified_instance = self.__create_tk_interaction(state, e.app_config)
            return self.__unified_instance
        if e.backend_mode == BackendMode.RASPBERRY:
            from interaction.FramebufferDisplay import FramebufferDisplay
            from interaction.GlesCrtDisplay import GlesCrtDisplay
            from interaction.ILI9486Display import ILI9486Display
            from interaction.NullInput import NullInput

            if not e.input.keyboard_enabled:
                logger.info('GPIO keypad skipped (input.mode=%s)', e.input.mode)
                return NullInput()

            from interaction.GPIOInput import GPIOInput

            def reset_and_init():
                if isinstance(display, (ILI9486Display, FramebufferDisplay, GlesCrtDisplay)):
                    display.reset()
                display.show(state.clear_buffer(), 0, 0)

            try:
                return GPIOInput(e.keypad_config.left_pin, e.keypad_config.right_pin,
                                 e.keypad_config.up_pin, e.keypad_config.down_pin,
                                 e.keypad_config.a_pin, e.keypad_config.b_pin,
                                 e.rotary_config.rotary_device, e.rotary_config.sw_pin,
                                 lambda: state.on_key_left(display), lambda: state.on_key_right(display),
                                 lambda: state.on_key_up(display), lambda: state.on_key_down(display),
                                 lambda: state.on_key_a(display), lambda: state.on_key_b(display),
                                 lambda: state.on_rotary_increase(display),
                                 lambda: state.on_rotary_decrease(display),
                                 reset_and_init)
            except Exception as exc:  # noqa: BLE001 — missing keypad / GPIO busy / no rotary
                logger.warning('GPIOInput unavailable (%s); continuing without keypad', exc)
                return NullInput()
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

    font = state.environment.app_config.font_tab
    max_text_width = width - (2 * header_side_offset)
    # Ink boxes (FreeType getbbox can have negative top — do not treat bottom as height).
    tab_boxes = [tuple(map(int, font.getbbox(app.title))) for app in state.apps]
    widths = [right - left for left, _top, right, _bottom in tab_boxes]
    heights = [bottom - top for _left, top, _right, bottom in tab_boxes]
    app_text_width = sum(widths) + (len(state.apps) - 1) * app_spacing
    cursor = header_side_offset + max(0, (max_text_width - app_text_width) // 2)
    tab_band = max(1, header_top_offset)
    max_h = max(heights) if heights else 0
    text_top = max(2, (tab_band - max_h) // 2)
    if text_top + max_h > tab_band:
        text_top = max(0, tab_band - max_h)
    tab_hits: list[HitTarget] = []
    for index, app in enumerate(state.apps):
        left, top, right, bottom = tab_boxes[index]
        text_width = right - left
        # anchor=lt: (x, y) is the top-left of the ink box — stays inside the header crop.
        draw.text((cursor, text_top), app.title, color_accent, font=font, anchor='lt')
        tab_rect = Rect(cursor - app_padding, 0,
                        cursor + text_width + app_padding,
                        header_top_offset + vertical_line)
        tab_hits.append(make_hit(tab_rect, f'tab:{index}', min_w=56, min_h=48))
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
    run_boot_then_enter(app_state, DISPLAY)

    import signal

    def _request_shutdown(signum, frame):  # noqa: ARG001
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, _request_shutdown)

    try:
        app_state.watch_function(DISPLAY)
    except KeyboardInterrupt:
        pass
    finally:
        app_state.stop_touch()
        DISPLAY.close()
        INPUT.close()
