"""Unit tests for shelter terminal simulator services (stage 1)."""
import time

from backend.simulator import SimulatorBackend
from ports.intercom import CallPhase, PeerPresence
from ports.lock import AccessOutcome, LockState
from ports.sensors import SensorReading
from services.event_log import EventLogService
from services.terminal import AccessService, DeviceService, IntercomService, SensorService


def _backend(pulse_ms: int = 200) -> tuple[SimulatorBackend, EventLogService]:
    log = EventLogService(max_events=20)
    backend = SimulatorBackend(log, resolution=(800, 480), lock_pulse_ms=pulse_ms, connect_delay_s=0.15)
    return backend, log


def test_resolution_constant():
    backend, _ = _backend()
    assert backend.get_status().resolution == (800, 480)


def test_lock_pulse_returns_to_safe():
    backend, log = _backend(pulse_ms=150)
    assert backend.get_state() == LockState.LOCKED
    result = backend.pulse_unlock()
    assert result.ok
    assert backend.get_state() == LockState.PULSING
    time.sleep(0.25)
    assert backend.get_state() == LockState.LOCKED
    messages = ' '.join(e.message for e in log.list_events())
    assert 'импульс' in messages.lower() or 'Импульс' in messages
    assert 'безопасное' in messages.lower() or 'безопасн' in messages


def test_access_masks_code_from_log():
    backend, log = _backend()
    access = AccessService(backend, backend, log, default_pulse_ms=100)
    result, pulse = access.submit_code('1234')
    assert result.outcome == AccessOutcome.GRANTED_NORMAL
    assert pulse is not None
    denied, _ = access.submit_code('1111')
    assert denied.outcome == AccessOutcome.DENIED
    blob = ' '.join(e.message for e in log.list_events())
    assert '1234' not in blob
    assert '1111' not in blob
    assert '0000' not in blob


def test_demo_scenarios():
    backend, _ = _backend()
    assert backend.evaluate_code('0000').outcome == AccessOutcome.GRANTED_SILENT
    assert backend.evaluate_code('9999').outcome == AccessOutcome.GRANTED_EFFECTS
    assert backend.evaluate_code('5555').outcome == AccessOutcome.DENIED


def test_intercom_outbound_state_machine():
    backend, _ = _backend()
    intercom = IntercomService(backend)
    session = intercom.start_call('bunker')
    assert session.phase == CallPhase.CALLING
    # wait for connecting/connected
    deadline = time.time() + 2.0
    while time.time() < deadline:
        phase = intercom.session().phase
        if phase == CallPhase.CONNECTED:
            break
        time.sleep(0.05)
    assert intercom.session().phase == CallPhase.CONNECTED
    ended = intercom.hang_up()
    assert ended.phase == CallPhase.ENDED


def test_intercom_incoming_accept_reject():
    backend, _ = _backend()
    intercom = IntercomService(backend)
    session = intercom.simulate_incoming('floor1_a')
    assert session.phase == CallPhase.RINGING
    intercom.reject()
    assert intercom.session().phase == CallPhase.ENDED

    intercom.simulate_incoming('floor1_a')
    intercom.accept()
    deadline = time.time() + 2.0
    while time.time() < deadline and intercom.session().phase != CallPhase.CONNECTED:
        time.sleep(0.05)
    assert intercom.session().phase == CallPhase.CONNECTED


def test_peer_offline_blocks_call():
    backend, _ = _backend()
    intercom = IntercomService(backend)
    intercom.set_peer_online('floor2', False)
    peers = {p.peer_id: p for p in intercom.peers()}
    assert peers['floor2'].presence == PeerPresence.OFFLINE
    session = intercom.start_call('floor2')
    assert session.phase == CallPhase.ENDED


def test_devices_toggle_and_fail():
    backend, _ = _backend()
    devices = DeviceService(backend)
    vent = next(d for d in devices.devices() if d.device_id == 'vent')
    assert vent.powered_on is False
    ok = devices.toggle('vent')
    assert ok.ok
    assert ok.device.powered_on is True
    devices.set_next_fails(True)
    fail = devices.toggle('vent')
    assert fail.ok is False


def test_sensors_warning_and_offline():
    backend, _ = _backend()
    sensors = SensorService(backend)
    sensors.nudge(temperature=50.0)
    reading = sensors.reading()
    assert isinstance(reading, SensorReading)
    assert reading.warning
    sensors.set_online(False)
    offline = sensors.reading()
    assert offline.data is None


def test_event_log_limit():
    log = EventLogService(max_events=5)
    for i in range(20):
        log.add('test', f'event-{i}')
    events = log.list_events()
    assert len(events) == 5
    assert events[0].message == 'event-19'
