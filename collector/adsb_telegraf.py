#!/usr/bin/env python3
"""adsb-graphs Telegraf collector.

Fetches dump1090/readsb JSON and emits InfluxDB line protocol on stdout. Two run modes:

  execd (default): Telegraf drives it via STDIN — one collection per newline.
      [[inputs.execd]] command=["python3", ".../adsb_telegraf.py"] signal="STDIN"
  exec (--once):   collect a single batch, print, exit. Fallback for platforms
      where execd misbehaves:  [[inputs.exec]] commands=["... --once"]
"""

import os
import sys
import json
from contextlib import closing
from urllib.request import urlopen

from line_protocol import build_all_lines


# ── config ────────────────────────────────────────────────────────────────────

DEFAULT_CONF = '/usr/share/adsb-graphs/adsb_collector.conf'


def load_config():
    conf = {
        'instance':   os.environ.get('ADSB_INSTANCE', 'localhost'),
        'url':        os.environ.get('ADSB_URL', ''),
        'url_978':    os.environ.get('ADSB_URL_978', ''),
        'url_airspy': os.environ.get('ADSB_URL_AIRSPY', ''),
        'url_signal': os.environ.get('ADSB_URL_1090_SIGNAL', ''),
    }
    path = os.environ.get('ADSB_COLLECTOR_CONF', DEFAULT_CONF)
    if os.path.isfile(path):
        with open(path) as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith('#') or '=' not in line:
                    continue
                key, val = line.split('=', 1)
                key = key.strip().lower()
                val = val.strip().strip('"').strip("'")
                if key == 'instance':
                    conf['instance'] = val
                elif key == 'url':
                    conf['url'] = val
                elif key == 'url_978':
                    conf['url_978'] = val
                elif key == 'url_airspy':
                    conf['url_airspy'] = val
                elif key in ('url_1090_signal', 'url_signal'):
                    conf['url_signal'] = val
    return conf


# ── I/O ──────────────────────────────────────────────────────────────────────

def fetch_json(url, timeout=5.0):
    with closing(urlopen(url, None, timeout)) as fh:
        return json.load(fh)


def collect(conf):
    url = conf['url']
    if not url:
        return []
    try:
        stats = fetch_json(url + '/data/stats.json')
        receiver = fetch_json(url + '/data/receiver.json')
        aircraft_json = fetch_json(url + '/data/aircraft.json')
    except Exception:
        return []

    kwargs = {}
    url_978 = conf.get('url_978', '')
    if url_978:
        try:
            kwargs['receiver_978'] = fetch_json(url_978 + '/data/receiver.json')
            kwargs['aircraft_978'] = fetch_json(url_978 + '/data/aircraft.json')
        except Exception:
            pass

    url_airspy = conf.get('url_airspy', '')
    if url_airspy:
        try:
            kwargs['airspy_stats'] = fetch_json(url_airspy + '/stats.json')
        except Exception:
            pass

    return build_all_lines(stats, receiver, aircraft_json, conf['instance'], **kwargs)


def emit(lines):
    if lines:
        sys.stdout.write('\n'.join(lines) + '\n')
    sys.stdout.flush()


def main():
    conf = load_config()
    if '--once' in sys.argv:
        emit(collect(conf))
        return
    for _ in sys.stdin:
        emit(collect(conf))


if __name__ == '__main__':
    main()
