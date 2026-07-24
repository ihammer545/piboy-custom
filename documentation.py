"""Generate static app screenshots for documentation (shelter terminal)."""
import os
from typing import Callable

from injector import Injector, provider, singleton
from PIL import Image

from core.decorator import override
from environment import Environment
from piboy import AppModule, AppState, draw_base, register_shelter_apps

target = './docs/apps'

# Latin filenames for docs (UI titles stay Cyrillic).
SCREENSHOT_NAMES = {
    'СВЗ': 'intercom.png',
    'ДОСТ': 'access.png',
    'СРЕД': 'sensors.png',
    'СИСТ': 'devices.png',
    'ЛОГ': 'event-log.png',
    'СЕРВ': 'system.png',
}


class DefaultEnvironmentAppModule(AppModule):

    def __init__(self):
        super().__init__()
        self.set_force_simulator(True)

    @singleton
    @provider
    @override
    def provide_environment(self) -> Environment:
        return Environment()

    @singleton
    @provider
    @override
    def provide_draw_callback(self, state: AppState) -> Callable[[bool], None]:
        return lambda partial: None


def main():
    module = DefaultEnvironmentAppModule()
    injector = Injector([module])
    app_state = injector.get(AppState)
    register_shelter_apps(injector, app_state)

    os.makedirs(target, exist_ok=True)
    for index, app in enumerate(app_state.apps):
        while app_state.active_app_index != index:
            app_state.next_app()
        image = app_state.clear_buffer()
        for patch, x0, y0 in draw_base(image, app_state):
            image.paste(patch, (x0, y0))
        bbox = (app_state.environment.app_config.app_side_offset,
                app_state.environment.app_config.app_top_offset,
                app_state.environment.app_config.width - app_state.environment.app_config.app_side_offset,
                app_state.environment.app_config.height - app_state.environment.app_config.app_bottom_offset)
        for patch, x0, y0 in app.draw(image.crop(bbox), partial=False):
            image.paste(patch, (x0 + bbox[0], y0 + bbox[1]))
        filename = SCREENSHOT_NAMES.get(app.title, f'{app.title}.png')
        path = os.path.join(target, filename)
        image.save(path)
        print('wrote', path, image.size)


if __name__ == '__main__':
    main()
