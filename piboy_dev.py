import threading

from injector import Injector

from backend.simulator import SimulatorBackend
from environment import Environment
from interaction.SelfManagedTkInteraction import SelfManagedTkInteraction
from interaction.touch.simulator import SimulatorTouchInput
from piboy import AppModule, AppState, register_shelter_apps
from services.terminal import DeviceService, IntercomService, SensorService

"""
Shelter terminal — development entrypoint.

Always uses simulator backend. Main terminal surface is exactly app_config.resolution
(default 800×480). Virtual keypad and simulator controls sit beside the screen.
Left-click on the canvas simulates a finger tap.
"""
if __name__ == '__main__':
    module = AppModule()
    module.set_force_simulator(True)
    injector = Injector([module])

    env = injector.get(Environment)
    app_state = injector.get(AppState)
    backend = injector.get(SimulatorBackend)
    intercom = injector.get(IntercomService)
    sensors = injector.get(SensorService)
    devices = injector.get(DeviceService)

    touch = SimulatorTouchInput(
        on_event=app_state.on_touch_event,
        debounce_ms=env.input.touch.debounce_ms,
        screen_width=env.app_config.width,
        screen_height=env.app_config.height,
    )
    touch.start()
    app_state.bind_touch_source(touch)

    def on_sim_action(action: str):
        if action == 'incoming_bunker':
            intercom.simulate_incoming('bunker')
        elif action == 'incoming_floor1':
            intercom.simulate_incoming('floor1')
        elif action == 'toggle_floor2':
            peers = {p.peer_id: p for p in intercom.peers()}
            peer = peers.get('floor2')
            if peer:
                online = peer.presence.value == 'online'
                intercom.set_peer_online('floor2', not online)
        elif action == 'sensor_offline':
            sensors.set_online(False)
        elif action == 'sensor_online':
            sensors.set_online(True)
        elif action == 'sensor_hot':
            sensors.set_online(True)
            sensors.nudge(temperature=42.0)
        elif action == 'sensor_ok':
            sensors.set_online(True)
            sensors.nudge(temperature=21.5, humidity=0.48)
        elif action == 'device_fail':
            devices.set_next_fails(True)
        elif action == 'vent_offline':
            devices.set_online('vent', False)
        elif action == 'vent_online':
            devices.set_online('vent', True)
        elif action == 'crt_off':
            app_state.set_crt_preset('off')
            return
        elif action == 'crt_subtle':
            app_state.set_crt_preset('subtle')
            return
        elif action == 'crt_strong':
            app_state.set_crt_preset('strong')
            return
        elif action == 'sound_toggle':
            app_state.sounds.set_enabled(not app_state.sounds.enabled)
            return
        elif action == 'sound_vol_down':
            app_state.sounds.adjust_volume(-0.05)
            return
        elif action == 'sound_vol_up':
            app_state.sounds.adjust_volume(0.05)
            return
        elif action == 'sound_test':
            info = app_state.sounds.test_confirm()
            print(f'[ui-sound] test device: {info}')
            return
        app_state.update_display(__tk, partial=False)

    __tk = SelfManagedTkInteraction(
        app_state.on_key_left, app_state.on_key_right,
        app_state.on_key_up, app_state.on_key_down,
        app_state.on_key_a, app_state.on_key_b,
        app_state.on_rotary_increase, app_state.on_rotary_decrease, lambda _: None,
        env.app_config.resolution, env.app_config.background, env.app_config.accent_dark,
        simulator_callback=on_sim_action,
        touch_input=touch,
        on_digit=lambda d: app_state.on_digit_key(d, __tk),
        on_backspace=lambda: app_state.on_backspace_key(__tk),
        on_clear=lambda: app_state.on_clear_key(__tk),
    )

    module.register_external_tk_interaction(__tk)
    app_state.bind_display(__tk)
    register_shelter_apps(injector, app_state)

    app_state.update_display(__tk)
    app_state.active_app.on_app_enter()

    threading.Thread(target=app_state.watch_function, args=(__tk,), daemon=True).start()

    try:
        __tk.run()
    except KeyboardInterrupt:
        pass
    finally:
        app_state.stop_touch()
        backend.ensure_safe()
        __tk.close()
