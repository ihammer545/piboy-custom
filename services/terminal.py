from ports.devices import DeviceCommandResult, DeviceInfo, DevicePort
from ports.intercom import CallSession, IntercomPort, PeerInfo
from ports.lock import AccessPort, AccessResult, LockPort, LockState, PulseResult
from ports.sensors import SensorPort, SensorReading
from ports.status import StatusPort, TerminalStatus
from services.event_log import EventLogService


class AccessService:
    def __init__(self, access_port: AccessPort, lock_port: LockPort, event_log: EventLogService,
                 default_pulse_ms: int = 1500):
        self.__access = access_port
        self.__lock = lock_port
        self.__event_log = event_log
        self.__default_pulse_ms = default_pulse_ms

    def submit_code(self, code: str) -> tuple[AccessResult, PulseResult | None]:
        result = self.__access.evaluate_code(code)
        pulse = None
        if result.outcome.value.startswith('granted'):
            # Effects/silent/normal all still pulse; duration may vary later.
            pulse = self.__lock.pulse_unlock(self.__default_pulse_ms)
        return result, pulse

    def lock_state(self) -> LockState:
        return self.__lock.get_state()


class IntercomService:
    def __init__(self, port: IntercomPort):
        self.__port = port

    def peers(self) -> list[PeerInfo]:
        return self.__port.list_peers()

    def session(self) -> CallSession:
        return self.__port.get_session()

    def start_call(self, peer_id: str) -> CallSession:
        return self.__port.start_call(peer_id)

    def accept(self) -> CallSession:
        return self.__port.accept_call()

    def reject(self) -> CallSession:
        return self.__port.reject_call()

    def hang_up(self) -> CallSession:
        return self.__port.hang_up()

    def simulate_incoming(self, peer_id: str) -> CallSession:
        return self.__port.simulate_incoming(peer_id)

    def set_peer_online(self, peer_id: str, online: bool) -> None:
        self.__port.set_peer_online(peer_id, online)


class DeviceService:
    def __init__(self, port: DevicePort):
        self.__port = port

    def devices(self) -> list[DeviceInfo]:
        return self.__port.list_devices()

    def toggle(self, device_id: str) -> DeviceCommandResult:
        return self.__port.toggle(device_id)

    def set_online(self, device_id: str, online: bool) -> None:
        self.__port.set_device_online(device_id, online)

    def set_next_fails(self, fails: bool) -> None:
        self.__port.set_next_command_fails(fails)


class SensorService:
    def __init__(self, port: SensorPort):
        self.__port = port

    def reading(self) -> SensorReading:
        return self.__port.get_reading()

    def set_online(self, online: bool) -> None:
        self.__port.set_online(online)

    def nudge(self, **kwargs) -> None:
        self.__port.nudge_values(**kwargs)


class SystemService:
    def __init__(self, port: StatusPort, event_log: EventLogService):
        self.__port = port
        self.__event_log = event_log

    def status(self) -> TerminalStatus:
        return self.__port.get_status()

    def event_log(self) -> EventLogService:
        return self.__event_log
