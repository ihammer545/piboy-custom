#!/usr/bin/env python3
"""
Phase-0 hardware spike: SDL2 KMSDRM + OpenGL ES fullscreen clear (+ optional textured quad).

Run on shelter-terminal (stop piboy first):

  sudo apt-get install -y libsdl2-2.0-0 libegl1 libgles2 \\
      libsdl2-dev libegl-dev libgles-dev

  cd ~/piboy
  .venv/bin/pip install 'pygame>=2.5' 'PyOpenGL>=3.1'
  # hide console cursor if needed:
  #   sudo bash scripts/hide-fb-cursor.sh
  SDL_VIDEODRIVER=kmsdrm .venv/bin/python scripts/spike_gles_kms.py

Go: green clear visible on 5\" panel, clean exit, then framebuffer piboy still works.
Exit: 0 ok, 1 runtime fail, 2 missing deps.
"""

from __future__ import annotations

import array
import ctypes
import os
import sys
import time
from pathlib import Path


def _compile(gl, vert_src: str, frag_src: str):
    def one(src, stype):
        sid = gl.glCreateShader(stype)
        gl.glShaderSource(sid, src)
        gl.glCompileShader(sid)
        if not gl.glGetShaderiv(sid, gl.GL_COMPILE_STATUS):
            raise RuntimeError(gl.glGetShaderInfoLog(sid))
        return sid

    vs = one(vert_src, gl.GL_VERTEX_SHADER)
    fs = one(frag_src, gl.GL_FRAGMENT_SHADER)
    prog = gl.glCreateProgram()
    gl.glAttachShader(prog, vs)
    gl.glAttachShader(prog, fs)
    gl.glLinkProgram(prog)
    if not gl.glGetProgramiv(prog, gl.GL_LINK_STATUS):
        raise RuntimeError(gl.glGetProgramInfoLog(prog))
    gl.glDeleteShader(vs)
    gl.glDeleteShader(fs)
    return prog


def main() -> int:
    os.environ.setdefault('SDL_VIDEODRIVER', 'kmsdrm')
    os.environ.setdefault('SDL_OPENGL_ES_DRIVER', '1')

    try:
        import pygame
        from OpenGL import GL
    except ImportError as exc:
        print(f'missing dependency: {exc}', file=sys.stderr)
        return 2

    width, height = 800, 480
    print(f'SDL_VIDEODRIVER={os.environ.get("SDL_VIDEODRIVER")}')
    pygame.init()
    try:
        pygame.display.gl_set_attribute(pygame.GL_CONTEXT_MAJOR_VERSION, 2)
        pygame.display.gl_set_attribute(pygame.GL_CONTEXT_MINOR_VERSION, 0)
        pygame.display.gl_set_attribute(pygame.GL_CONTEXT_PROFILE_MASK, pygame.GL_CONTEXT_PROFILE_ES)
    except Exception as exc:  # noqa: BLE001
        print(f'GL attribute warning: {exc}')

    try:
        pygame.display.set_mode(
            (width, height),
            pygame.OPENGL | pygame.FULLSCREEN | pygame.DOUBLEBUF,
            vsync=1,
        )
    except Exception as exc:  # noqa: BLE001
        print(f'FAILED set_mode: {exc}', file=sys.stderr)
        pygame.quit()
        return 1

    print('window ok — clear green 2s')
    GL.glViewport(0, 0, width, height)
    GL.glClearColor(0.05, 0.45, 0.08, 1.0)
    GL.glClear(GL.GL_COLOR_BUFFER_BIT)
    pygame.display.flip()
    time.sleep(2.0)

    shader_dir = Path(__file__).resolve().parent.parent / 'rendering' / 'shaders'
    try:
        prog = _compile(
            GL,
            (shader_dir / 'passthrough.vert').read_text(),
            (shader_dir / 'passthrough.frag').read_text(),
        )
        GL.glUseProgram(prog)
        from PIL import Image, ImageDraw
        img = Image.new('RGB', (width, height), (0, 20, 0))
        draw = ImageDraw.Draw(img)
        draw.rectangle((40, 40, width - 40, height - 40), outline=(27, 251, 30), width=3)
        draw.text((80, 200), 'GLES SPIKE OK', fill=(27, 251, 30))

        tex = GL.glGenTextures(1)
        GL.glBindTexture(GL.GL_TEXTURE_2D, tex)
        GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MIN_FILTER, GL.GL_LINEAR)
        GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MAG_FILTER, GL.GL_LINEAR)
        GL.glTexImage2D(
            GL.GL_TEXTURE_2D, 0, GL.GL_RGB, width, height, 0,
            GL.GL_RGB, GL.GL_UNSIGNED_BYTE, img.tobytes(),
        )
        verts = array.array('f', [
            -1.0, -1.0, 0.0, 1.0,
             1.0, -1.0, 1.0, 1.0,
            -1.0,  1.0, 0.0, 0.0,
             1.0,  1.0, 1.0, 0.0,
        ])
        vbo = GL.glGenBuffers(1)
        GL.glBindBuffer(GL.GL_ARRAY_BUFFER, vbo)
        GL.glBufferData(GL.GL_ARRAY_BUFFER, verts.tobytes(), GL.GL_STATIC_DRAW)
        loc_pos = GL.glGetAttribLocation(prog, 'a_pos')
        loc_uv = GL.glGetAttribLocation(prog, 'a_uv')
        GL.glEnableVertexAttribArray(loc_pos)
        GL.glVertexAttribPointer(loc_pos, 2, GL.GL_FLOAT, False, 16, None)
        GL.glEnableVertexAttribArray(loc_uv)
        GL.glVertexAttribPointer(loc_uv, 2, GL.GL_FLOAT, False, 16, ctypes.c_void_p(8))
        GL.glUniform1i(GL.glGetUniformLocation(prog, 'u_tex'), 0)
        GL.glClear(GL.GL_COLOR_BUFFER_BIT)
        GL.glDrawArrays(GL.GL_TRIANGLE_STRIP, 0, 4)
        pygame.display.flip()
        print('textured passthrough — hold 3s (Esc to skip)')
    except Exception as exc:  # noqa: BLE001
        print(f'texture phase skipped: {exc}')
        print('(clear-only is enough to validate KMS if green was visible)')

    deadline = time.time() + 3.0
    while time.time() < deadline:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                deadline = 0
            if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                deadline = 0
        time.sleep(0.05)

    pygame.display.quit()
    pygame.quit()
    print('CLEAN EXIT — re-test: .venv/bin/python piboy.py with driver framebuffer')
    print('If OK: set display_config.driver: gles and crt.preset: subtle')
    return 0


if __name__ == '__main__':
    sys.exit(main())
