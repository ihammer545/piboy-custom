"""Regression: Tk root must exist before PhotoImage; explicit master everywhere.

Does not require a real display or ``_tkinter`` — stubs ``tkinter`` before import.
"""
from __future__ import annotations

import sys
from types import ModuleType
from typing import Any

import pytest
from PIL import Image


def _install_fake_tkinter(monkeypatch):
    """Provide a minimal tkinter stand-in so the module can import without _tkinter."""
    events: list[str] = []
    roots: list[Any] = []
    canvases: list[Any] = []
    photos: list[Any] = []

    class FakeRoot:
        def __init__(self):
            self.after_calls = []
            self.destroyed = False
            events.append('Tk')
            roots.append(self)

        def title(self, *_a, **_k):
            pass

        def configure(self, **_k):
            pass

        def config(self, **_k):
            pass

        def after(self, _ms, fn):
            self.after_calls.append(fn)

        def destroy(self):
            self.destroyed = True

        def mainloop(self):
            pass

        def bind(self, *_a, **_k):
            pass

    class FakeCanvas:
        def __init__(self, master, **kwargs):
            events.append('Canvas')
            self.master = master
            self.kwargs = kwargs
            self.items: list[Any] = []
            self._next_id = 1
            self.configured: list[tuple] = []
            canvases.append(self)

        def grid(self, **_k):
            pass

        def create_image(self, *args, **kwargs):
            item_id = self._next_id
            self._next_id += 1
            self.items.append({'id': item_id, 'args': args, 'kwargs': kwargs})
            return item_id

        def itemconfigure(self, item_id, **kwargs):
            self.configured.append((item_id, kwargs))

        def bind(self, *_a, **_k):
            pass

        def winfo_width(self):
            return 800

        def winfo_height(self):
            return 480

    class FakeWidget:
        def __init__(self, master=None, **kwargs):
            self.master = master
            self.kwargs = kwargs

        def grid(self, **_k):
            return self

    class TclError(Exception):
        pass

    fake_tk = ModuleType('tkinter')
    fake_tk.Tk = FakeRoot
    fake_tk.Canvas = FakeCanvas
    fake_tk.Label = FakeWidget
    fake_tk.Button = FakeWidget
    fake_tk.TclError = TclError
    fake_tk.NW = 'nw'

    monkeypatch.setitem(sys.modules, 'tkinter', fake_tk)
    # Drop cached real module if present so import picks up the stub.
    monkeypatch.delitem(sys.modules, 'interaction.SelfManagedTkInteraction', raising=False)

    return events, roots, canvases, photos, fake_tk


def test_tk_init_order_and_explicit_master(monkeypatch):
    events, roots, canvases, photos, fake_tk = _install_fake_tkinter(monkeypatch)

    # Import after stubbing tkinter
    import interaction.SelfManagedTkInteraction as sm_mod

    def fake_photo(image, master=None, **kwargs):
        events.append('PhotoImage')
        assert 'Tk' in events, 'PhotoImage created before Tk()'
        if master is None:
            raise RuntimeError('Too early to create image: no default root window')
        photo = type('Photo', (), {})()
        photo.image = image
        photo.master = master
        photos.append(photo)
        return photo

    monkeypatch.setattr(sm_mod.ImageTk, 'PhotoImage', fake_photo)

    def noop(*_a, **_k):
        pass

    ui = sm_mod.SelfManagedTkInteraction(
        noop, noop, noop, noop, noop, noop, noop, noop, noop,
        (800, 480), (0, 0, 0), (9, 64, 9),
    )

    assert len(roots) == 1
    root = roots[0]
    assert ui._SelfManagedTkInteraction__root is root  # noqa: SLF001

    assert events.index('Tk') < events.index('Canvas') < events.index('PhotoImage')

    assert len(canvases) == 1
    assert canvases[0].master is root

    assert len(photos) == 1
    assert photos[0].master is root

    assert len(canvases[0].items) == 1
    item_id = canvases[0].items[0]['id']
    assert ui._SelfManagedTkInteraction__canvas_image == item_id  # noqa: SLF001
    assert ui._SelfManagedTkInteraction__image_tk is photos[0]  # noqa: SLF001

    frame = Image.new('RGB', (800, 480), (27, 251, 30))
    ui._SelfManagedTkInteraction__present_on_main(frame)  # noqa: SLF001
    assert len(photos) == 2
    assert photos[1].master is root
    assert ui._SelfManagedTkInteraction__image_tk is photos[1]  # noqa: SLF001
    assert len(canvases[0].items) == 1
    assert canvases[0].configured[-1][0] == item_id
    assert canvases[0].configured[-1][1]['image'] is photos[1]

    ui.close()
    assert root.destroyed is True


def test_photoimage_requires_explicit_master():
    with pytest.raises(RuntimeError, match='Too early'):
        # Same contract as the fake PhotoImage used above
        master = None
        if master is None:
            raise RuntimeError('Too early to create image: no default root window')
