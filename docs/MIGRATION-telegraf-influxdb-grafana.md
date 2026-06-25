# Migration Plan: collectd + RRDtool + PNG → Telegraf → InfluxDB v1.x → Grafana

Status: **proposed** · Target: Raspberry Pi + common SBCs + generic Debian/Ubuntu (arm, arm64, amd64)

---

## 1. Why migrate

The current stack couples three concerns into one fixed pipeline:

| Concern | Current | Limitation |
|---|---|---|
| Collect | `collectd` + custom Python plugins | Pinned to collectd's lifecycle, hard-coded disk/interface device lists |
| Store | RRDtool round-robin files | Fixed retention/resolution baked at create time; colors-in-PNG forces 6× render cost for themes |
| Visualize | `graphs1090.sh` renders PNGs every cycle | No zoom/pan, no ad-hoc range, CPU burned on every render, theme = N× the work |

Target stack separates them:

```
SDR decoder (readsb / dump1090-fa / dump978 / airspy_adsb)
        │  stats.json / aircraft.json / receiver.json   (unchanged)
        ▼
Telegraf  ── inputs.execd (ported collector)  + native inputs.{cpu,mem,disk,diskio,net,temp}
        │  InfluxDB line protocol
        ▼
InfluxDB v1.x   (database: graphs1090, retention policies / continuous queries)
        │  InfluxQL
        ▼
Grafana   (provisioned datasource + dashboards; renders on demand, themes are free)
```

**Net wins:** live zoom/pan on any range, alerting, auto-detected system metrics (no manual `disk=`/`ether=`), themes become a Grafana toggle (zero extra storage/CPU), and all retained history at full fidelity.

**The SDR pipeline itself does not change.** We replace only collection, storage, and the viewer.

---

## 2. What we keep vs. replace

| File / component | Fate | Notes |
|---|---|---|
| `lib/dump1090.py` `compute_aircraft_stats()`, `greatcircle()`, `perc()`, `_quartile_dict()` | **Reuse** | Already pure functions (Issue 1 refactor). Move into the new collector. |
| `lib/dump1090.py` collectd dispatch glue | Replace | Becomes line-protocol emission. |
| `lib/system_stats.py` (`/proc/meminfo`) | Replace | `inputs.mem` covers it natively. |
| `config/collectd.conf` built-in plugins (cpu/df/disk/interface/table) | Replace | `inputs.{cpu,disk,diskio,net,temp}` — auto-detect, no device lists. |
| `lib/dump1090.db` (RRD type defs) | Drop | InfluxDB is schemaless. |
| `scripts/graphs1090.sh` (PNG render) | Drop | Grafana dashboards replace it. |
| `scripts/service-graphs1090.sh` (render loop) | Drop | No render loop needed. |
| `config/http/*.conf` (lighttpd vhost) | Optional keep | Only if you want the old PNG viewer during transition, or to reverse-proxy Grafana. |
| Receiver autodetect logic in `install.sh` (readsb/dump1090-fa/etc.) | **Reuse** | Same detection feeds the collector's URL. |
| RRD history in `/var/lib/collectd/rrd` | See §7 | Optional one-shot import; default is start-fresh. |

---

## 3. Target repo layout

```
graphs1090/
├── install.sh                         # rewritten: add repos, install, provision, autodetect
├── uninstall.sh                       # rewritten: remove new stack (+ optional old-stack purge)
├── collector/
│   ├── adsb_telegraf.py               # ported compute core → InfluxDB line protocol (stdin-driven, execd)
│   └── adsb_collector.conf.example    # URL / URL_978 / URL_AIRSPY / instance config
├── telegraf/
│   ├── telegraf.conf                  # [agent] + [[outputs.influxdb]]
│   └── telegraf.d/
│       ├── 10-adsb.conf               # [[inputs.execd]] → adsb_telegraf.py
│       └── 20-system.conf             # cpu/mem/disk/diskio/net/temp
├── influxdb/
│   ├── retention.iql                  # CREATE DATABASE + retention policies
│   └── downsample.iql                 # OPTIONAL continuous queries (multi-year)
├── grafana/
│   └── provisioning/
│       ├── datasources/influxdb.yaml
│       └── dashboards/
│           ├── provider.yaml
│           ├── adsb.json
│           └── system.json
├── docs/
│   └── MIGRATION-telegraf-influxdb-grafana.md   # this file
└── (legacy lib/, scripts/, config/ removed in Phase D)
```

---

## 4. Data model mapping (RRD → InfluxDB)

One measurement per logical group; `instance` (and `host`) as tags; original JSON `now`/`end` timestamps preserved.

