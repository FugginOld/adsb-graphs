import os
import sys
from unittest.mock import MagicMock

# After the repo reorg the importable modules live in sibling top-level
# folders, not next to the tests. Put them on the path so `import dump1090`
# (lib/) and `import adsb_telegraf` / `import adsb_stats` (collector/) resolve.
_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _d in ("lib", "collector"):
    _p = os.path.join(_root, _d)
    if _p not in sys.path:
        sys.path.insert(0, _p)

# dump1090.py / system_stats.py import collectd at module load; it only exists
# inside a running collectd, so stub it for tests.
mock_collectd = MagicMock()
mock_collectd.Values.return_value = MagicMock()
sys.modules['collectd'] = mock_collectd
