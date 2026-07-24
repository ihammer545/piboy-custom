import random
import threading
import time
from datetime import datetime
from subprocess import run

from core.data import DeviceStatus
from data.EnvironmentDataProvider import EnvironmentData
from ports.devices import DeviceCommandResult, DeviceInfo, DevicePort, DevicePresence
from ports.intercom import CallPhase, CallSession, IntercomPort, PeerInfo, PeerPresence
from ports.lock import AccessOutcome, AccessPort, AccessResult, LockPort, LockState, PulseResult
from ports.sensors import SensorPort, SensorReading
from ports.status import LinkStatus, StatusPort, TerminalStatus
from services.event_log import EventLogService


class SimulatorBackend(LockPort, AccessPort, IntercomPort, DevicePort, SensorPort, StatusPort):
    """
    In-process simulator for shelter terminal stage 1.
    Demo access codes live only here — never log the digits themselves.
    """

    # Demonstration-only codes for the simulator (not production secrets).
    __DEMO_CODES = {
        '1234': (AccessOutcome.GRANTED_NORMAL, 'normal', 'Обычное открытие'),
        '0000': (AccessOutcome.GRANTED_SILENT, 'silent', 'Тихое открытие'),
        '9999': (AccessOutcome.GRANTED_EFFECTS, 'effects', 'Открытие со световым и звуковым эффектом'),
    }

    def __init__(self, event_log: EventLogService, resolution: tuple[int, int],
                 lock_pulse_ms: int = 1500,
                 temp_min: float = 10.0, temp_max: float = 35.0,
                 humidity_min: float = 0.20, humidity_max: float = 0.80,
                 connect_delay_s: float = 0.8):
        self.__event_log = event_log
        self.__resolution = resolution
        self.__lock_pulse_ms = lock_pulse_ms
        self.__temp_min = temp_min
        self.__temp_max = temp_max
        self.__humidity_min = humidity_min
        self.__humidity_max = humidity_max
        self.__connect_delay_s = connect_delay_s
        self.__started_at = time.monotonic()
        self.__version = self.__read_version()

        self.__lock = threading.RLock()
        self.__lock_state = LockState.LOCKED
        self.__pulse_timer: threading.Timer | None = None

        self.__peers: dict[str, PeerInfo] = {
            'bunker': PeerInfo('bunker', 'Бункер', PeerPresence.ONLINE),
            'floor1': PeerInfo('floor1', '1 этаж', PeerPresence.ONLINE),
            'floor2': PeerInfo('floor2', '2 этаж', PeerPresence.OFFLINE),
        }
        self.__session = CallSession(CallPhase.IDLE)
        self.__connect_timer: threading.Timer | None = None

        self.__devices: dict[str, DeviceInfo] = {
            'vent': DeviceInfo('vent', 'Вентиляция', 'relay', DevicePresence.ONLINE, False, True),
            'lights': DeviceInfo('lights', 'Освещение', 'relay', DevicePresence.ONLINE, True, False),
            'pump': DeviceInfo('pump', 'Насос', 'relay', DevicePresence.ONLINE, False, True),
        }
        self.__next_command_fails = False

        self.__sensor_online = True
        self.__sensor_was_online = True
        self.__temperature = 21.5
        self.__humidity = 0.48
        self.__pressure = 1013.0
        self.__sensor_last_update: datetime | None = datetime.now()

        self.__network = LinkStatus.SIMULATED
        self.__audio = LinkStatus.SIMULATED

        self.ensure_safe()

    def get_state(self) -> LockState:
        with self.__lock:
            return self.__lock_state

    def ensure_safe(self) -> None:
        with self.__lock:
            if self.__pulse_timer is not None:
                self.__pulse_timer.cancel()
                self.__pulse_timer = None
            self.__lock_state = LockState.LOCKED

    def pulse_unlock(self, duration_ms: int | None = None) -> PulseResult:
        duration = self.__lock_pulse_ms if duration_ms is None else max(50, duration_ms)
        with self.__lock:
            if self.__pulse_timer is not None:
                self.__pulse_timer.cancel()
            self.__lock_state = LockState.PULSING
            self.__pulse_timer = threading.Timer(duration / 1000.0, self.__end_pulse)
            self.__pulse_timer.daemon = True
            self.__pulse_timer.start()
        self.__event_log.add('lock', f'Замок: импульс {duration} мс')
        return PulseResult(True, f'Импульс замка {duration} мс', duration)

    def __end_pulse(self) -> None:
        with self.__lock:
            self.__lock_state = LockState.LOCKED
            self.__pulse_timer = None
        self.__event_log.add('lock', 'Замок: безопасное состояние')

    def evaluate_code(self, code: str) -> AccessResult:
        entry = self.__DEMO_CODES.get(code)
        if entry is None:
            self.__event_log.add('access', 'Доступ отклонён')
            return AccessResult(AccessOutcome.DENIED, 'Отказ в доступе', 'denied')
        outcome, scenario, message = entry
        self.__event_log.add('access', f'Доступ разрешён ({scenario})')
        return AccessResult(outcome, message, scenario)

    def list_peers(self) -> list[PeerInfo]:
        with self.__lock:
            return [PeerInfo(p.peer_id, p.name, p.presence, p.busy) for p in self.__peers.values()]

    def get_session(self) -> CallSession:
        with self.__lock:
            return CallSession(self.__session.phase, self.__session.remote_peer_id,
                               self.__session.direction, self.__session.message)

    def start_call(self, peer_id: str) -> CallSession:
        with self.__lock:
            peer = self.__peers.get(peer_id)
            if peer is None:
                return self.__session
            if self.__session.phase not in (CallPhase.IDLE, CallPhase.ENDED):
                self.__session.message = 'Уже есть активный вызов'
                return self.get_session()
            if peer.presence != PeerPresence.ONLINE:
                self.__session = CallSession(CallPhase.ENDED, peer_id, 'out', 'Абонент недоступен')
                self.__event_log.add('intercom', f'Вызов к «{peer.name}» не удался (offline)')
                return self.get_session()
            self.__cancel_connect_timer()
            self.__session = CallSession(CallPhase.CALLING, peer_id, 'out', 'Вызов...')
            peer.busy = True
            self.__event_log.add('intercom', f'Исходящий вызов: {peer.name}')
            self.__connect_timer = threading.Timer(self.__connect_delay_s, self.__auto_connect_out, args=(peer_id,))
            self.__connect_timer.daemon = True
            self.__connect_timer.start()
            return self.get_session()

    def __auto_connect_out(self, peer_id: str) -> None:
        with self.__lock:
            if self.__session.phase != CallPhase.CALLING or self.__session.remote_peer_id != peer_id:
                return
            self.__session = CallSession(CallPhase.CONNECTING, peer_id, 'out', 'Соединение...')
        timer = threading.Timer(0.4, self.__mark_connected, args=(peer_id, 'out'))
        timer.daemon = True
        timer.start()

    def __mark_connected(self, peer_id: str, direction: str) -> None:
        with self.__lock:
            if self.__session.remote_peer_id != peer_id:
                return
            if self.__session.phase not in (CallPhase.CONNECTING, CallPhase.CALLING, CallPhase.RINGING):
                return
            peer = self.__peers.get(peer_id)
            name = peer.name if peer else peer_id
            self.__session = CallSession(CallPhase.CONNECTED, peer_id, direction, f'Разговор: {name}')
            self.__event_log.add('intercom', f'Разговор начат: {name}')

    def accept_call(self) -> CallSession:
        with self.__lock:
            if self.__session.phase != CallPhase.RINGING:
                return self.get_session()
            peer_id = self.__session.remote_peer_id
            self.__session = CallSession(CallPhase.CONNECTING, peer_id, 'in', 'Соединение...')
            self.__event_log.add('intercom', 'Входящий вызов принят')
        if peer_id:
            timer = threading.Timer(0.4, self.__mark_connected, args=(peer_id, 'in'))
            timer.daemon = True
            timer.start()
        return self.get_session()

    def reject_call(self) -> CallSession:
        with self.__lock:
            if self.__session.phase != CallPhase.RINGING:
                return self.get_session()
            peer_id = self.__session.remote_peer_id
            peer = self.__peers.get(peer_id) if peer_id else None
            if peer:
                peer.busy = False
            name = peer.name if peer else (peer_id or '?')
            self.__session = CallSession(CallPhase.ENDED, peer_id, 'in', 'Отклонён')
            self.__event_log.add('intercom', f'Входящий вызов отклонён: {name}')
            return self.get_session()

    def hang_up(self) -> CallSession:
        with self.__lock:
            self.__cancel_connect_timer()
            peer_id = self.__session.remote_peer_id
            peer = self.__peers.get(peer_id) if peer_id else None
            if peer:
                peer.busy = False
            name = peer.name if peer else (peer_id or '?')
            if self.__session.phase in (CallPhase.IDLE, CallPhase.ENDED):
                return self.get_session()
            self.__session = CallSession(CallPhase.ENDED, peer_id, self.__session.direction, 'Завершён')
            self.__event_log.add('intercom', f'Вызов завершён: {name}')
            return self.get_session()

    def simulate_incoming(self, peer_id: str) -> CallSession:
        with self.__lock:
            peer = self.__peers.get(peer_id)
            if peer is None:
                return self.get_session()
            if self.__session.phase not in (CallPhase.IDLE, CallPhase.ENDED):
                self.__session.message = 'Линия занята'
                return self.get_session()
            if peer.presence != PeerPresence.ONLINE:
                peer.presence = PeerPresence.ONLINE
            self.__cancel_connect_timer()
            peer.busy = True
            self.__session = CallSession(CallPhase.RINGING, peer_id, 'in', f'Входящий: {peer.name}')
            self.__event_log.add('intercom', f'Входящий вызов: {peer.name}')
            return self.get_session()

    def set_peer_online(self, peer_id: str, online: bool) -> None:
        with self.__lock:
            peer = self.__peers.get(peer_id)
            if peer is None:
                return
            peer.presence = PeerPresence.ONLINE if online else PeerPresence.OFFLINE
            if not online and self.__session.remote_peer_id == peer_id \
                    and self.__session.phase not in (CallPhase.IDLE, CallPhase.ENDED):
                self.__cancel_connect_timer()
                peer.busy = False
                self.__session = CallSession(CallPhase.ENDED, peer_id, self.__session.direction, 'Связь потеряна')
                self.__event_log.add('intercom', f'Связь с «{peer.name}» потеряна')

    def __cancel_connect_timer(self) -> None:
        if self.__connect_timer is not None:
            self.__connect_timer.cancel()
            self.__connect_timer = None

    def list_devices(self) -> list[DeviceInfo]:
        with self.__lock:
            return [
                DeviceInfo(d.device_id, d.name, d.kind, d.presence, d.powered_on, d.requires_confirm)
                for d in self.__devices.values()
            ]

    def toggle(self, device_id: str) -> DeviceCommandResult:
        with self.__lock:
            device = self.__devices.get(device_id)
            if device is None:
                return DeviceCommandResult(False, 'Устройство не найдено')
            if device.presence != DevicePresence.ONLINE:
                return DeviceCommandResult(False, f'«{device.name}» недоступно', device)
            if self.__next_command_fails:
                self.__next_command_fails = False
                self.__event_log.add('device', f'«{device.name}»: ошибка команды')
                return DeviceCommandResult(False, f'Ошибка управления «{device.name}»', device)
            device.powered_on = not device.powered_on
            state = 'включено' if device.powered_on else 'выключено'
            self.__event_log.add('device', f'«{device.name}» {state}')
            snapshot = DeviceInfo(device.device_id, device.name, device.kind, device.presence,
                                  device.powered_on, device.requires_confirm)
            return DeviceCommandResult(True, f'«{device.name}» {state}', snapshot)

    def set_device_online(self, device_id: str, online: bool) -> None:
        with self.__lock:
            device = self.__devices.get(device_id)
            if device is None:
                return
            device.presence = DevicePresence.ONLINE if online else DevicePresence.OFFLINE

    def set_next_command_fails(self, fails: bool) -> None:
        with self.__lock:
            self.__next_command_fails = fails

    def get_reading(self) -> SensorReading:
        with self.__lock:
            if not self.__sensor_online:
                if self.__sensor_was_online:
                    self.__event_log.add('sensor', 'Датчик потерял связь')
                    self.__sensor_was_online = False
                return SensorReading(None, DeviceStatus.UNAVAILABLE, self.__sensor_last_update,
                                    'Источник offline')
            if not self.__sensor_was_online:
                self.__event_log.add('sensor', 'Датчик восстановил связь')
                self.__sensor_was_online = True

            self.__temperature += random.uniform(-0.05, 0.05)
            self.__humidity = min(0.99, max(0.01, self.__humidity + random.uniform(-0.002, 0.002)))
            self.__pressure += random.uniform(-0.2, 0.2)
            self.__sensor_last_update = datetime.now()
            data = EnvironmentData(self.__temperature, self.__pressure, self.__humidity)
            warning = self.__build_warning(data)
            return SensorReading(data, DeviceStatus.OPERATIONAL, self.__sensor_last_update, warning)

    def __build_warning(self, data: EnvironmentData) -> str | None:
        parts = []
        if data.temperature < self.__temp_min or data.temperature > self.__temp_max:
            parts.append('температура')
        if data.humidity < self.__humidity_min or data.humidity > self.__humidity_max:
            parts.append('влажность')
        if not parts:
            return None
        return 'Вне нормы: ' + ', '.join(parts)

    def set_online(self, online: bool) -> None:
        with self.__lock:
            self.__sensor_online = online

    def nudge_values(self, temperature: float | None = None,
                     humidity: float | None = None,
                     pressure: float | None = None) -> None:
        with self.__lock:
            if temperature is not None:
                self.__temperature = temperature
            if humidity is not None:
                self.__humidity = humidity
            if pressure is not None:
                self.__pressure = pressure
            self.__sensor_last_update = datetime.now()

    def get_status(self) -> TerminalStatus:
        return TerminalStatus(
            backend='simulator',
            network=self.__network,
            audio=self.__audio,
            resolution=self.__resolution,
            uptime_seconds=time.monotonic() - self.__started_at,
            version=self.__version,
        )

    def set_network_online(self, online: bool) -> None:
        self.__network = LinkStatus.SIMULATED if online else LinkStatus.OFFLINE

    def set_audio_online(self, online: bool) -> None:
        self.__audio = LinkStatus.SIMULATED if online else LinkStatus.OFFLINE

    @staticmethod
    def __read_version() -> str:
        try:
            result = run(['git', 'rev-parse', '--short', 'HEAD'], capture_output=True, text=True, timeout=1)
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip()
        except (OSError, TimeoutError):
            pass
        return 'dev'
