# Ponytail Audit Report

Scope: over-engineering and complexity only. Ranked biggest cut first.

---

## Findings

**`delete:` `lib/dump1090.py` + `lib/system_stats.py` + `lib/prune-value.py`**
Legacy collectd Python. `adsb_telegraf.py` comment says "Phase D consolidates them into this one"; commit history confirms Phase D is done. Nothing to replace.
→ [`lib/`](lib/)

---

**`delete:` `tests/test_dump1090.py` + `tests/conftest.py` mock_collectd stub**
Tests and collectd stub exist solely to support the lib files above. Removing the libs makes these dead. `conftest.py` can be deleted entirely if no remaining tests use it.
→ [`tests/`](tests/)

---

**`delete:` RRD/collectd scripts in `scripts/`**
`rrd-dump.sh`, `rrd-integrate-old.sh`, `rrd-restore.sh`, `rem_rra.sh`, `malarky.sh`, `stopMalarky.sh`, `readback.sh`, `writeback.sh`, `scatter.sh`, `new-format.sh`, `prune.sh`, `prune-range.sh` — all RRD or collectd lifecycle scripts. The last two commits exist specifically to remove this stack.
→ [`scripts/`](scripts/)

---

**`delete:` `collector/decommission.sh` + `bringup-slice.sh` + `cutover.sh`**
One-time migration scripts. Migration is complete.
→ [`collector/`](collector/)

---

**`delete:` `config/collectd.conf`, `config/hide_system-collectd.conf`, `config/malarky.conf`**
Collectd config files for a stack that has been removed.
→ [`config/`](config/)

---

**`stdlib:` `load_config()` hand-rolled INI parser**
30 lines of manual `split('=', 1)` / strip / case-fold. `configparser.ConfigParser()` with `read()` and `os.environ` fallbacks covers all the same keys in ~8 lines.
→ [`collector/adsb_telegraf.py`](collector/adsb_telegraf.py)

---

**`yagni:` `adsb-graphs-themes/` (aviation.sh, minimal.sh, night.sh, retro.sh)**
4 theme-switcher shell scripts with no caller in `install.sh` or any other script. Delete unless theme selection is actively shipped.
→ [`adsb-graphs-themes/`](adsb-graphs-themes/)

---

**`yagni:` `config/http/95-adsb-graphs-otherport.conf`**
Alternate-port nginx block with no documented use case and no reference in `install.sh`.
→ [`config/http/`](config/http/)

---

**`delete:` `SUMMARY.md`**
7.9 KB AI-generated project summary duplicating README content. Not referenced anywhere.
→ [`SUMMARY.md`](SUMMARY.md)

---

**`delete:` `scripts/generate-adsb.im-backup.sh`, `scripts/gunzip.sh`, `scripts/boot.sh`**
One-off utilities with no callers in `install.sh` or cron config.
→ [`scripts/`](scripts/)

---

## Summary

**net: ~-500 lines, -0 deps possible.**

All cuts are dead code from the collectd→Telegraf migration that did not fully clean up after itself. The live stack (`adsb_telegraf.py`, `telegraf/`, `influxdb/`, `grafana/`) is lean.
