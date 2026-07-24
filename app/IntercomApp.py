from typing import Any, Callable, Generator

from injector import inject
from PIL import Image, ImageDraw

from app.App import SelfUpdatingApp
from app.ui_kit import button_row, draw_button, fit_text
from core.decorator import override
from environment import AppConfig
from ports.intercom import CallPhase, PeerPresence
from services.terminal import IntercomService


class IntercomApp(SelfUpdatingApp):
    """СВЯЗЬ — simulated local intercom UI."""

    @inject
    def __init__(self, draw_callback: Callable[[bool], None], intercom: IntercomService,
                 app_config: AppConfig):
        super().__init__(lambda: draw_callback(True))
        self.__intercom = intercom
        self.__app_config = app_config
        self.__selected = 0
        self.__focus_action = 0  # 0=list, 1+=actions
        self.__actions = ['Вызов', 'Принять', 'Отклонить', 'Завершить']

    @property
    @override
    def title(self) -> str:
        return 'СВЗ'

    @property
    @override
    def refresh_time(self) -> float:
        return 0.5

    @override
    def draw(self, image: Image.Image, partial=False) -> Generator[tuple[Image.Image, int, int], Any, None]:
        draw = ImageDraw.Draw(image)
        cfg = self.__app_config
        layout = cfg.layout
        width, height = cfg.app_size
        font = cfg.font_standard
        header_font = cfg.font_header
        accent, dark, bg = cfg.accent, cfg.accent_dark, cfg.background

        draw.text((layout.pad, layout.pad), 'СВЯЗЬ — интерком убежища', fill=accent, font=header_font)

        peers = self.__intercom.peers()
        session = self.__intercom.session()
        y = layout.pad + layout.line_height + layout.gap
        row_h = layout.list_row_height

        for index, peer in enumerate(peers):
            selected = index == self.__selected and self.__focus_action == 0
            row_box = (layout.pad, y, width - layout.pad, y + row_h - 1)
            if selected:
                draw.rectangle(row_box, fill=dark)
            presence = 'online' if peer.presence == PeerPresence.ONLINE else 'offline'
            phase_hint = ''
            if session.remote_peer_id == peer.peer_id and session.phase not in (CallPhase.IDLE, CallPhase.ENDED):
                phase_hint = f' · {self.__phase_label(session.phase)}'
            elif peer.presence == PeerPresence.ONLINE:
                phase_hint = ' · свободен'
            line = fit_text(font, f'{peer.name}  [{presence}]{phase_hint}', width - 2 * layout.pad - 8)
            draw.text((layout.pad + 6, y + (row_h - layout.line_height) // 2), line, fill=accent, font=font)
            y += row_h + 4

        status = fit_text(font, f'Состояние: {session.message or self.__phase_label(session.phase)}',
                          width - 2 * layout.pad)
        draw.text((layout.pad, y + layout.gap), status, fill=accent, font=font)

        btn_y = height - layout.button_min_height - layout.pad
        buttons = button_row(width, btn_y, self.__actions, layout.button_min_width,
                             layout.button_min_height, layout.gap, layout.pad)
        for i, (label, box) in enumerate(buttons):
            focused = self.__focus_action == i + 1
            draw_button(draw, box, label, font, accent, dark, focused, bg)

        yield image, 0, 0

    @staticmethod
    def __phase_label(phase: CallPhase) -> str:
        return {
            CallPhase.IDLE: 'ожидание',
            CallPhase.CALLING: 'вызов',
            CallPhase.RINGING: 'входящий',
            CallPhase.CONNECTING: 'соединение',
            CallPhase.CONNECTED: 'разговор',
            CallPhase.ENDED: 'завершён',
        }.get(phase, phase.value)

    @override
    def on_key_up(self):
        if self.__focus_action == 0:
            peers = self.__intercom.peers()
            if peers:
                self.__selected = (self.__selected - 1) % len(peers)
        else:
            self.__focus_action = 0

    @override
    def on_key_down(self):
        if self.__focus_action == 0:
            peers = self.__intercom.peers()
            if peers:
                self.__selected = (self.__selected + 1) % len(peers)
        else:
            self.__focus_action = 0

    @override
    def on_key_left(self):
        if self.__focus_action <= 1:
            self.__focus_action = 0
        else:
            self.__focus_action -= 1

    @override
    def on_key_right(self):
        self.__focus_action = min(self.__focus_action + 1, len(self.__actions))

    @override
    def on_key_a(self):
        peers = self.__intercom.peers()
        if not peers:
            return
        peer = peers[self.__selected % len(peers)]
        if self.__focus_action == 0 or self.__focus_action == 1:
            self.__intercom.start_call(peer.peer_id)
        elif self.__focus_action == 2:
            self.__intercom.accept()
        elif self.__focus_action == 3:
            self.__intercom.reject()
        elif self.__focus_action == 4:
            self.__intercom.hang_up()

    @override
    def on_key_b(self):
        self.__intercom.hang_up()
