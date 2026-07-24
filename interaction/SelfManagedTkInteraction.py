import tkinter as tk
from typing import Callable, Optional

from PIL import Image, ImageTk

from core.decorator import override
from interaction.Display import Display
from interaction.Input import Input
from interaction.UnifiedInteraction import UnifiedInteraction


class SelfManagedTkInteraction(UnifiedInteraction):
    """
    Dev UI: terminal canvas is exactly `resolution` (e.g. 800×480).
    Keypad and simulator controls are laid out beside the canvas — never over it.
    """

    BUTTON_W = 12
    BUTTON_H = 2

    def __init__(self, on_key_left: Callable[[Display], None], on_key_right: Callable[[Display], None],
                 on_key_up: Callable[[Display], None], on_key_down: Callable[[Display], None],
                 on_key_a: Callable[[Display], None], on_key_b: Callable[[Display], None],
                 on_rotary_increase: Callable[[Display], None], on_rotary_decrease: Callable[[Display], None],
                 on_rotary_switch: Callable[[Display], None],
                 resolution: tuple[int, int], background: tuple[int, int, int], ui_background: tuple[int, int, int],
                 simulator_callback: Optional[Callable[[str], None]] = None):
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
        self.__image = Image.new('RGB', resolution, background)

        self.__root = tk.Tk()
        self.__root.title('Терминал убежища — симулятор')
        self.__root.configure(bg='#%02x%02x%02x' % ui_background)

        w, h = resolution
        self.__image_tk = ImageTk.PhotoImage(self.__image)
        self.__canvas = tk.Canvas(self.__root, width=w, height=h, highlightthickness=0,
                                  bg='#%02x%02x%02x' % background)
        self.__canvas.grid(row=0, column=0, rowspan=12, sticky='nw')
        self.__canvas_image = self.__canvas.create_image(0, 0, anchor=tk.NW, image=self.__image_tk)

        size_label = tk.Label(self.__root, text=f'Экран {w}×{h}',
                              bg='#%02x%02x%02x' % ui_background, fg='#1bfb1e')
        size_label.grid(row=0, column=1, columnspan=3, sticky='w', padx=8)

        # Navigation keypad (beside screen)
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

        # Simulator controls
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

    def __sim(self, action: str):
        if self.__simulator_callback:
            self.__simulator_callback(action)

    @override
    def show(self, image: Image.Image, x0: int, y0: int):
        self.__image.paste(image, (x0, y0))
        self.__image_tk = ImageTk.PhotoImage(self.__image)
        self.__canvas.itemconfigure(self.__canvas_image, image=self.__image_tk)

    @override
    def close(self):
        try:
            self.__root.destroy()
        except tk.TclError:
            pass

    def run(self):
        """Blocking UI mainloop."""
        self.__root.mainloop()
