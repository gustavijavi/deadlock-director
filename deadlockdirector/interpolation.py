"""Easing curves and keyframe interpolation helpers.

Values are either floats or lists of floats (vectors). Every function here is
pure so it can be unit-tested without Qt or the game.
"""
import math

BLEND_MODES = [
    ('spline', 'Spline (smooth path)'),
    ('linear', 'Linear'),
    ('smooth', 'Smooth step'),
    ('ease_in', 'Ease in'),
    ('ease_out', 'Ease out'),
    ('ease_in_out', 'Ease in/out'),
    ('hold', 'Hold (cut)'),
]
BLEND_NAMES = [name for name, _ in BLEND_MODES]


def ease(mode, u):
    """Map a linear 0..1 progress value through the named easing curve."""
    u = min(1.0, max(0.0, u))
    if mode == 'smooth':
        return u * u * (3.0 - 2.0 * u)
    if mode == 'ease_in':
        return u * u * u
    if mode == 'ease_out':
        v = 1.0 - u
        return 1.0 - v * v * v
    if mode == 'ease_in_out':
        if u < 0.5:
            return 4.0 * u * u * u
        v = -2.0 * u + 2.0
        return 1.0 - v * v * v / 2.0
    if mode == 'hold':
        return 0.0
    return u


def lerp(a, b, u):
    if isinstance(a, (list, tuple)):
        return [x + (y - x) * u for x, y in zip(a, b)]
    return a + (b - a) * u


def _sub(a, b):
    if isinstance(a, (list, tuple)):
        return [x - y for x, y in zip(a, b)]
    return a - b


def _scale(a, s):
    if isinstance(a, (list, tuple)):
        return [x * s for x in a]
    return a * s


def _hermite(p0, p1, m0, m1, u):
    u2 = u * u
    u3 = u2 * u
    h00 = 2 * u3 - 3 * u2 + 1
    h10 = u3 - 2 * u2 + u
    h01 = -2 * u3 + 3 * u2
    h11 = u3 - u2
    if isinstance(p0, (list, tuple)):
        return [h00 * a + h10 * b + h01 * c + h11 * d for a, b, c, d in zip(p0, m0, p1, m1)]
    return h00 * p0 + h10 * m0 + h01 * p1 + h11 * m1


def _tangent(times, values, i):
    """Time-aware finite-difference tangent (units per second) at keyframe i."""
    n = len(values)
    if n < 2:
        return _scale(values[0], 0.0)
    if i == 0:
        lo, hi = 0, 1
    elif i == n - 1:
        lo, hi = n - 2, n - 1
    else:
        lo, hi = i - 1, i + 1
    dt = times[hi] - times[lo]
    if dt <= 0:
        return _scale(values[i], 0.0)
    return _scale(_sub(values[hi], values[lo]), 1.0 / dt)


def wrap180(angle):
    """Wrap an angle into the (-180, 180] range."""
    angle = math.fmod(angle, 360.0)
    if angle > 180.0:
        angle -= 360.0
    elif angle <= -180.0:
        angle += 360.0
    return angle


def unwrap_angles(values):
    """Make a list of [pitch, yaw, roll] rotations continuous so that blending
    always takes the shortest way round instead of spinning through 360."""
    result = []
    for value in values:
        value = list(value)
        if result:
            previous = result[-1]
            value = [p + wrap180(v - p) for p, v in zip(previous, value)]
        result.append(value)
    return result


def evaluate(times, values, blends, t):
    """Evaluate a keyframed curve at time t.

    times  -- sorted keyframe times
    values -- keyframe values (float or list)
    blends -- blend mode of each keyframe, controlling the segment *after* it
    """
    n = len(times)
    if n == 0:
        return None
    if t <= times[0] or n == 1:
        return values[0]
    if t >= times[-1]:
        return values[-1]
    # Binary search for the segment containing t.
    lo, hi = 0, n - 1
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if times[mid] <= t:
            lo = mid
        else:
            hi = mid
    t0, t1 = times[lo], times[hi]
    span = t1 - t0
    if span <= 0:
        return values[hi]
    u = (t - t0) / span
    mode = blends[lo]
    if mode == 'hold':
        return values[lo]
    if mode == 'spline':
        m0 = _scale(_tangent(times, values, lo), span)
        m1 = _scale(_tangent(times, values, hi), span)
        return _hermite(values[lo], values[hi], m0, m1, u)
    return lerp(values[lo], values[hi], ease(mode, u))
