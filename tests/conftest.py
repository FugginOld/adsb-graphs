import sys
from unittest.mock import MagicMock

mock_collectd = MagicMock()
mock_collectd.Values.return_value = MagicMock()
sys.modules['collectd'] = mock_collectd
