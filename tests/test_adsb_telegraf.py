import adsb_telegraf as t
from adsb_stats import compute_aircraft_stats


# ── fixtures ──────────────────────────────────────────────────────────────────

def sample_total():
    return {
        'end': 1719240000.0,
        'local': {'accepted': [100, 20, 5], 'strong_signals': 12},
        'remote': {'accepted': [3, 0], 'basestation': 7},
        'cpr': {'global_ok': 400, 'local_ok': 89},
    }


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


# ── adsb_messages ─────────────────────────────────────────────────────────────

def test_messages_line_basic_fields():
    line = t.messages_line(sample_total(), 'localhost')
    assert line.startswith('adsb_messages,instance=localhost ')
    assert 'local_accepted=125i' in line       # 100+20+5
    assert 'remote_accepted=10i' in line        # 3+0+7 basestation
    assert 'positions=489i' in line             # 400+89
    assert 'strong_signals=12i' in line
    assert line.endswith(' 1719240000000000000')


def test_messages_line_position_fallback():
    total = {'end': 1.0, 'cpr': {'global_ok': 0, 'local_ok': 0}, 'position_count_total': 42}
    line = t.messages_line(total, 'localhost')
    assert 'positions=42i' in line


def test_messages_line_none_when_no_total():
    assert t.messages_line(None, 'localhost') is None
    assert t.messages_line({}, 'localhost') is None  # no 'end'


# ── adsb_aircraft ─────────────────────────────────────────────────────────────

def test_aircraft_line_counts():
    aj = aircraft_json()
    ac_stats = compute_aircraft_stats(aj['aircraft'], 51.5, 0.0)
    line = t.aircraft_line(ac_stats, aj['now'], 'localhost')
    assert line.startswith('adsb_aircraft,instance=localhost,band=1090 ')
    assert 'total=3i' in line
    assert 'with_pos=2i' in line
    assert 'mlat=1i' in line
    assert 'gps=1i' in line
    assert line.endswith(' 1719240000000000000')


def test_aircraft_line_none_when_empty():
    assert t.aircraft_line(None, 1719240000.0, 'localhost') is None


# ── adsb_range ────────────────────────────────────────────────────────────────

def test_range_line_with_quartiles():
    ac_stats = {
        'range_quartiles': {
            'min': 4200.0, 'q1': 98000.0, 'median': 210400.0,
            'q3': 288000.0, 'max': 345600.0,
        },
    }
    line = t.range_line(ac_stats, None, 1719240000.0, 'localhost')
    assert line.startswith('adsb_range,instance=localhost,band=1090 ')
    assert 'max_range=345600' in line
    assert 'median=210400' in line
    assert 'q1=98000' in line
    assert 'q3=288000' in line
    assert 'min=4200' in line
    assert line.endswith(' 1719240000000000000')


def test_range_line_max_from_last1min():
    ac_stats = {
        'range_quartiles': {
            'min': 4200.0, 'q1': 98000.0, 'median': 210400.0,
            'q3': 288000.0, 'max': 345600.0,
        },
    }
    last1min = {'max_distance': 400000.0}
    line = t.range_line(ac_stats, last1min, 1719240000.0, 'localhost')
    assert 'max_range=400000' in line  # last1min overrides rq['max']


def test_range_line_no_quartiles_emits_max_zero():
    ac_stats = {'range_quartiles': None}
    line = t.range_line(ac_stats, None, 1719240000.0, 'localhost')
    assert 'max_range=0' in line
    assert 'median' not in line


# ── adsb_signal ───────────────────────────────────────────────────────────────

def test_signal_line_full():
    ac_stats = {
        'signal_quartiles': {
            'min': -24.0, 'q1': -22.0, 'median': -18.2,
            'q3': -14.0, 'max': -3.1,
        },
    }
    last1min = {'local': {'signal': -19.0, 'noise': -30.1}}
    line = t.signal_line(ac_stats, last1min, 1719240000.0, 'localhost')
    assert line.startswith('adsb_signal,instance=localhost,band=1090 ')
    assert 'signal=-19' in line
    assert 'noise=-30.1' in line
    assert 'median=-18.2' in line
    assert 'peak_signal=-3.1' in line
    assert 'min_signal=-24' in line
    assert line.endswith(' 1719240000000000000')


