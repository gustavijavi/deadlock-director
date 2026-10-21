import pytest

from deadlockdirector import console, interpolation
from deadlockdirector.obs import auth_response
from deadlockdirector.sequence import History, Sequence


def test_ease_endpoints():
    for mode in interpolation.BLEND_NAMES:
        if mode in ('hold', 'spline'):
            continue
        assert interpolation.ease(mode, 0.0) == pytest.approx(0.0)
        assert interpolation.ease(mode, 1.0) == pytest.approx(1.0)


def test_linear_and_hold():
    times, values = [0.0, 2.0], [0.0, 10.0]
    assert interpolation.evaluate(times, values, ['linear', 'linear'], 1.0) == pytest.approx(5.0)
    assert interpolation.evaluate(times, values, ['hold', 'linear'], 1.9) == 0.0
    assert interpolation.evaluate(times, values, ['linear', 'linear'], -1) == 0.0
    assert interpolation.evaluate(times, values, ['linear', 'linear'], 5) == 10.0


def test_spline_passes_through_keys_and_is_smooth():
    times = [0.0, 1.0, 3.0, 4.0]
    values = [[0, 0, 0], [100, 0, 0], [100, 200, 0], [0, 200, 50]]
    blends = ['spline'] * 4
    for t, v in zip(times, values):
        assert interpolation.evaluate(times, values, blends, t) == pytest.approx(v)
    # Velocity should be continuous across the keyframe at t=1.
    eps = 1e-4
    before = interpolation.evaluate(times, values, blends, 1 - eps)
    at = interpolation.evaluate(times, values, blends, 1)
    after = interpolation.evaluate(times, values, blends, 1 + eps)
    v_in = [(a - b) / eps for a, b in zip(at, before)]
    v_out = [(a - b) / eps for a, b in zip(after, at)]
    assert v_in == pytest.approx(v_out, rel=1e-2, abs=1e-1)


def test_rotation_takes_shortest_path():
    seq = Sequence()
    seq.track('rotation').add(0, [0, 170, 0], 'linear')
    seq.track('rotation').add(1, [0, -170, 0], 'linear')
    yaw = seq.evaluate(0.5)['rotation'][1]
    assert interpolation.wrap180(yaw) == pytest.approx(180.0)


def test_rotation_full_spin_preserved():
    values = interpolation.unwrap_angles([[0, 0, 0], [0, 180, 0], [0, 360, 0]])
    assert [v[1] for v in values] == [0, 180, 360]


def test_sequence_roundtrip_and_ticks(tmp_path):
    seq = Sequence()
    seq.name = 'Shot'
    seq.start_tick = 5000
    seq.track('position').add(0, [1, 2, 3])
    seq.track('position').add(2.5, [4, 5, 6])
    seq.track('speed').add(1, 0.5)
    path = tmp_path / 'shot.json'
    seq.save(str(path))
    loaded = Sequence.load(str(path))
    assert loaded.to_dict() == seq.to_dict()
    assert loaded.duration == 2.5
    assert loaded.tick_at(1.0) == 5064
    assert loaded.speed_at(10) == 0.5


def test_add_replaces_same_time():
    seq = Sequence()
    track = seq.track('fov')
    track.add(1.0, 90)
    track.add(1.00001, 70)
    assert len(track.keyframes) == 1 and track.keyframes[0].value == 70


def test_history_undo_redo():
    seq = Sequence()
    history = History(seq)
    history.push()
    seq.track('fov').add(0, 90)
    assert history.undo() and seq.is_empty()
    assert history.redo() and not seq.is_empty()


@pytest.mark.parametrize('line,expected', [
    ('spec_goto 123.5 -456.0 200 12.5 90', [123.5, -456.0, 200, 12.5, 90, 0]),
    ('setpos 1 2 3;setang 4 5 6', [1, 2, 3, 4, 5, 6]),
    ('  10.0 20.0 30.0 -5.0 179.9', [10, 20, 30, -5, 179.9, 0]),
    ('\x1b[32mspec_goto 1e2 2 3 4 5\x1b[0m', [100, 2, 3, 4, 5, 0]),
])
def test_parse_camera(line, expected):
    state = console.parse_camera(line)
    assert state.position + state.rotation == pytest.approx(expected)


def test_parse_camera_rejects_noise():
    assert console.parse_camera('Unknown command spec_pos') is None
    assert console.parse_camera('fps 144 frametime 6.9') is None


def test_parse_tick():
    assert console.parse_tick('Demo: x.dem\nCurrent tick: 12345') == 12345
    assert console.parse_tick('nothing here') is None


def test_render_templates():
    out = console.render('spec_goto {x:.1f} {y:.1f} {z:.1f}', x=1, y=2.25, z=-3)
    assert out == 'spec_goto 1.0 2.2 -3.0'
    assert console.render('cmd {missing}', x=1) == 'cmd {missing}'
    assert console.split_commands('a 1; b 2\nc') == ['a 1', 'b 2', 'c']
    assert console.sanitize('quit\nrcon') == 'quit rcon'


def test_obs_auth_matches_reference():
    # Reference value computed per the obs-websocket v5 protocol docs.
    import base64, hashlib
    secret = base64.b64encode(hashlib.sha256(b'pwsalt').digest()).decode()
    expected = base64.b64encode(hashlib.sha256((secret + 'chal').encode()).digest()).decode()
    assert auth_response('pw', 'salt', 'chal') == expected
