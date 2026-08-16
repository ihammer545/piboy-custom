#version 100
precision mediump float;

/*
  Order mirrors CRTRenderer.process (rendering/crt.py):
  phosphor → glow (cheap blur skip; mix) → barrel sample → scanlines →
  grain → vignette → glare → flicker → rounded glass / bezel.

  Barrel: for display UV, sample UI at display_to_ui (crt_geometry.py):
    xn = uv.x*2-1; yn = uv.y*2-1;
    f = 1.0 + u_curvature * (xn*xn + yn*yn);
    sample_uv = (xn*f, yn*f) * 0.5 + 0.5;
*/

varying vec2 v_uv;
uniform sampler2D u_tex;
uniform vec2 u_resolution;
uniform float u_time;
uniform float u_enabled;          // 0 = passthrough
uniform float u_phosphor_floor;
uniform float u_scanlines;
uniform float u_vignette;
uniform float u_grain;
uniform float u_glare;
uniform float u_flicker;
uniform float u_glow;
uniform float u_curvature;
uniform float u_rounded_corners;  // px
uniform float u_bezel_inset;      // px
uniform float u_grain_seed;

float hash(vec2 p) {
  return fract(sin(dot(p, vec2(127.1, 311.7)) + u_grain_seed) * 43758.5453);
}

float sdRoundBox(vec2 p, vec2 b, float r) {
  vec2 q = abs(p) - b + r;
  return min(max(q.x, q.y), 0.0) + length(max(q, 0.0)) - r;
}

void main() {
  vec2 uv = v_uv;

  if (u_enabled < 0.5) {
    gl_FragColor = texture2D(u_tex, uv);
    return;
  }

  // Display-space → UI sample (same as crt_geometry.display_to_ui)
  vec2 xn = uv * 2.0 - 1.0;
  float r2 = dot(xn, xn);
  float f = 1.0 + u_curvature * r2;
  vec2 sample_n = xn * f;
  vec2 sample_uv = sample_n * 0.5 + 0.5;
  float outside = step(1.001, max(abs(sample_n.x), abs(sample_n.y)));

  vec3 col = texture2D(u_tex, clamp(sample_uv, 0.0, 1.0)).rgb;

  // Phosphor floor (green-black lift)
  vec3 ph = vec3(u_phosphor_floor * 0.35, u_phosphor_floor * 1.0, u_phosphor_floor * 0.4);
  col = max(col, ph);

  // Cheap glow: mix with slightly blurred neighbor taps
  if (u_glow > 0.001) {
    vec2 px = 1.0 / u_resolution;
    vec3 blur = col;
    blur += texture2D(u_tex, clamp(sample_uv + vec2(px.x, 0.0), 0.0, 1.0)).rgb;
    blur += texture2D(u_tex, clamp(sample_uv - vec2(px.x, 0.0), 0.0, 1.0)).rgb;
    blur += texture2D(u_tex, clamp(sample_uv + vec2(0.0, px.y), 0.0, 1.0)).rgb;
    blur += texture2D(u_tex, clamp(sample_uv - vec2(0.0, px.y), 0.0, 1.0)).rgb;
    blur *= 0.2;
    col = mix(col, blur, clamp(u_glow * 0.35, 0.0, 1.0));
  }

  // Scanlines (multiply dark even rows)
  if (u_scanlines > 0.001) {
    float line = mod(floor(uv.y * u_resolution.y), 2.0);
    float dark = 1.0 - u_scanlines * 0.55 * (1.0 - line);
    col *= dark;
  }

  // Grain
  if (u_grain > 0.001) {
    float g = hash(uv * u_resolution + floor(u_time * 5.0));
    col += (g - 0.5) * u_grain * 0.35;
  }

  // Vignette
  if (u_vignette > 0.001) {
    float v = length(xn);
    float vig = smoothstep(0.95, 0.35, v);
    vig = mix(1.0, vig, clamp(u_vignette, 0.0, 1.0));
    col *= vig;
  }

  // Glare (screen-ish highlight upper-left)
  if (u_glare > 0.001) {
    float g = exp(-length(uv - vec2(0.28, 0.22)) * 4.0);
    col = col + (1.0 - col) * (g * u_glare * 0.5);
  }

  // Flicker
  if (u_flicker > 0.001) {
    float phase = sin(u_time * 2.2) * 0.5 + sin(u_time * 5.1) * 0.5;
    col *= clamp(1.0 + phase * u_flicker, 0.94, 1.06);
  }

  // Rounded glass + bezel
  float inset = u_bezel_inset;
  vec2 half_res = u_resolution * 0.5;
  vec2 p = (uv * u_resolution) - half_res;
  vec2 box = half_res - vec2(inset);
  float rr = max(u_rounded_corners, 0.0);
  float d = sdRoundBox(p, box, rr);
  float glass = 1.0 - smoothstep(-1.0, 1.0, d);
  col *= glass;
  // faint rim
  float rim = (1.0 - smoothstep(-2.0, 2.0, abs(d))) * 0.15 * glass;
  col += vec3(0.0, rim, rim * 0.5);

  if (outside > 0.5) {
    col = vec3(0.0);
  }

  gl_FragColor = vec4(clamp(col, 0.0, 1.0), 1.0);
}
