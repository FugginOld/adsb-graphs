import adsb_telegraf as t


# ── adsb_messages line ────────────────────────────────────────────────────────

def sample_total():
    return {
        'end': 1719240000.0,
        'local': {'accepted': [100, 20, 5], 'strong_signals': 12},
        'remote': {'accepted': [3, 0], 'basestation': 7},
        'cpr': {'global_ok': 400, 'local_ok': 89},
    }


def test_messages_line_basic_fields():
    line = t.messages_line(sample_total(), 'localhost')
    assert line.startswith('adsb_messages,instance=localhost ')
    assert 'local_accepted=125i' in line       # 100+20+5
    assert 'remote_accepted=10i' in line        # 3+0+7 basestation
    assert 'positions=489i' in line             # 400+89
    assert 'strong_signals=12i' in line
    assert line.endswith(' 1719240000000000000')  # end * 1e9


def test_messages_line_position_fallback():
    total = {'end': 1.0, 'cpr': {'global_ok': 0, 'local_ok': 0}, 'position_count_total': 42}
    line = t.messages_line(total, 'localhost')
    assert 'positions=42i' in line


def test_messages_line_none_when_no_total():
    assert t.messages_line(None, 'localhost') is None
    assert t.messages_line({}, 'localhost') is None  # no 'end'


# ── adsb_aircraft line ────────────────────────────────────────────────────────

def aircraft_json():
    return {
        'now': 1719240000.0,
        'aircraft': [
            {'seen': 1, 'messages': 50, 'rssi': -20.0, 'seen_pos': 1, 'lat': 51.0, 'lon': 0.1},
            {'seen': 2, 'messages': 50, 'rssi': -22.0, 'seen_pos': 2, 'lat': 52.0, 'lon': 0.2,
             'mlat': ['lat', 'lon']},
            {'seen': 5, 'messages': 50, 'rssi': -30.0},  # no position
            {'seen': 90, 'messages': 50, 'rssi': -30.0},  # stale, not counted
        ],
    }


def test_aircraft_line_counts():
    line = t.aircraft_line(aircraft_json(), 51.5, 0.0, 'localhost')
    assert line.startswith('adsb_aircraft,instance=localhost ')
    assert 'total=3i' in line       # three with seen<60
    assert 'with_pos=2i' in line    # two with seen_pos<60
    assert 'mlat=1i' in line
    assert 'gps=1i' in line
    assert line.endswith(' 1719240000000000000')


def test_aircraft_line_none_when_empty():
    assert t.aircraft_line({}, None, None, 'localhost') is None


# ── build_lines integration ───────────────────────────────────────────────────

def test_build_lines_emits_both_measurements():
    stats = {'total': sample_total()}
    receiver = {'lat': 51.5, 'lon': 0.0}
    lines = t.build_lines(stats, receiver, aircraft_json(), 'localhost')
    assert len(lines) == 2
    assert any(l.startswith('adsb_messages,') for l in lines)
    assert any(l.startswith('adsb_aircraft,') for l in lines)


def test_build_lines_tolerates_missing_inputs():
    assert t.build_lines(None, None, None, 'localhost') == []


# ── tag escaping ──────────────────────────────────────────────────────────────

def test_esc_tag_escapes_specials():
    assert t.esc_tag('my host,a=b') == 'my\\ host\\,a\\=b'
