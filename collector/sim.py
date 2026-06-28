#!/usr/bin/env python3
"""Local data simulator for adsb-graphs.

Serves dump1090/readsb/airspy-shaped JSON so the collector can run with no
real receiver. Stdlib only, no deps.

Usage:
    python collector/sim.py            # serve on 127.0.0.1:8080
    python collector/sim.py 9090       # custom port
    python collector/sim.py --selftest # feed one snapshot through the real parsers

Point the collector at it (same base works for all three bands):
    ADSB_URL=http://127.0.0.1:8080 \
    ADSB_URL_978=http://127.0.0.1:8080 \
    ADSB_URL_AIRSPY=http://127.0.0.1:8080 \
    python collector/adsb_telegraf.py

Routes:
    /data/stats.json      1090/978 stats
    /data/receiver.json   receiver lat/lon
    /data/aircraft.json   aircraft table (positions jitter each request)
    /stats.json           airspy stats
"""
import json
import math
import random
import sys
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

RECEIVER_LAT = 40.64
RECEIVER_LON = -73.78


def _aircraft_table(now, n=18, seed=None):
    """n synthetic aircraft: mix of gps / mlat / tisb, jittered positions."""
    rng = random.Random(seed)
    out = []
    for i in range(n):
        bearing = rng.uniform(0, 2 * math.pi)
        dist_deg = rng.uniform(0.05, 2.5)          # ~3..160 nm spread
        lat = RECEIVER_LAT + dist_deg * math.cos(bearing)
        lon = RECEIVER_LON + dist_deg * math.sin(bearing)
        kind = rng.choices(['gps', 'mlat', 'tisb', 'stale'],
                           weights=[60, 15, 10, 15])[0]
        ac = {
            'hex': '%06x' % (0xa00000 + i),
            'messages': rng.randint(5, 5000),
            'rssi': round(rng.uniform(-32.0, -8.0), 1),
        }
        if kind == 'stale':                         # seen>60 → excluded by stats
            ac['seen'] = rng.uniform(70, 300)
            out.append(ac)
            continue
        ac['seen'] = round(rng.uniform(0, 30), 1)
        ac['seen_pos'] = round(rng.uniform(0, 30), 1)
        ac['lat'] = round(lat, 5)
        ac['lon'] = round(lon, 5)
        if kind == 'mlat':
            ac['mlat'] = ['lat', 'lon']
            ac['type'] = 'mlat'
        elif kind == 'tisb':
            ac['tisb'] = ['lat', 'lon']
            ac['type'] = 'tisb_icao'
        else:
            ac['type'] = 'adsb_icao'
        out.append(ac)
    return {'now': now, 'messages': rng.randint(100000, 9000000), 'aircraft': out}


def _stats(now):
    return {
        'total': {
            'end': now,
            'local': {'accepted': [random.randint(1000, 5000)],
                      'strong_signals': random.randint(0, 200),
                      'signal': round(random.uniform(-14, -8), 1),
                      'noise': round(random.uniform(-34, -28), 1)},
            'remote': {'accepted': [random.randint(0, 500)], 'basestation': 0},
            'cpr': {'global_ok': random.randint(500, 2000),
                    'local_ok': random.randint(200, 1000)},
            'cpu': {'demod': random.randint(800, 1200),
                    'reader': random.randint(100, 300),
                    'background': random.randint(20, 80)},
            'tracks': {'all': random.randint(200, 400),
                       'single_message': random.randint(5, 40)},
        },
        'last1min': {
            'end': now,
            'max_distance': random.randint(150000, 400000),
            'local': {'signal': round(random.uniform(-14, -8), 1),
                      'noise': round(random.uniform(-34, -28), 1)},
            'gain_db': round(random.uniform(40, 60), 1),
        },
    }


def _receiver():
    return {'lat': RECEIVER_LAT, 'lon': RECEIVER_LON, 'version': 'sim',
            'refresh': 1000, 'history': 0}


def _airspy(now):
    def q():
        base = sorted(round(random.uniform(-30, -5), 1) for _ in range(7))
        return dict(zip(('min', 'p5', 'q1', 'median', 'q3', 'p95', 'max'), base))
    return {
        'now': now,
        'rssi': q(), 'snr': q(), 'noise': q(),
        'preamble_filter': random.randint(2, 8),
        'samplerate': 20000000,
        'gain': round(random.uniform(10, 21), 1),
        'lost_buffers': random.randint(0, 5),
        'max_aircraft_count': random.randint(10, 40),
        'df_counts': [random.randint(0, 9000) for _ in range(30)],
    }


def snapshot():
    """One full poll's worth of JSON — used by both the server and selftest."""
    now = time.time()
    return {
        '/data/stats.json': _stats(now),
        '/data/receiver.json': _receiver(),
        '/data/aircraft.json': _aircraft_table(now),
        '/stats.json': _airspy(now),
    }


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = snapshot().get(self.path)
        if body is None:
            self.send_error(404)
            return
        payload = json.dumps(body).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *_):           # quiet
        pass


def selftest():
    """Feed a snapshot through the real parsers; assert lines come out."""
    import os
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from line_protocol import build_all_lines
    s = snapshot()
    lines = build_all_lines(
        s['/data/stats.json'], s['/data/receiver.json'], s['/data/aircraft.json'],
        'sim', receiver_978=s['/data/receiver.json'],
        aircraft_978=s['/data/aircraft.json'], airspy_stats=s['/stats.json'])
    measurements = {l.split(',', 1)[0] for l in lines}
    assert lines, 'no lines produced'
    for m in ('adsb_messages', 'adsb_aircraft', 'adsb_range', 'adsb_signal',
              'adsb_cpu', 'adsb_tracks', 'adsb_gain', 'airspy'):
        assert m in measurements, 'missing measurement: %s' % m
    print('selftest OK — %d lines, measurements: %s' %
          (len(lines), ', '.join(sorted(measurements))))


def main():
    if '--selftest' in sys.argv:
        selftest()
        return
    port = int(next((a for a in sys.argv[1:] if a.isdigit()), 8080))
    srv = HTTPServer(('127.0.0.1', port), Handler)
    print('adsb-graphs sim serving on http://127.0.0.1:%d  (Ctrl-C to stop)' % port)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        srv.shutdown()


if __name__ == '__main__':
    main()
