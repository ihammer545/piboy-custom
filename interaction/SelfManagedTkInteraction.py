import logging
import threading
import tkinter as tk
from typing import Callable, Optional

from PIL import Image, ImageTk

from core.decorator import override
from interaction.Display import Display
from interaction.Input import Input
from interaction.UnifiedInteraction import UnifiedInteraction
from interaction.frame_presenter import FramePresenter
from interaction.touch.simulator import SimulatorTouchInput

logger = logging.getLogger('piboy.tk')


class SelfManagedTkInteraction(UnifiedInteraction):
    """
    Dev UI: terminal canvas is exactly `resolution` (e.g. 800×480).
    Keypad and simulator controls are laid out beside the canvas — never over it.
    Left-click on the canvas is a finger tap simulation (no hover/cursor UX).

    All PhotoImage / canvas updates run on the Tk main thread via ``after``.
    Incoming frames are coalesced (queue size 1); the visible frame is never
    cleared to black while the next frame is being prepared.
    """

    BUTTON_W = 12
    BUTTON_H = 2

    def __init__(self, on_key_left: Callable[[Display], None], on_key_right: Callable[[Display], None],
                 on_key_up: Callable[[Display], None], on_key_down: Callable[[Display], None],
                 on_key_a: Callable[[Display], None], on_key_b: Callable[[Display], None],
                 on_rotary_increase: Callable[[Display], None], on_rotary_decrease: Callable[[Display], None],
                 on_rotary_switch: Callable[[Display], None],
                 resolution: tuple[int, int], background: tuple[int, int, int], ui_background: tuple[int, int, int],
                 simulator_callback: Optional[Callable[[str], None]] = None,
                 touch_input: Optional[SimulatorTouchInput] = None,
                 on_digit: Optional[Callable[[str], None]] = None,
                 on_backspace: Optional[Callable[[], None]] = None,
                 on_clear: Optional[Callable[[], None]] = None):
        Input.__init__(self, on_key_left, on_key_right, on_key_up, on_key_down, on_key_a, on_key_b,
                       on_rotary_increase, on_rotary_decrease, on_rotary_switch)
        self.__on_key_left = lambda: on_key_left(self)
        self.__on_key_right = lambda: on_key_right(self)
        self.__on_key_up = lambda: on_key_up(self)
        self.__on_key_down = lambda: on_key_down(self)
        self.__on_key_a = lambda: on_key_a(self)
        self.__on_key_b = lambda: on_key_b(self)
        self.__on_rotary_increase = lambda: on_rotary_increase(self)
        self.__on_rotary_decrease = lambda: on_rotary_decrease(self)
        self.__resolution = resolution
        self.__background = background
        self.__simulator_callback = simulator_callback
        self.__touch_input = touch_input
        self.__on_digit = on_digit
        self.__on_backspace = on_backspace
        self.__on_clear = on_clear
        self.__main_thread_id = threading.get_ident()
        # Staging buffer for partial patches (never shown until a full present).
        self.__staging = Image.new('RGB', resolution, background)
        self.__staging_lock = threading.Lock()
        # Strong refs for the *currently displayed* PhotoImage + pixels.
        self.__displayed_image: Image.Image = self.__staging.copy()
        self.__image_tk = ImageTk.PhotoImage(self.__displayed_image)

        self.__root = tk.Tk()
        self.__root.title('Терминал убежища — симулятор')
        self.__root.configure(bg='#%02x%02x%02x' % ui_background)
        self.__root.config(cursor='none')

        w, h = resolution
        self.__canvas = tk.Canvas(self.__root, width=w, height=h, highlightthickness=0,
                                  bg='#%02x%02x%02x' % background, cursor='none')
        self.__canvas.grid(row=0, column=0, rowspan=12, sticky='nw')
        # One permanent image item — only its `image` option is replaced.
        self.__canvas_image = self.__canvas.create_image(
            0, 0, anchor=tk.NW, image=self.__image_tk,
        )
        self.__canvas.bind('<Button-1>', self.__on_canvas_tap)

        self.__presenter = FramePresenter(
            schedule=self.__schedule_on_main,
            present=self.__present_on_main,
            name='terminal-800x480',
        )

        size_label = tk.Label(self.__root, text=f'Экран {w}×{h} · tap=ЛКМ',
                              bg='#%02x%02x%02x' % ui_background, fg='#1bfb1e')
        size_label.grid(row=0, column=1, columnspan=3, sticky='w', padx=8)

        tk.Button(self.__root, width=self.BUTTON_W, height=self.BUTTON_H, text='▲',
                  command=self.__on_key_up).grid(row=1, column=2, padx=4, pady=2)
        tk.Button(self.__root, width=self.BUTTON_W, height=self.BUTTON_H, text='◀',
                  command=self.__on_key_left).grid(row=2, column=1, padx=4, pady=2)
        tk.Button(self.__root, width=self.BUTTON_W, height=self.BUTTON_H, text='▶',
                  command=self.__on_key_right).grid(row=2, column=3, padx=4, pady=2)
        tk.Button(self.__root, width=self.BUTTON_W, height=self.BUTTON_H, text='▼',
                  command=self.__on_key_down).grid(row=3, column=2, padx=4, pady=2)
        tk.Button(self.__root, width=self.BUTTON_W, height=self.BUTTON_H, text='A / OK',
                  command=self.__on_key_a).grid(row=4, column=1, padx=4, pady=2)
        tk.Button(self.__root, width=self.BUTTON_W, height=self.BUTTON_H, text='B / Back',
                  command=self.__on_key_b).grid(row=4, column=3, padx=4, pady=2)
        tk.Button(self.__root, width=self.BUTTON_W, height=self.BUTTON_H, text='Вкладка −',
                  command=self.__on_rotary_decrease).grid(row=5, column=1, padx=4, pady=2)
        tk.Button(self.__root, width=self.BUTTON_W, height=self.BUTTON_H, text='Вкладка +',
                  command=self.__on_rotary_increase).grid(row=5, column=3, padx=4, pady=2)

        sim_label = tk.Label(self.__root, text='Симулятор',
                             bg='#%02x%02x%02x' % ui_background, fg='#1bfb1e')
        sim_label.grid(row=6, column=1, columnspan=3, sticky='w', padx=8, pady=(12, 2))

        sim_actions = [
            ('Входящий: Бункер', 'incoming_bunker'),
            ('Входящий: 1 этаж', 'incoming_floor1'),
            ('2 этаж online/off', 'toggle_floor2'),
            ('Датчик offline', 'sensor_offline'),
            ('Датчик online', 'sensor_online'),
            ('Датчик жара', 'sensor_hot'),
            ('Датчик норма', 'sensor_ok'),
            ('След. команда FAIL', 'device_fail'),
            ('Вент. offline', 'vent_offline'),
            ('Вент. online', 'vent_online'),
            ('CRT off', 'crt_off'),
            ('CRT subtle', 'crt_subtle'),
            ('CRT strong', 'crt_strong'),
        ]
        for idx, (label, action) in enumerate(sim_actions):
            row = 7 + idx // 2
            col = 1 + (idx % 2) * 2
            tk.Button(self.__root, width=self.BUTTON_W + 4, height=self.BUTTON_H, text=label,
                      command=lambda a=action: self.__sim(a)).grid(row=row, column=col, columnspan=2,
                                                                   padx=4, pady=2, sticky='we')

        self.__root.bind('<Left>', lambda _e: self.__on_key_left())
        self.__root.bind('<Right>', lambda _e: self.__on_key_right())
        self.__root.bind('<Up>', lambda _e: self.__on_key_up())
        self.__root.bind('<Down>', lambda _e: self.__on_key_down())
        self.__root.bind('<Return>', lambda _e: self.__on_key_a())
        self.__root.bind('<Escape>', lambda _e: self.__on_key_b())
        self.__root.bind('<Prior>', lambda _e: self.__on_rotary_decrease())
        self.__root.bind('<Next>', lambda _e: self.__on_rotary_increase())
        self.__root.bind('<BackSpace>', lambda _e: self.__backspace())
        self.__root.bind('<Delete>', lambda _e: self.__clear())
        for digit in '0123456789':
            self.__root.bind(digit, lambda _e, d=digit: self.__digit(d))

    def __schedule_on_main(self, fn: Callable[[], None]) -> None:
        self.__root.after(0, fn)

    def __present_on_main(self, frame: Image.Image) -> None:
        """Atomic canvas update — must run on Tk main thread only."""
        tid = threading.get_ident()
        if tid != self.__main_thread_id:
            logger.error('Tk present from non-main thread=%s (main=%s)', tid, self.__main_thread_id)
        # Own pixel buffer for PhotoImage; never mutate this while it is displayed.
        owned = frame.copy()
        photo = ImageTk.PhotoImage(owned)
        # Keep strong refs so GC cannot drop the visible image.
        self.__displayed_image = owned
        self.__image_tk = photo
        self.__canvas.itemconfigure(self.__canvas_image, image=photo)
        logger.debug('Tk PhotoImage swap thread=%s size=%s', tid, owned.size)

    def is_main_thread(self) -> bool:
        return threading.get_ident() == self.__main_thread_id

    def call_soon(self, fn: Callable[[], None]) -> None:
        """Marshal ``fn`` onto the Tk main thread."""
        if self.is_main_thread():
            fn()
        else:
            self.__schedule_on_main(fn)

    def __digit(self, digit: str):
        if self.__on_digit:
            self.__on_digit(digit)

    def __backspace(self):
        if self.__on_backspace:
            self.__on_backspace()

    def __clear(self):
        if self.__on_clear:
            self.__on_clear()

    def __on_canvas_tap(self, event):
        if self.__touch_input is None:
            return
        cw = max(self.__canvas.winfo_width(), 1)
        ch = max(self.__canvas.winfo_height(), 1)
        self.__touch_input.inject_canvas_click(event.x, event.y, cw, ch)

    def __sim(self, action: str):
        if self.__simulator_callback:
            self.__simulator_callback(action)

    @override
    def show(self, image: Image.Image, x0: int, y0: int):
        """
        Accept a patch or full frame from any thread; present only complete
        frames on the main thread. Never clears the canvas to empty/black.
        """
        w, h = self.__resolution
        with self.__staging_lock:
            if x0 == 0 and y0 == 0 and image.size == (w, h):
                self.__staging.paste(image, (0, 0))
            else:
                self.__staging.paste(image, (x0, y0))
            # Submit an immutable snapshot — staging may be written again immediately.
            snapshot = self.__staging.copy()
        self.__presenter.submit(snapshot)

    @property
    def presenter(self) -> FramePresenter:
        return self.__presenter

    @override
    def close(self):
        self.__presenter.shutdown()
        try:
            self.__root.destroy()
        except tk.TclError:
            pass

    def run(self):
        """Blocking UI mainloop."""
        self.__root.mainloop()
