"""Tests for FramePresenter and RenderGate (no Tk required)."""
from __future__ import annotations

from PIL import Image

from interaction.frame_presenter import FramePresenter, RenderGate


class _FakeScheduler:
    def __init__(self):
        self.queue: list = []

    def __call__(self, fn):
        self.queue.append(fn)

    def run_one(self):
        fn = self.queue.pop(0)
        fn()

    def run_all(self):
        while self.queue:
            self.run_one()


def _frame(color=(10, 20, 30)) -> Image.Image:
    return Image.new('RGB', (800, 480), color)


def test_presenter_never_publishes_empty_or_black_placeholder():
    presented = []
    sched = _FakeScheduler()

    def present(img: Image.Image):
        assert img.size == (800, 480)
        # Must be a real composed color, not a cleared black intermediate we invented.
        presented.append(img.copy())

    p = FramePresenter(sched, present)
    src = _frame((27, 251, 30))
    p.submit(src)
    assert p.pending_count == 1
    assert presented == []  # not yet flushed
    sched.run_all()
    assert len(presented) == 1
    assert presented[0].getpixel((0, 0)) == (27, 251, 30)
    assert p.pending_count == 0


def test_queue_holds_at_most_one_pending_frame():
    presented = []
    sched = _FakeScheduler()
    p = FramePresenter(sched, lambda img: presented.append(img.copy()))
    p.submit(_frame((1, 0, 0)))
    p.submit(_frame((2, 0, 0)))
    p.submit(_frame((3, 0, 0)))
    assert p.pending_count == 1
    assert p.dropped_count == 2
    sched.run_all()
    assert len(presented) == 1
    assert presented[0].getpixel((0, 0)) == (3, 0, 0)


def test_new_frame_replaces_only_after_processing_completes():
    """While flush runs, a new submit is queued and presented next — never mid-swap blank."""
    order = []
    sched = _FakeScheduler()
    p_holder: dict = {}

    def present(img: Image.Image):
        order.append(('present', img.getpixel((0, 0))[0]))
        # During present, a newer frame arrives.
        if img.getpixel((0, 0))[0] == 1:
            p_holder['p'].submit(_frame((2, 0, 0)))

    p = FramePresenter(sched, present)
    p_holder['p'] = p
    p.submit(_frame((1, 0, 0)))
    sched.run_all()
    assert order == [('present', 1), ('present', 2)]


def test_render_gate_rejects_parallel_renders():
    gate = RenderGate()
    count = {'n': 0}

    def work():
        count['n'] += 1
        if count['n'] == 1:
            # Overlapping request coalesces; same render_fn re-runs once after.
            assert gate.request(lambda: None) is False

    assert gate.request(work) is True
    assert count['n'] == 2
    assert gate.busy is False


def test_repeated_requests_do_not_start_parallel_render():
    gate = RenderGate()
    active = {'n': 0, 'max': 0}
    phase = {'i': 0}

    def work():
        active['n'] += 1
        active['max'] = max(active['max'], active['n'])
        phase['i'] += 1
        if phase['i'] == 1:
            gate.request(lambda: None)
        active['n'] -= 1

    gate.request(work)
    assert active['max'] == 1
    assert gate.busy is False

def test_shutdown_stops_pending_update():
    presented = []
    sched = _FakeScheduler()
    p = FramePresenter(sched, lambda img: presented.append(img))
    p.submit(_frame((9, 9, 9)))
    assert p.pending_count == 1
    p.shutdown()
    assert p.pending_count == 0
    sched.run_all()
    assert presented == []

    gate = RenderGate()
    gate.shutdown()
    assert gate.request(lambda: presented.append('x')) is False
    assert presented == []


def test_submit_copies_so_caller_mutation_does_not_affect_pending():
    presented = []
    sched = _FakeScheduler()
    p = FramePresenter(sched, lambda img: presented.append(img.copy()))
    src = _frame((5, 5, 5))
    p.submit(src)
    src.paste((0, 0, 0), (0, 0, 800, 480))  # mutate after submit
    sched.run_all()
    assert presented[0].getpixel((100, 100)) == (5, 5, 5)
