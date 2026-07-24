from PIL import Image

from core.decorator import override
from interaction.Display import Display
from interaction.Input import Input
from interaction.UnifiedInteraction import UnifiedInteraction


class NullInteraction(UnifiedInteraction):
    """Headless display/input for tests and environments without Tk."""

    def __init__(self, resolution: tuple[int, int], background: tuple[int, int, int]):
        Input.__init__(self, lambda: None, lambda: None, lambda: None, lambda: None,
                       lambda: None, lambda: None, lambda: None, lambda: None, lambda: None)
        self.__resolution = resolution
        self.__background = background
        self.__image = Image.new('RGB', resolution, background)

    @override
    def show(self, image: Image.Image, x0: int, y0: int):
        self.__image.paste(image, (x0, y0))

    @override
    def close(self):
        pass

    @property
    def image(self) -> Image.Image:
        return self.__image