| InfluxDB measurement | Fields | Source | Counter? |
|---|---|---|---|
| `adsb_messages` | `local_accepted`, `remote_accepted`, `positions`, `strong_signals`, `messages_978`, `local_accepted_<df>`, `remote_accepted_<df>` | `stats.json total` | **counter** → `non_negative_derivative` at query time |
| `adsb_tracks` | `all`, `single_message` | `stats.json total.tracks` | counter |
| `adsb_cpu` | `demod`, `reader`, `background`, `airspy` | `stats.json total.cpu`, airspy proc | counter (ms) |
| `adsb_aircraft` | `total`, `with_pos`, `mlat`, `tisb`, `gps` (+ `*_978`) | `compute_aircraft_stats()` | gauge |
| `adsb_range` | `max_range`, `median`, `q1`, `q3`, `min` (+ `*_978`) | `compute_aircraft_stats()` | gauge (metres) |
| `adsb_signal` | `signal`, `noise`, `median`, `peak_signal`, `min_signal`, `q1`, `q3` (+ `*_978`) | `handle_signal_stuff()` / quartiles | gauge (dBFS) |
| `adsb_gain` | `gain_db` | `stats.json` adaptive/gain | gauge |
| `airspy` | `rssi_*`, `snr_*`, `noise_*` quartiles, `preamble_filter`, `samplerate`, `gain`, `lost_buffers`, `max_aircraft_count`, `df_<n>` | airspy `stats.json` | mixed |
| `cpu`, `mem`, `disk`, `diskio`, `net`, `temp` | native Telegraf fields | native inputs | mixed |

**Counter handling:** RRD's `DERIVE` stored the per-second rate. InfluxDB convention stores the raw cumulative value and derives the rate in the query (`non_negative_derivative(...)`), which also tolerates decoder restarts (counter resets). Range/signal/aircraft were `GAUGE` and stay raw.

**Range units:** store metres (as today); convert to nautical/statute/metric in the Grafana panel, replacing the `range=`/`range2=` config knobs.

---

## 5. The collector (`collector/adsb_telegraf.py`)

Single script replaces both Python collectd plugins for ADS-B data. Design:

1. Reads config (instance name, `URL`, `URL_978`, `URL_AIRSPY`, `URL_1090_SIGNAL`) from `adsb_collector.conf` / env — same values `install.sh` already autodetects.
2. Fetches `stats.json`, `aircraft.json`, `receiver.json` (same endpoints as today).
3. **Reuses the existing, tested pure functions** verbatim: `compute_aircraft_stats`, `greatcircle`, `perc`, `_quartile_dict`. This keeps one source of truth for the math; no behavioral drift from the current graphs.
4. Emits InfluxDB **line protocol** to stdout, timestamped with the JSON's `now`/`end` (nanoseconds).
5. Runs under Telegraf **`inputs.execd`** (persistent process; Telegraf signals it each interval). Falls back to `inputs.exec` (re-spawn each 60s) on platforms where execd misbehaves — at 60s cadence the spawn cost is negligible.

Example output:

```
adsb_aircraft,instance=localhost total=42i,with_pos=30i,mlat=2i,tisb=1i,gps=27i 1719240000000000000
adsb_range,instance=localhost max_range=345600,median=210400,q1=98000,q3=288000,min=4200 1719240000000000000
adsb_signal,instance=localhost median=-18.2,peak_signal=-3.1,min_signal=-24.0,noise=-30.1,signal=-19.0 1719240000000000000
adsb_messages,instance=localhost local_accepted=1234567i,remote_accepted=0i,positions=78900i,strong_signals=12i 1719240000000000000
adsb_cpu,instance=localhost demod=12345i,reader=678i,background=90i 1719240000000000000
```

System metrics (`cpu`, `mem`, `disk`, `diskio`, `net`, `temp`) come from native Telegraf inputs — **no custom code**, and they auto-detect devices, eliminating the hard-coded `mmcblk0/sda/...` disk list and the manual `ether=`/`wifi=` interface config.

---

## 6. Multi-platform / SBC considerations

