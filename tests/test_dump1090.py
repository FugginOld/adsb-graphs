import dump1090


# helpers
def ac(**kw):
    """Minimal aircraft dict; override any field via kwargs."""
    defaults = {'seen': 10, 'messages': 10, 'rssi': -20.0}
    defaults.update(kw)
    return defaults


# ── Cycle 1: empty aircraft ───────────────────────────────────────────────────

def test_empty_aircraft_returns_zeros_and_no_quartiles():
    result = dump1090.compute_aircraft_stats([], None, None)
    assert result['total'] == 0
    assert result['with_pos'] == 0
    assert result['mlat'] == 0
    assert result['tisb'] == 0
    assert result['gps'] == 0
    assert result['range_quartiles'] is None
    assert result['signal_quartiles'] is None


# ── Cycle 2: aircraft counting ────────────────────────────────────────────────

def test_total_counts_aircraft_seen_within_60s():
    aircraft = [ac(seen=59), ac(seen=60), ac(seen=61)]
    result = dump1090.compute_aircraft_stats(aircraft, None, None)
    assert result['total'] == 1  # only seen=59 qualifies

def test_with_pos_counts_aircraft_with_recent_position():
    aircraft = [
        ac(seen_pos=59, lat=1.0, lon=1.0),
        ac(seen_pos=60, lat=1.0, lon=1.0),
        ac(),  # no seen_pos
    ]
    result = dump1090.compute_aircraft_stats(aircraft, None, None)
    assert result['with_pos'] == 1

def test_mlat_counted_separately_from_gps():
    aircraft = [
        ac(seen_pos=10, lat=1.0, lon=1.0, mlat=['lat']),
        ac(seen_pos=10, lat=1.0, lon=1.0),
    ]
    result = dump1090.compute_aircraft_stats(aircraft, None, None)
    assert result['mlat'] == 1
    assert result['gps'] == 1

def test_tisb_counted_separately():
    aircraft = [
        ac(seen_pos=10, lat=1.0, lon=1.0, tisb=['lat']),
        ac(seen_pos=10, lat=1.0, lon=1.0),
    ]
    result = dump1090.compute_aircraft_stats(aircraft, None, None)
    assert result['tisb'] == 1
    assert result['gps'] == 1


# ── Cycle 3: signal filtering ─────────────────────────────────────────────────

def test_signal_excluded_when_rssi_below_threshold():
    aircraft = [ac(rssi=-50.0, messages=10, seen=5)]
    result = dump1090.compute_aircraft_stats(aircraft, None, None)
    assert result['signal_quartiles'] is None

def test_signal_excluded_when_too_few_messages():
    aircraft = [ac(rssi=-20.0, messages=4, seen=5)]
    result = dump1090.compute_aircraft_stats(aircraft, None, None)
    assert result['signal_quartiles'] is None

def test_signal_excluded_for_tisb_source():
    aircraft = [ac(rssi=-20.0, messages=10, seen=5, type='tisb_icao')]
    result = dump1090.compute_aircraft_stats(aircraft, None, None)
    assert result['signal_quartiles'] is None

def test_signal_excluded_for_adsr_source():
    aircraft = [ac(rssi=-20.0, messages=10, seen=5, type='adsr_icao')]
    result = dump1090.compute_aircraft_stats(aircraft, None, None)
    assert result['signal_quartiles'] is None

def test_signal_quartiles_computed_from_valid_aircraft():
    # Four aircraft with known rssi values → verify quartile keys present and min/max correct
    aircraft = [
        ac(rssi=-10.0, messages=10, seen=5),
        ac(rssi=-20.0, messages=10, seen=5),
        ac(rssi=-30.0, messages=10, seen=5),
        ac(rssi=-40.0, messages=10, seen=5),
    ]
    result = dump1090.compute_aircraft_stats(aircraft, None, None)
    q = result['signal_quartiles']
    assert q is not None
    assert q['min'] == -40.0
    assert q['max'] == -10.0
    assert q['min'] <= q['q1'] <= q['median'] <= q['q3'] <= q['max']


# ── Cycle 4: range quartiles ──────────────────────────────────────────────────

def test_range_quartiles_none_when_no_receiver_position_and_adsb():
    # rlat/rlon=None → distances are 0, but we still get quartiles (distance=0)
    aircraft = [ac(seen_pos=10, lat=1.0, lon=1.0)]
    result = dump1090.compute_aircraft_stats(aircraft, None, None)
    assert result['range_quartiles'] is not None
    assert result['range_quartiles']['min'] == 0

def test_range_uses_great_circle_distance():
    # London (51.5, -0.1) to Paris (48.8, 2.35) ≈ 340 km
    receiver_lat, receiver_lon = 51.5, -0.1
    paris_lat, paris_lon = 48.8, 2.35
    aircraft = [ac(seen_pos=10, lat=paris_lat, lon=paris_lon, type='adsb_icao')]
    result = dump1090.compute_aircraft_stats(aircraft, receiver_lat, receiver_lon)
    q = result['range_quartiles']
    assert q is not None
    assert 330_000 < q['max'] < 360_000  # metres, ~340 km

def test_tisb_aircraft_excluded_from_range_stats():
    aircraft = [ac(seen_pos=10, lat=48.8, lon=2.35, tisb=['lat'])]
    result = dump1090.compute_aircraft_stats(aircraft, 51.5, -0.1)
    assert result['range_quartiles'] is None

def test_978_mode_caps_range_at_350_nmi():
    # 350 nmi = 648,020 m; use a distance just over that
    # Receiver at 0,0; aircraft at ~6 degrees lat ≈ 667 km
    aircraft = [ac(seen_pos=10, lat=6.0, lon=0.0)]
    result = dump1090.compute_aircraft_stats(aircraft, 0.0, 0.0, mode='978')
    assert result['range_quartiles'] is None  # excluded because > 350 nmi
