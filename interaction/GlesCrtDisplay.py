"""OpenGL ES CRT display for Raspberry Pi (pygame + KMSDRM).

All GL calls run on a dedicated present thread. Other threads paste into a
staging canvas and enqueue drop-to-latest frames.
"""

from __future__ import annotations

import logging
import os
import ctypes
import threading
import time
from pathlib import Path
from typing import Optional

from PIL import Image

from core.decorator import override
from interaction.Display import Display
from rendering.crt import CrtSettings, resolve_crt_settings
from rendering.crt_uniforms import crt_settings_to_uniforms

logger = logging.getLogger('piboy.gles')

_SHADER_DIR = Path(__file__).resolve().parent.parent / 'rendering' / 'shaders'


class GlesCrtDisplay(Display):
    """Fullscreen GLES present with optional CRT fragment shader."""

    applies_crt = True

    def __init__(
        self,
        *,
        width: int = 800,
        height: int = 480,
        crt_settings: CrtSettings | None = None,
        init_timeout_s: float = 8.0,
        animate_fps: float = 8.0,
    ):
        self.__width = int(width)
        self.__height = int(height)
        self.__settings = crt_settings or resolve_crt_settings(
            preset='subtle', width=self.__width, height=self.__height,
        )
        self.__animate_fps = max(1.0, float(animate_fps))
        self.__profile = os.environ.get('PIBOY_GL_PROFILE', '').strip() in ('1', 'true', 'yes')

        self.__staging = Image.new('RGB', (self.__width, self.__height), (0, 0, 0))
        self.__defer = 0
        self.__lock = threading.Lock()
        self.__frame_event = threading.Event()
        self.__pending: Optional[Image.Image] = None
        self.__settings_lock = threading.Lock()
        self.__closed = False
        self.__ready = threading.Event()
        self.__init_error: str | None = None

        self.__pygame = None
        self.__gl = None
        self.__program = None
        self.__tex = None
        self.__vbo = None
        self.__uniforms: dict[str, int] = {}

        os.environ.setdefault('SDL_VIDEODRIVER', 'kmsdrm')
        os.environ.setdefault('SDL_OPENGL_ES_DRIVER', '1')
        os.environ.setdefault('PYOPENGL_PLATFORM', 'egl')

        self.__thread = threading.Thread(target=self.__present_loop, name='gles-present', daemon=True)
        self.__thread.start()
        if not self.__ready.wait(timeout=float(init_timeout_s)):
            self.__init_error = self.__init_error or f'GLES init timed out after {init_timeout_s}s'
            self.close()
            raise RuntimeError(self.__init_error)
        if self.__init_error:
            err = self.__init_error
            self.close()
            raise RuntimeError(err)
        logger.info(
            'GlesCrtDisplay %sx%s CRT=%s animate=%.1ffps',
            self.__width, self.__height, self.__settings.preset, self.__animate_fps,
        )

    @property
    def size(self) -> tuple[int, int]:
        return self.__width, self.__height

    def set_crt_settings(self, settings: CrtSettings) -> None:
        with self.__settings_lock:
            self.__settings = settings
        # Force a redraw with new uniforms
        with self.__lock:
            self.__pending = self.__staging.copy()
            self.__frame_event.set()

    def begin_update(self) -> None:
        with self.__lock:
            self.__defer += 1

    def end_update(self) -> None:
        with self.__lock:
            if self.__defer > 0:
                self.__defer -= 1
            if self.__defer == 0:
                self.__enqueue_locked()

    @override
    def show(self, image: Image.Image, x0: int, y0: int):
        rgb = image.convert('RGB')
        with self.__lock:
            if rgb.size == (self.__width, self.__height) and x0 == 0 and y0 == 0:
                self.__staging = rgb
            else:
                self.__staging.paste(rgb, (int(x0), int(y0)))
            if self.__defer == 0:
                self.__enqueue_locked()

    def __enqueue_locked(self) -> None:
        self.__pending = self.__staging.copy()
        self.__frame_event.set()

    @override
    def close(self):
        with self.__lock:
            self.__closed = True
            self.__frame_event.set()
        if self.__thread.is_alive() and threading.current_thread() is not self.__thread:
            self.__thread.join(timeout=3.0)

    def reset(self):
        with self.__lock:
            self.__staging = Image.new('RGB', (self.__width, self.__height), (0, 0, 0))
            self.__enqueue_locked()

    # --- present thread -------------------------------------------------

    def __present_loop(self) -> None:
        try:
            self.__init_gl()
            self.__ready.set()
        except Exception as exc:  # noqa: BLE001
            self.__init_error = str(exc)
            logger.exception('GLES init failed')
            self.__ready.set()
            self.__teardown_gl()
            return

        animate_interval = 1.0 / self.__animate_fps
        next_animate = time.monotonic() + animate_interval
        try:
            while True:
                with self.__lock:
                    if self.__closed:
                        break
                # Wait for frame or animate tick
                timeout = max(0.001, next_animate - time.monotonic())
                self.__frame_event.wait(timeout=timeout)
                self.__frame_event.clear()

                with self.__lock:
                    if self.__closed:
                        break
                    frame = self.__pending
                    self.__pending = None

                now = time.monotonic()
                if frame is not None:
                    self.__upload_and_draw(frame, now)
                    next_animate = now + animate_interval
                elif now >= next_animate:
                    with self.__settings_lock:
                        need_animate = self.__settings.enabled and (
                            self.__settings.grain > 0 or self.__settings.flicker > 0
                        )
                    if need_animate:
                        with self.__lock:
                            frame = self.__staging.copy()
                        self.__upload_and_draw(frame, now)
                    next_animate = now + animate_interval

                # Drain pygame events so KMS stays happy
                pygame = self.__pygame
                if pygame is not None:
                    for event in pygame.event.get():
                        if event.type == pygame.QUIT:
                            with self.__lock:
                                self.__closed = True
        finally:
            self.__teardown_gl()

    def __init_gl(self) -> None:
        import pygame

        self.__pygame = pygame

        pygame.init()
        pygame.display.gl_set_attribute(pygame.GL_CONTEXT_MAJOR_VERSION, 2)
        pygame.display.gl_set_attribute(pygame.GL_CONTEXT_MINOR_VERSION, 0)
        try:
            pygame.display.gl_set_attribute(pygame.GL_CONTEXT_PROFILE_MASK, pygame.GL_CONTEXT_PROFILE_ES)
        except Exception:  # noqa: BLE001
            pass

        pygame.display.set_mode(
            (self.__width, self.__height),
            pygame.OPENGL | pygame.FULLSCREEN | pygame.DOUBLEBUF,
            vsync=1,
        )
        pygame.mouse.set_visible(False)
        try:
            pygame.event.set_grab(True)
        except Exception:  # noqa: BLE001
            pass
        # Import after context exists; force EGL on Pi KMS.
        from OpenGL import GL
        self.__gl = GL
        GL.glViewport(0, 0, self.__width, self.__height)

        vert = (_SHADER_DIR / 'crt.vert').read_text()
        frag = (_SHADER_DIR / 'crt.frag').read_text()
        self.__program = self.__compile(vert, frag)
        GL.glUseProgram(self.__program)

        # Fullscreen triangle strip: pos.xy, uv.xy
        # NDC: (-1,-1)-(1,1); UV: (0,0)-(1,1) with y flipped for PIL top-left
        import array
        verts = array.array('f', [
            # x, y, u, v
            -1.0, -1.0, 0.0, 1.0,
             1.0, -1.0, 1.0, 1.0,
            -1.0,  1.0, 0.0, 0.0,
             1.0,  1.0, 1.0, 0.0,
        ])
        self.__vbo = GL.glGenBuffers(1)
        GL.glBindBuffer(GL.GL_ARRAY_BUFFER, self.__vbo)
        GL.glBufferData(GL.GL_ARRAY_BUFFER, verts.tobytes(), GL.GL_STATIC_DRAW)

        loc_pos = GL.glGetAttribLocation(self.__program, 'a_pos')
        loc_uv = GL.glGetAttribLocation(self.__program, 'a_uv')
        stride = 4 * 4
        GL.glEnableVertexAttribArray(loc_pos)
        GL.glVertexAttribPointer(loc_pos, 2, GL.GL_FLOAT, False, stride, ctypes.c_void_p(0))
        GL.glEnableVertexAttribArray(loc_uv)
        GL.glVertexAttribPointer(loc_uv, 2, GL.GL_FLOAT, False, stride, ctypes.c_void_p(8))

        self.__tex = GL.glGenTextures(1)
        GL.glBindTexture(GL.GL_TEXTURE_2D, self.__tex)
        GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MIN_FILTER, GL.GL_LINEAR)
        GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MAG_FILTER, GL.GL_LINEAR)
        GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_WRAP_S, GL.GL_CLAMP_TO_EDGE)
        GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_WRAP_T, GL.GL_CLAMP_TO_EDGE)
        GL.glTexImage2D(
            GL.GL_TEXTURE_2D, 0, GL.GL_RGB, self.__width, self.__height, 0,
            GL.GL_RGB, GL.GL_UNSIGNED_BYTE, None,
        )

        names = [
            'u_tex', 'u_resolution', 'u_time', 'u_enabled', 'u_phosphor_floor',
            'u_scanlines', 'u_vignette', 'u_grain', 'u_glare', 'u_flicker', 'u_glow',
            'u_curvature', 'u_rounded_corners', 'u_bezel_inset', 'u_grain_seed',
        ]
        self.__uniforms = {n: GL.glGetUniformLocation(self.__program, n) for n in names}
        GL.glUniform1i(self.__uniforms['u_tex'], 0)

    def __compile(self, vert_src: str, frag_src: str):
        GL = self.__gl
        assert GL is not None

        def compile_shader(src: str, stype):
            sid = GL.glCreateShader(stype)
            GL.glShaderSource(sid, src)
            GL.glCompileShader(sid)
            if not GL.glGetShaderiv(sid, GL.GL_COMPILE_STATUS):
                log = GL.glGetShaderInfoLog(sid)
                raise RuntimeError(f'shader compile failed: {log}')
            return sid

        vs = compile_shader(vert_src, GL.GL_VERTEX_SHADER)
        fs = compile_shader(frag_src, GL.GL_FRAGMENT_SHADER)
        prog = GL.glCreateProgram()
        GL.glAttachShader(prog, vs)
        GL.glAttachShader(prog, fs)
        GL.glLinkProgram(prog)
        if not GL.glGetProgramiv(prog, GL.GL_LINK_STATUS):
            log = GL.glGetProgramInfoLog(prog)
            raise RuntimeError(f'shader link failed: {log}')
        GL.glDeleteShader(vs)
        GL.glDeleteShader(fs)
        return prog

    def __upload_and_draw(self, frame: Image.Image, now: float) -> None:
        GL = self.__gl
        pygame = self.__pygame
        if GL is None or pygame is None or self.__program is None:
            return
        t0 = time.perf_counter() if self.__profile else 0.0
        rgb = frame.convert('RGB')
        if rgb.size != (self.__width, self.__height):
            rgb = rgb.resize((self.__width, self.__height), Image.Resampling.BILINEAR)
        data = rgb.tobytes()

        GL.glUseProgram(self.__program)
        GL.glBindTexture(GL.GL_TEXTURE_2D, self.__tex)
        GL.glTexSubImage2D(
            GL.GL_TEXTURE_2D, 0, 0, 0, self.__width, self.__height,
            GL.GL_RGB, GL.GL_UNSIGNED_BYTE, data,
        )

        with self.__settings_lock:
            settings = self.__settings
        uniforms = crt_settings_to_uniforms(settings, time_s=now)
        self.__apply_uniforms(uniforms)

        GL.glViewport(0, 0, self.__width, self.__height)
        GL.glClearColor(0.0, 0.0, 0.0, 1.0)
        GL.glClear(GL.GL_COLOR_BUFFER_BIT)
        GL.glDrawArrays(GL.GL_TRIANGLE_STRIP, 0, 4)
        pygame.display.flip()
        if self.__profile:
            logger.info('gl present %sms', round((time.perf_counter() - t0) * 1000, 1))

    def __apply_uniforms(self, uniforms: dict) -> None:
        GL = self.__gl
        assert GL is not None
        u = self.__uniforms
        GL.glUniform2f(u['u_resolution'], *uniforms['u_resolution'])
        GL.glUniform1f(u['u_time'], uniforms['u_time'])
        for key in (
            'u_enabled', 'u_phosphor_floor', 'u_scanlines', 'u_vignette', 'u_grain',
            'u_glare', 'u_flicker', 'u_glow', 'u_curvature', 'u_rounded_corners',
            'u_bezel_inset', 'u_grain_seed',
        ):
            loc = u.get(key, -1)
            if loc is not None and loc >= 0:
                GL.glUniform1f(loc, float(uniforms[key]))

    def __teardown_gl(self) -> None:
        pygame = self.__pygame
        GL = self.__gl
        # Leave a black screen so the last UI frame does not freeze on the panel.
        try:
            if GL is not None and pygame is not None:
                GL.glViewport(0, 0, self.__width, self.__height)
                GL.glClearColor(0.0, 0.0, 0.0, 1.0)
                GL.glClear(GL.GL_COLOR_BUFFER_BIT)
                pygame.display.flip()
        except Exception:  # noqa: BLE001
            pass
        try:
            if GL is not None and self.__tex is not None:
                GL.glDeleteTextures(1, [self.__tex])
        except Exception:  # noqa: BLE001
            pass
        try:
            if GL is not None and self.__program is not None:
                GL.glDeleteProgram(self.__program)
        except Exception:  # noqa: BLE001
            pass
        try:
            if pygame is not None:
                pygame.display.quit()
                pygame.quit()
        except Exception:  # noqa: BLE001
            pass
        self.__tex = None
        self.__program = None
        self.__pygame = None
        self.__gl = None
        logger.info('GlesCrtDisplay torn down')