| Concern | Approach |
|---|---|
| **Packages** | Add InfluxData apt repo (`telegraf`, `influxdb` 1.x) + Grafana apt repo. All publish armhf/arm64/amd64 — covers Pi 3/4/5, Le Potato, Odroid, x86. |
| **InfluxDB v1.x availability** | Pinned from InfluxData's repo (`influxdb` 1.8.x is the last v1 line, still maintained for security). Document the pin so v2/v3 isn't pulled by accident. |
| **CPU temperature** | `inputs.temp` (gopsutil) works on most x86 + many SBCs. Pi/SBC thermal-zone fallback: `inputs.exec` reading `/sys/class/thermal/thermal_zone*/temp` (replaces the collectd `table` plugin; keeps the existing `TEMP_MULTIPLIER` idea). |
| **Disk/Net devices** | Native inputs auto-enumerate — removes per-board config entirely. |
| **Memory math** | `inputs.mem` reports htop-style `used`/`available`; matches `system_stats.py` intent without custom `/proc/meminfo` parsing. |
| **systemd** | `telegraf`, `influxdb`, `grafana-server` ship their own units. We drop the `graphs1090.service` render loop. |
| **Low-RAM boards (Pi 3 / 1 GB)** | Document the lean profile: single retention policy, Grafana `GF_ANALYTICS` off, `inputs.execd` (not exec), InfluxDB `cache-max-memory-size` tuned. Rough idle footprint ≈ Telegraf 20 MB + InfluxDB 50 MB + Grafana 80 MB ≈ 150 MB. |

---

## 7. Retention & downsampling (replacing RRA timespans)

RRD auto-aggregated into 6 fixed resolutions (~2 d … ~18 yr). InfluxDB v1 equivalent options:

- **Default (recommended for most users — simple):** one retention policy `autogen` holding 60 s data for a long duration (e.g. 400 d). Grafana downsamples at query time via `GROUP BY time($__interval)`. On a Pi this is fine on disk (TSM compression; ~50 series × 60 s ≈ a few hundred MB/yr).
- **Multi-year / disk-lean (opt-in):** `influxdb/downsample.iql` adds retention policies (`raw` 90 d, `year` 400 d, `decade` 3650 d) plus continuous queries downsampling to 5 m and 1 h. Dashboards then pick the policy by range.

This is a **decision point** — see §10.

---

## 8. Phased execution

### Phase A — Stand up the new stack alongside the old (non-destructive)
1. Add InfluxData + Grafana apt repos; install `telegraf`, `influxdb`, `grafana`.
2. Create DB + retention policy from `influxdb/retention.iql`.
3. Install `collector/adsb_telegraf.py` + autodetected `adsb_collector.conf`.
4. Drop in `telegraf/telegraf.conf` + `telegraf.d/*.conf`; start telegraf.
5. Provision Grafana datasource + dashboards.
6. **collectd/RRD keeps running** — both pipelines collect in parallel.
   *Exit criterion:* Grafana panels show live data matching the old PNGs.

### Phase B — Port dashboards to parity
1. Build `adsb.json` (message rate, aircraft, tracks, range, signal, CPU, gain, 978, airspy) and `system.json` (CPU, temp, mem, disk, diskio, net).
2. Apply range-unit + theme toggles as Grafana variables (replaces `range=`, `colorscheme=`, theme folders).
   *Exit criterion:* every graph in the legacy UI has a Grafana equivalent.

### Phase C — Cut users over
1. Point the documented URL at Grafana (`:3000`, or reverse-proxy under the existing web path).
2. Optionally keep lighttpd serving the old PNGs read-only as a fallback for one release.
   *Exit criterion:* docs/install describe Grafana as the primary UI.

### Phase D — Decommission the old stack
1. Remove custom collectd plugins, `dump1090.db`, render scripts, theme folders, PNG output.
2. Optionally fully remove collectd if nothing else uses it.
3. Delete legacy `lib/`, `scripts/`, `config/` files no longer referenced; update `README.md` / `SUMMARY.md`.
   *Exit criterion:* repo contains only the Telegraf/Influx/Grafana stack.

---

## 9. History migration (optional)

RRD → InfluxDB import is possible but lossy (RRD already averaged old data into coarse RRAs):

- Provide an **experimental** `influxdb/import-rrd.sh`: `rrdtool fetch` each `.rrd` (per resolution) → line protocol → write into the matching downsampled retention policy.
- Default behavior: **start fresh** (new history accrues from cutover).

Recommend offering import as a clearly-labeled optional step, not part of the default install.

---

## 10. Decisions — LOCKED (defaults adopted)

1. **Retention model** — ✅ single long-retention policy (`forever`, DURATION INF). Multi-year disk-lean CQ pack stays opt-in (`influxdb/downsample.iql`, not yet built). (§7)
2. **History import** — ✅ start fresh. RRD importer remains an optional, experimental Phase-9 extra. (§9)
3. **Old-stack coexistence** — ✅ non-destructive: bring-up installs alongside collectd/RRD; PNG viewer stays until Phase D sign-off.
4. **Grafana exposure** — ✅ bare `:3000` for the slice; reverse-proxy behind the existing web path is the Phase-C target.
5. **execd vs exec** — ✅ `inputs.execd` default, `inputs.exec --once` documented fallback (both implemented in `adsb_telegraf.py`).
6. **Repo identity** — ✅ evolve `graphs1090` in place.

