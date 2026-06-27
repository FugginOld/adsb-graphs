import line_protocol as t
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


# ── build_lines_978 ───────────────────────────────────────────────────────────

def aircraft_978_json():
    return {
        'now': 1719240000.0,
        'messages': 42000,
        'aircraft': [
            {'seen': 1, 'messages': 10, 'rssi': -18.0, 'seen_pos': 1, 'lat': 51.0, 'lon': 0.1},
            {'seen': 3, 'messages': 10, 'rssi': -25.0, 'seen_pos': 3, 'lat': 52.0, 'lon': 0.2,
             'tisb': ['lat', 'lon']},
            {'seen': 90, 'messages': 10, 'rssi': -20.0},  # stale
        ],
    }


def test_build_lines_978_emits_expected_measurements():
    receiver = {'lat': 51.5, 'lon': 0.0}
    lines = t.build_lines_978(receiver, aircraft_978_json(), 'localhost')
    measurements = {l.split(',')[0] for l in lines}
    assert 'adsb_messages' in measurements
    assert 'adsb_aircraft' in measurements
    assert 'adsb_range' in measurements
    assert 'adsb_signal' in measurements


def test_build_lines_978_uses_978_band_tag():
    receiver = {'lat': 51.5, 'lon': 0.0}
    lines = t.build_lines_978(receiver, aircraft_978_json(), 'localhost')
    tagged = [l for l in lines if l.startswith('adsb_aircraft') or l.startswith('adsb_range') or l.startswith('adsb_signal')]
    assert all('band=978' in l for l in tagged)


def test_build_lines_978_messages_count():
    aj = {'now': 1719240000.0, 'messages': 42000, 'aircraft': []}
    lines = t.build_lines_978(None, aj, 'localhost')
    msg = next((l for l in lines if l.startswith('adsb_messages')), None)
    assert msg is not None
    assert 'messages=42000i' in msg
    assert 'band=978' in msg
    assert msg.endswith(' 1719240000000000000')


def test_build_lines_978_tisb_counted_separately():
    # aircraft[0]: seen=1, seen_pos=1, no mlat/tisb key → gps=1
    # aircraft[1]: seen=3, seen_pos=3, tisb=['lat','lon'] → tisb=1
    # aircraft[2]: seen=90 → not counted
    receiver = {'lat': 51.5, 'lon': 0.0}
    lines = t.build_lines_978(receiver, aircraft_978_json(), 'localhost')
    ac = next(l for l in lines if l.startswith('adsb_aircraft'))
    assert 'tisb=1i' in ac
    assert 'gps=1i' in ac
    assert 'total=2i' in ac
    assert 'with_pos=2i' in ac


def test_build_lines_978_tolerates_missing():
    assert t.build_lines_978(None, None, 'localhost') == []
    assert t.build_lines_978(None, {'now': 1.0}, 'localhost') == []  # no 'aircraft' key


# ── build_lines_airspy ────────────────────────────────────────────────────────

def sample_airspy_stats():
    return {
        'now': 1719240000.0,
        'rssi': {'min': -30.0, 'p5': -28.0, 'q1': -25.0, 'median': -22.0,
                 'q3': -18.0, 'p95': -12.0, 'max': -3.0},
        'snr':  {'min': 5.0,   'p5': 6.0,   'q1': 8.0,   'median': 12.0,
                 'q3': 16.0,   'p95': 22.0,  'max': 25.0},
        'noise':{'min': -35.0, 'p5': -34.0, 'q1': -32.0, 'median': -30.0,
                 'q3': -28.0,  'p95': -25.0, 'max': -20.0},
        'preamble_filter': 0.001,
        'samplerate': 20000000,
        'gain': 21,
        'lost_buffers': 0,
        'max_aircraft_count': 45,
        'df_counts': [100, 0, 0, 0, 50, 200, 0, 0, 0, 0, 0, 30,
                      0, 0, 0, 0, 5, 8000, 0, 0, 10, 2],
    }