def test_signal_line_none_when_no_data():
    assert t.signal_line({}, None, 1719240000.0, 'localhost') is None
    assert t.signal_line({'signal_quartiles': None}, None, 1719240000.0, 'localhost') is None


# ── adsb_cpu ──────────────────────────────────────────────────────────────────

def test_cpu_line_basic():
    total = {
        'end': 1719240000.0,
        'cpu': {'demod': 12345, 'reader': 678, 'background': 90},
    }
    line = t.cpu_line(total, 'localhost')
    assert line.startswith('adsb_cpu,instance=localhost ')
    assert 'demod=12345i' in line
    assert 'reader=678i' in line
    assert 'background=90i' in line
    assert line.endswith(' 1719240000000000000')


def test_cpu_line_none_when_missing():
    assert t.cpu_line(None, 'localhost') is None
    assert t.cpu_line({'end': 1.0}, 'localhost') is None  # no cpu key


# ── adsb_tracks ───────────────────────────────────────────────────────────────

def test_tracks_line_basic():
    total = {'end': 1719240000.0, 'tracks': {'all': 500, 'single_message': 120}}
    line = t.tracks_line(total, 'localhost')
    assert line.startswith('adsb_tracks,instance=localhost ')
    assert 'all=500i' in line
    assert 'single_message=120i' in line
    assert line.endswith(' 1719240000000000000')


def test_tracks_line_none_when_missing():
    assert t.tracks_line(None, 'localhost') is None
    assert t.tracks_line({'end': 1.0}, 'localhost') is None  # no tracks key


# ── adsb_gain ─────────────────────────────────────────────────────────────────

def test_gain_line_from_adaptive():
    stats = {'last1min': {'end': 1719240000.0, 'adaptive': {'gain_db': 49.6}}}
    line = t.gain_line(stats, 'localhost')
    assert 'adsb_gain,instance=localhost' in line
    assert 'gain_db=49.6' in line
    assert line.endswith(' 1719240000000000000')


def test_gain_line_from_last1min_direct():
    stats = {'last1min': {'end': 1719240000.0, 'gain_db': 48.0}}
    line = t.gain_line(stats, 'localhost')
    assert 'gain_db=48' in line


def test_gain_line_from_top_level():
    stats = {'now': 1719240000.0, 'gain_db': 40.0}
    line = t.gain_line(stats, 'localhost')
    assert 'gain_db=40' in line


def test_gain_line_none_when_missing():
    assert t.gain_line(None, 'localhost') is None
    assert t.gain_line({}, 'localhost') is None


# ── build_lines integration ───────────────────────────────────────────────────

def test_build_lines_emits_core_measurements():
    stats = {'total': sample_total()}
    receiver = {'lat': 51.5, 'lon': 0.0}
    lines = t.build_lines(stats, receiver, aircraft_json(), 'localhost')
    measurements = {l.split(',')[0] for l in lines}
    assert 'adsb_messages' in measurements
    assert 'adsb_aircraft' in measurements
    assert 'adsb_range' in measurements
    assert 'adsb_signal' in measurements


def test_build_lines_emits_cpu_and_tracks_when_present():
    total = dict(sample_total())
    total['cpu'] = {'demod': 1000, 'reader': 200, 'background': 50}
    total['tracks'] = {'all': 300, 'single_message': 80}
    stats = {'total': total}
    lines = t.build_lines(stats, None, None, 'localhost')
    measurements = {l.split(',')[0] for l in lines}
    assert 'adsb_cpu' in measurements
    assert 'adsb_tracks' in measurements


def test_build_lines_emits_gain_when_present():
    stats = {
        'total': sample_total(),
        'last1min': {'end': 1719240000.0, 'adaptive': {'gain_db': 49.6}},
    }
    lines = t.build_lines(stats, None, None, 'localhost')
    assert any('adsb_gain' in l for l in lines)


def test_build_lines_tolerates_missing_inputs():
    assert t.build_lines(None, None, None, 'localhost') == []


# ── tag escaping ──────────────────────────────────────────────────────────────

def test_esc_tag_escapes_specials():
    assert t.esc_tag('my host,a=b') == 'my\\ host\\,a\\=b'
