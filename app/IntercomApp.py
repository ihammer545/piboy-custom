from typing import Any, Callable, Generator

from injector import inject
from PIL import Image, ImageDraw

from app.App import SelfUpdatingApp
from app.ui_kit import button_row, draw_button, fit_text, make_hit
from core.decorator import override
from environment import AppConfig
from interaction.touch.events import HitTarget, Rect, hit_test
from ports.intercom import CallPhase, PeerInfo, PeerPresence
from services.terminal import IntercomService


# Cutaway layout: peer_id → (floor_from_top, slot_index, slot_count)
# floors: 0 = 2nd floor (1 room), 1 = 1st floor (2 rooms), 2 = basement (1 room)
_ROOM_LAYOUT: dict[str, tuple[int, int, int]] = {
    'floor2': (0, 0, 1),
    'floor1_a': (1, 0, 2),
    'floor1_b': (1, 1, 2),
    'bunker': (2, 0, 1),
}


class IntercomApp(SelfUpdatingApp):
    """СВЯЗЬ — shelter cutaway + call controls."""

    @inject
    def __init__(self, draw_callback: Callable[[bool], None], intercom: IntercomService,
                 app_config: AppConfig):
        super().__init__(lambda: draw_callback(True))
        self.__intercom = intercom
        self.__app_config = app_config
        self.__selected = 0
        self.__focus_action = 0  # 0=rooms, 1+=actions
        self.__actions = ['Вызов', 'Принять', 'Отклонить', 'Завершить']
        self.__action_ids = ['call', 'accept', 'reject', 'hangup']
        self.__hits: list[HitTarget] = []
        self.__pressed_action: str | None = None

    @property
    @override
    def title(self) -> str:
        return 'СВЗ'

    @property
    @override
    def refresh_time(self) -> float:
        return 0.5

    def __peers_ordered(self) -> list[PeerInfo]:
        """Peers in cutaway order (top floor → basement, left → right)."""
        peers = {p.peer_id: p for p in self.__intercom.peers()}
        order = ['floor2', 'floor1_a', 'floor1_b', 'bunker']
        ordered = [peers[pid] for pid in order if pid in peers]
        # Any unexpected peers append at end (forward compatible).
        for p in self.__intercom.peers():
            if p.peer_id not in order:
                ordered.append(p)
        return ordered

    def __run_action(self, action_id: str):
        peers = self.__peers_ordered()
        if not peers:
            return
        peer = peers[self.__selected % len(peers)]
        if action_id == 'call':
            self.__intercom.start_call(peer.peer_id)
        elif action_id == 'accept':
            self.__intercom.accept()
        elif action_id == 'reject':
            self.__intercom.reject()
        elif action_id == 'hangup':
            self.__intercom.hang_up()
        elif action_id.startswith('peer:'):
            idx = int(action_id.split(':', 1)[1])
            self.__selected = idx
            self.__focus_action = 0

    def __draw_cutaway(self, draw: ImageDraw.ImageDraw, peers: list[PeerInfo],
                       area: Rect, accent, dark, bg, font, header_font, session) -> None:
        """Fallout Shelter–style side cutaway: earth + rooms + elevator shaft."""
        x0, y0, x1, y1 = area.x0, area.y0, area.x1, area.y1
        # Ground / earth fill
        draw.rectangle((x0, y0, x1, y1), fill=bg, outline=accent, width=1)

        # Surface hatch
        surface_y = y0 + 10
        draw.line((x0 + 4, surface_y, x1 - 4, surface_y), fill=accent, width=1)
        for gx in range(x0 + 8, x1 - 4, 10):
            draw.line((gx, surface_y - 4, gx + 4, surface_y), fill=dark, width=1)

        pad = 8
        elev_w = 22
        building_left = x0 + pad
        building_right = x1 - pad - elev_w - 6
        building_top = surface_y + 8
        building_bottom = y1 - pad
        floors = 3
        floor_h = (building_bottom - building_top) // floors
        elev_x0 = building_right + 6
        elev_x1 = elev_x0 + elev_w - 1

        # Elevator shaft (full height)
        draw.rectangle((elev_x0, building_top, elev_x1, building_bottom), outline=accent, width=1)
        for fy in range(building_top + 6, building_bottom, 10):
            draw.line((elev_x0 + 3, fy, elev_x1 - 3, fy), fill=dark, width=1)

        peer_by_id = {p.peer_id: (i, p) for i, p in enumerate(peers)}

        for peer_id, (floor, slot, slots) in _ROOM_LAYOUT.items():
            if peer_id not in peer_by_id:
                continue
            index, peer = peer_by_id[peer_id]
            fy0 = building_top + floor * floor_h
            fy1 = fy0 + floor_h - 4
            slot_w = (building_right - building_left - (slots - 1) * 4) // slots
            rx0 = building_left + slot * (slot_w + 4)
            rx1 = rx0 + slot_w - 1
            box = Rect(rx0, fy0, rx1, fy1)

            selected = index == self.__selected and self.__focus_action == 0
            online = peer.presence == PeerPresence.ONLINE
            in_call = (
                session.remote_peer_id == peer.peer_id
                and session.phase not in (CallPhase.IDLE, CallPhase.ENDED)
            )

            fill = dark if selected or in_call else bg
            outline = accent
            draw.rectangle(box.as_tuple(), fill=fill, outline=outline, width=2 if selected else 1)

            # Inner “lit room” bar when online
            if online:
                inset = 4
                draw.rectangle(
                    (rx0 + inset, fy0 + inset, rx1 - inset, fy0 + inset + 3),
                    fill=accent,
                )

            label = fit_text(font, peer.name, box.width - 8)
            _, _, tw, th = font.getbbox(label)
            draw.text((rx0 + (box.width - tw) // 2, fy0 + (box.height - th) // 2 - 4),
                      label, fill=accent, font=font)

            status = 'онлайн' if online else 'офлайн'
            if in_call:
                status = self.__phase_label(session.phase)
            status = fit_text(font, status, box.width - 8)
            _, _, sw, sh = font.getbbox(status)
            draw.text((rx0 + (box.width - sw) // 2, fy0 + box.height // 2 + 4),
                      status, fill=accent if online else dark, font=font)

            # Door notch toward elevator
            mid_y = (fy0 + fy1) // 2
            draw.rectangle((rx1 - 3, mid_y - 6, rx1, mid_y + 6), fill=accent)

            self.__hits.append(make_hit(box, f'peer:{index}',
                                        min_w=44, min_h=44))

        # Floor labels on the far left margin (tiny)
        floor_names = ['2 эт.', '1 эт.', 'подв.']
        for fi, name in enumerate(floor_names):
            ty = building_top + fi * floor_h + 2
            draw.text((x0 + 2, ty), name, fill=dark, font=font)

    @override
    def draw(self, image: Image.Image, partial=False) -> Generator[tuple[Image.Image, int, int], Any, None]:
        draw = ImageDraw.Draw(image)
        cfg = self.__app_config
        layout = cfg.layout
        width, height = cfg.app_size
        font = cfg.font_standard
        header_font = cfg.font_header
        accent, dark, bg = cfg.accent, cfg.accent_dark, cfg.background
        self.__hits = []

        draw.text((layout.pad, layout.pad), 'СВЯЗЬ — схема убежища', fill=accent, font=header_font)

        peers = self.__peers_ordered()
        session = self.__intercom.session()

        btn_h = layout.button_min_height + 16
        status_h = layout.line_height + layout.gap
        cutaway = Rect(
            layout.pad,
            layout.pad + layout.line_height + layout.gap,
            width - layout.pad,
            height - layout.pad - btn_h - status_h - layout.gap * 2,
        )
        self.__draw_cutaway(draw, peers, cutaway, accent, dark, bg, font, header_font, session)

        status = fit_text(
            font,
            f'Состояние: {session.message or self.__phase_label(session.phase)}',
            width - 2 * layout.pad,
        )
        draw.text((layout.pad, cutaway.y1 + layout.gap), status, fill=accent, font=font)

        btn_y = height - btn_h - layout.pad
        buttons = button_row(width, btn_y, self.__actions, layout.button_min_width,
                             btn_h, layout.gap, layout.pad)
        session_phase = session.phase
        enabled_map = {
            'call': session_phase in (CallPhase.IDLE, CallPhase.ENDED),
            'accept': session_phase == CallPhase.RINGING,
            'reject': session_phase == CallPhase.RINGING,
            'hangup': session_phase in (CallPhase.CALLING, CallPhase.CONNECTING, CallPhase.CONNECTED, CallPhase.RINGING),
        }
        for i, (label, box) in enumerate(buttons):
            action_id = self.__action_ids[i]
            enabled = enabled_map.get(action_id, True)
            focused = self.__focus_action == i + 1
            pressed = self.__pressed_action == action_id
            draw_button(draw, box, label, font, accent, dark, focused=focused, background=bg,
                        pressed=pressed, disabled=not enabled)
            self.__hits.append(make_hit(box, action_id, enabled=enabled,
                                        min_w=layout.button_min_width, min_h=layout.button_min_height))

        self.__pressed_action = None
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
    def on_tap(self, x: int, y: int) -> bool:
        target = hit_test(self.__hits, x, y)
        if target is None:
            return False
        self.__pressed_action = target.action
        if target.action.startswith('peer:'):
            self.__run_action(target.action)
        else:
            self.__focus_action = self.__action_ids.index(target.action) + 1
            self.__run_action(target.action)
        return True

    @override
    def on_key_up(self):
        if self.__focus_action == 0:
            peers = self.__peers_ordered()
            if peers:
                self.__selected = (self.__selected - 1) % len(peers)
        else:
            self.__focus_action = 0

    @override
    def on_key_down(self):
        if self.__focus_action == 0:
            peers = self.__peers_ordered()
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
        if self.__focus_action == 0 or self.__focus_action == 1:
            self.__run_action('call')
        elif self.__focus_action == 2:
            self.__run_action('accept')
        elif self.__focus_action == 3:
            self.__run_action('reject')
        elif self.__focus_action == 4:
            self.__run_action('hangup')

    @override
    def on_key_b(self):
        self.__run_action('hangup')