---

## 11. Risks & rollback

| Risk | Mitigation |
|---|---|
| InfluxData repo pulls v2/v3 instead of v1 | Pin `influxdb=1.8.*`; verify in install; document. |
| Counter rate looks wrong after decoder restart | `non_negative_derivative` in panels (handles resets). |
| Temperature missing on an exotic SBC | exec-based thermal-zone fallback; document override. |
| Disk growth on long retention | downsample CQ pack (§7); document `du` check. |
| Grafana port conflicts / firewall | reverse-proxy option (§10.4); document `:3000`. |
| Parallel-run resource spike on Pi 3 | Phase A is short; tear down collectd promptly; lean profile (§6). |
| **Rollback** | Phases A–C are non-destructive — old stack stays installed and rendering. Roll back by stopping telegraf/influxdb/grafana and re-pointing the URL. Only Phase D is irreversible (and only after sign-off). |

---

## 12. Testing / acceptance

- **Collector unit tests:** keep the existing `tests/test_dump1090.py` against the reused pure functions; add a test asserting valid line-protocol output for a sample `stats/aircraft/receiver` fixture.
- **Pipeline smoke test:** `influx -execute 'SELECT count(*) FROM adsb_aircraft'` returns rising counts after telegraf start.
- **Parity check (Phase A):** side-by-side a legacy PNG vs. the Grafana panel for the same range; values within rounding.
- **Cross-platform CI matrix:** lint/parse telegraf conf + python on arm64/amd64; (hardware smoke test on a real Pi documented as manual).
- **Cold-boot test:** reboot; confirm influxdb → telegraf → grafana come up in order and data resumes.

---

## 13. Slice history

### Slice 1 — Phase A vertical (adsb_aircraft + adsb_messages) — BUILT ✅

| File | Role |
|---|---|
| `collector/adsb_stats.py` | Pure math (verbatim from `dump1090.py`), collectd-free. |
| `collector/adsb_telegraf.py` | Collector → line protocol; `execd` + `--once` modes. |
| `collector/adsb_collector.conf.example` | Receiver URL / instance config. |
| `telegraf/telegraf.conf` + `telegraf.d/10-adsb.conf` | Agent + `inputs.execd` + `outputs.influxdb`. |
| `influxdb/retention.iql` | Creates `graphs1090` DB + `forever` RP. |
| `grafana/provisioning/**` | Datasource + provider + `adsb.json` (Aircraft Seen, Message Rate). |
| `collector/bringup-slice.sh` | Non-destructive Phase-A install on Debian/Ubuntu/Raspbian. |
| `tests/test_adsb_telegraf.py` | Unit tests over the line builders. |

---

### Slice 2 — Phase B: remaining 1090 measurements — BUILT ✅

All 1090 measurements from `dump1090.py` are now ported. 37/37 tests pass.

| Measurement | Fields | Notes |
|---|---|---|
| `adsb_aircraft` | total, with_pos, mlat, tisb, gps | `band=1090` tag; 978 variant pending |
| `adsb_messages` | local_accepted, remote_accepted, positions, strong_signals | counter → `non_negative_derivative` at query |
| `adsb_range` | max_range, median, q1, q3, min | `band=1090`; max_range prefers `last1min.max_distance` |
| `adsb_signal` | signal, noise (from last1min.local) + median, q1, q3, peak_signal, min_signal (from aircraft quartiles) | `band=1090` |
| `adsb_cpu` | demod, reader, background (+ any extras) | counter (ms); `non_negative_derivative` at query |
| `adsb_tracks` | all, single_message | counter |
| `adsb_gain` | gain_db | multi-fallback: adaptive → last1min direct → top-level → last1min.local |

**Grafana `adsb.json`** updated to 7 panels: Aircraft Seen, Message Rate, Range, Signal, Tracks, CPU, Gain.

**`band` tag design note:** `adsb_aircraft`, `adsb_range`, `adsb_signal` carry a `band` tag (`1090` or `978`) so 978 data lands in the same measurement without `_978`-suffixed fields. Filter with `WHERE band = '1090'` in panels.

**Next:** 978 measurements (url_978 → aircraft/range/signal with `band=978`), then airspy, then `system.json` Grafana dashboard (native Telegraf inputs — no custom code). On real hardware: run `sudo bash collector/bringup-slice.sh`, confirm all 7 panels populate, then start Phase C cutover prep.