def test_build_lines_airspy_emits_single_line():
    lines = t.build_lines_airspy(sample_airspy_stats(), 'localhost')
    assert len(lines) == 1
    assert lines[0].startswith('airspy,instance=localhost ')


def test_build_lines_airspy_rssi_quartiles():
    line = t.build_lines_airspy(sample_airspy_stats(), 'localhost')[0]
    assert 'rssi_min=-30' in line
    assert 'rssi_p5=-28' in line
    assert 'rssi_q1=-25' in line
    assert 'rssi_median=-22' in line
    assert 'rssi_q3=-18' in line
    assert 'rssi_p95=-12' in line
    assert 'rssi_max=-3' in line


def test_build_lines_airspy_snr_and_noise_quartiles():
    line = t.build_lines_airspy(sample_airspy_stats(), 'localhost')[0]
    assert 'snr_median=12' in line
    assert 'noise_median=-30' in line


def test_build_lines_airspy_misc_fields():
    line = t.build_lines_airspy(sample_airspy_stats(), 'localhost')[0]
    assert 'preamble_filter=' in line
    assert 'samplerate=' in line
    assert 'gain=21' in line
    assert 'lost_buffers=0i' in line
    assert 'max_aircraft_count=45i' in line


def test_build_lines_airspy_df_counts():
    line = t.build_lines_airspy(sample_airspy_stats(), 'localhost')[0]
    assert 'df0=100i' in line
    assert 'df4=50i' in line
    assert 'df17=8000i' in line
    assert 'df21=2i' in line
    # sparse: df1 is zero and should not appear
    assert 'df1=' not in line


def test_build_lines_airspy_timestamp():
    line = t.build_lines_airspy(sample_airspy_stats(), 'localhost')[0]
    assert line.endswith(' 1719240000000000000')


def test_build_lines_airspy_tolerates_missing_sections():
    # partial stats — only rssi, no snr/noise/df
    stats = {'now': 1719240000.0, 'rssi': {'min': -30.0, 'median': -22.0, 'max': -3.0}}
    line = t.build_lines_airspy(stats, 'localhost')[0]
    assert 'rssi_min=-30' in line
    assert 'snr_' not in line
    assert 'noise_' not in line


def test_build_lines_airspy_tolerates_none():
    assert t.build_lines_airspy(None, 'localhost') == []


def test_build_lines_airspy_tolerates_missing_now():
    assert t.build_lines_airspy({'rssi': {'min': -30.0}}, 'localhost') == []


def test_build_lines_airspy_tolerates_empty_fields():
    assert t.build_lines_airspy({'now': 1.0}, 'localhost') == []


# ── build_all_lines ───────────────────────────────────────────────────────────

def test_build_all_lines_1090_only():
    stats = {'total': sample_total()}
    lines = t.build_all_lines(stats, None, aircraft_json(), 'localhost')
    measurements = {l.split(',')[0] for l in lines}
    assert 'adsb_messages' in measurements
    assert 'adsb_aircraft' in measurements
    assert 'airspy' not in measurements


def test_build_all_lines_with_978():
    stats = {'total': sample_total()}
    lines = t.build_all_lines(stats, None, aircraft_json(), 'localhost',
                              aircraft_978=aircraft_978_json())
    measurements = {l.split(',')[0] for l in lines}
    assert 'adsb_messages' in measurements
    assert any('band=978' in l for l in lines)


def test_build_all_lines_with_airspy():
    lines = t.build_all_lines(None, None, None, 'localhost',
                              airspy_stats=sample_airspy_stats())
    assert any(l.startswith('airspy,') for l in lines)


# ── tag escaping ──────────────────────────────────────────────────────────────

def test_esc_tag_escapes_specials():
    assert t.esc_tag('my host,a=b') == 'my\\ host\\,a\\=b'
