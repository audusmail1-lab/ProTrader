"""Isolated integrated preview never starts or queues execution side effects."""
import os
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
import dashboard
import sentinel
import mt5_bridge

class IntegratedPreviewBoundaryTests(unittest.TestCase):
    def test_preview_blocks_bridge_execution_strategy_control_and_notifications(self):
        with patch.dict(os.environ,{'PROTRADER_LOCAL_PREVIEW':'1'}), patch.object(mt5_bridge,'_enqueue') as enqueue:
            client=TestClient(dashboard.app)
            for route in ['/api/bridge/cmd','/api/bridge/ea','/api/sentinel/live','/api/sentinel/drift','/api/notify/test']:
                result=client.post(route,json={'action':'start'})
                self.assertEqual(result.status_code,403,route)
                self.assertIn('isolated local preview',result.json()['detail'])
            enqueue.assert_not_called()
            self.assertEqual(client.get('/api/tickers').status_code,200)
            self.assertEqual(client.get('/api/sentinel/status').status_code,200)

    def test_scanner_remains_stopped_even_if_ambient_enabled_setting_is_true(self):
        with patch.dict(os.environ,{'PROTRADER_LOCAL_PREVIEW':'1','SENTINEL_ENABLED':'1'}), patch.object(sentinel.asyncio,'get_running_loop') as loop:
            sentinel.start()
            loop.assert_not_called()
            self.assertFalse(sentinel.status()['enabled'])

if __name__=='__main__': unittest.main()
