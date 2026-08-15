from core.decorator import override
from interaction.Input import Input


class NullInput(Input):
    """No physical keypad / rotary — touch-only or headless fallback."""

    def __init__(self):
        nop = lambda: None
        super().__init__(nop, nop, nop, nop, nop, nop, nop, nop, nop)

    @override
    def close(self):
        pass
