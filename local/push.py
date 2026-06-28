#!/usr/bin/env python3
"""Local demo pusher: sim -> real collector -> InfluxDB. Stdlib only.

Runs the data simulator in-process, polls it through the real collector
(`adsb_telegraf.collect`), and writes the resulting line protocol straight
to InfluxDB so Grafana has something to graph. Driven by docker-compose.yml.

Env:
    INFLUX_WRITE_URL  default http://influxdb:8086/write?db=adsb-graphs&precision=ns
    PUSH_INTERVAL     seconds between writes (default 5)
    SIM_PORT          in-process sim port (default 8080)
"""
import os
import sys
import threading
import time
import urllib.parse
import urllib.request
from http.server import HTTPServer

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'collector'))
import sim                                  # noqa: E402
from adsb_telegraf import load_config, collect  # noqa: E402

INFLUX = os.environ.get('INFLUX_WRITE_URL',
                        'http://influxdb:8086/write?db=adsb-graphs&precision=ns')
DB = os.environ.get('INFLUX_DB', 'adsb-graphs')
BASE = INFLUX.split('/write', 1)[0]
INTERVAL = float(os.environ.get('PUSH_INTERVAL', '5'))
SIM_PORT = int(os.environ.get('SIM_PORT', '8080'))


def write(lines):
    body = ('\n'.join(lines) + '\n').encode()
    req = urllib.request.Request(INFLUX, data=body, method='POST')
    with urllib.request.urlopen(req, timeout=5) as r:
        return r.status


def ensure_db():
    """CREATE DATABASE with a quoted name (hyphen-safe). Retries until influx is up."""
    q = urllib.parse.urlencode({'q': 'CREATE DATABASE "%s"' % DB}).encode()
    for _ in range(60):
        try:
            req = urllib.request.Request(BASE + '/query', data=q, method='POST')
            with urllib.request.urlopen(req, timeout=5):
                print('database "%s" ready' % DB, flush=True)
                return
        except Exception:                     # noqa: BLE001 — influx still booting
            time.sleep(2)
    raise SystemExit('influxdb never came up at %s' % BASE)


def main():
    threading.Thread(
        target=HTTPServer(('127.0.0.1', SIM_PORT), sim.Handler).serve_forever,
        daemon=True).start()
    time.sleep(1)

    base = 'http://127.0.0.1:%d' % SIM_PORT
    os.environ.setdefault('ADSB_INSTANCE', 'sim')
    os.environ.setdefault('ADSB_URL', base)
    os.environ.setdefault('ADSB_URL_978', base)
    os.environ.setdefault('ADSB_URL_AIRSPY', base)
    os.environ.setdefault('ADSB_COLLECTOR_CONF', '/nonexistent')
    conf = load_config()

    ensure_db()
    print('pushing sim -> %s every %ss' % (INFLUX, INTERVAL), flush=True)
    while True:
        try:
            lines = collect(conf)
            if lines:
                print('wrote %d lines -> HTTP %s' % (len(lines), write(lines)), flush=True)
        except Exception as e:                # noqa: BLE001 — demo loop, keep alive
            print('push error: %r' % e, flush=True)
        time.sleep(INTERVAL)


if __name__ == '__main__':
    main()
