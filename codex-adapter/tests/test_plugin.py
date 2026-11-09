import importlib
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
import urllib.error
import urllib.request

MARKET = Path(__file__).resolve().parents[1]
PLUGIN = MARKET / 'plugins' / 'bailong-pet'
sys.path.insert(0, str(PLUGIN / 'runtime'))
import core
import bridge


class ArtworkTests(unittest.TestCase):
    def test_prepared_frames_preserve_pixels_and_reject_stale_cache(self):
        import animation
        from PIL import Image
        import zlib
        import struct
        frames = [Image.new('RGBA', (300, 300), (10, 20, 30, 0)),
                  Image.new('RGBA', (300, 300), (100, 50, 20, 190))]
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary)/'sample.frames'
            animation.save_frames(path, 'fingerprint', frames, [40, 80])
            actual, delays = animation.read_frames(path, 'fingerprint')
            self.assertEqual(delays, [40, 80])
            self.assertEqual([f.tobytes() for f in actual], [f.tobytes() for f in frames])
            with self.assertRaises(ValueError):
                animation.read_frames(path, 'stale')
            # Compressed output beyond a frame's allowed size is rejected before materializing it.
            header = json.dumps({'fingerprint': 'x', 'delays': [40]}).encode()
            packed = zlib.compress(b'0'*(animation.FRAME_BYTES+100))
            path.write_bytes(animation.MAGIC+struct.pack('<I',len(header))+header+struct.pack('<I',len(packed))+packed)
            with self.assertRaises(ValueError):
                animation.read_frames(path, 'x')

    def test_all_25_webp_assets_decode_with_limits(self):
        from PIL import Image
        catalog = core.animation_catalog()
        self.assertEqual(len(catalog), 25)
        for item in catalog.values():
            with self.subTest(id=item['id']), Image.open(item['path'], formats=['WEBP']) as image:
                self.assertEqual(image.format, 'WEBP')
                self.assertLessEqual(image.width*image.height, core.MAX_PIXELS)
                self.assertLessEqual(image.n_frames, core.MAX_FRAMES)
                image.load()

    def test_traversal_and_other_formats_rejected(self):
        for filename in ['../../secrets.webp', str(Path('C:/outside.webp')), 'malicious.psd']:
            with self.subTest(filename=filename), patch.object(core, 'read_json', return_value={
                'idle': {'id': 'idle', 'file': filename}}):
                with self.assertRaises(ValueError):
                    core.animation_catalog()


class ProtocolTests(unittest.TestCase):
    def test_stdio_handshake_state_and_invalid_call(self):
        values = [
            {'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {'protocolVersion': '2024-11-05'}},
            {'jsonrpc': '2.0', 'method': 'notifications/initialized'},
            {'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list'},
            {'jsonrpc': '2.0', 'id': 3, 'method': 'tools/call', 'params': {'name': 'not_a_tool', 'arguments': {}}},
            {'jsonrpc': '2.0', 'id': 4, 'method': 'ping'}]
        result = subprocess.run([sys.executable, str(PLUGIN/'runtime/bridge.py'), 'mcp'],
            input='\n'.join(json.dumps(v) for v in values)+'\n', capture_output=True, text=True,
            encoding='utf8', timeout=15, check=True)
        replies = [json.loads(line) for line in result.stdout.splitlines()]
        self.assertEqual([r['id'] for r in replies], [1,2,3,4])
        self.assertEqual(len(replies[1]['result']['tools']), 5)
        self.assertTrue(replies[2]['result']['isError'])
        self.assertEqual(replies[3]['result'], {})
        self.assertEqual(result.stderr, '')

    def test_invalid_commands_do_not_launch_pet(self):
        with patch.object(bridge, 'start') as launch:
            for args in [{'action': 'event'}, {'action': 'say', 'message': 'x'*1001},
                         {'action': 'say', 'message': 'test', 'seconds': -1},
                         {'action': 'play', 'animation': '../../evil'}, {'action': 'shell'}]:
                with self.subTest(args=str(args)[:40]), self.assertRaises(ValueError):
                    bridge.tool_call('bailong_control', args)
            launch.assert_not_called()

    def test_usage_requires_actual_percentages(self):
        for value in [None, [], [{'label': 'quota', 'used_percent': 101}],
                      [{'label': 'quota', 'used_percent': float('nan')}],
                      [{'label': 'quota', 'used_percent': True}]]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                core.validate_command({'action': 'usage', 'windows': value}, {})

    def test_passive_hook_sends_only_event_name(self):
        import io
        message = {'hook_event_name': 'Stop', 'prompt': 'private prompt', 'tool_input': 'secret'}
        with patch('sys.stdin', io.StringIO(json.dumps(message))), patch.object(bridge, 'request') as req:
            bridge.hook()
            self.assertEqual(req.call_args.args[0], {'action': 'event', 'event': 'Stop'})


class QuotaTests(unittest.TestCase):
    def test_multi_bucket_missing_window_and_remaining(self):
        import quota
        result = {'rateLimits': {'primary': {'usedPercent': 90}}, 'rateLimitsByLimitId': {'codex': {
            'primary': {'usedPercent': 8, 'windowDurationMins': 300, 'resetsAt': 1792933208},
            'secondary': {'usedPercent': 1, 'windowDurationMins': 10080, 'resetsAt': 1793520008}}}}
        windows = quota.normalize(result)
        self.assertEqual([w['used_percent'] for w in windows], [8, 1])
        text = quota.format_usage({'windows': windows, 'checked_at': '2026-10-25T12:34:56+08:00'})
        self.assertIn('92.0%', text)
        self.assertIn('99.0%', text)
        self.assertIn('重置', text)
        self.assertEqual(len(quota.normalize({'rateLimits': {'primary': {'usedPercent': 0}, 'secondary': None}})), 1)

    def test_unavailable_quota_does_not_become_zero(self):
        import quota
        for result in [{}, {'rateLimits': {'primary': None}}, {'rateLimits': {'primary': {'usedPercent': None}}}]:
            with self.subTest(result=result), self.assertRaises(RuntimeError):
                quota.normalize(result)

    def test_quota_transport_only_sends_read_requests_and_cleans_up(self):
        import quota
        import io
        class Recording(io.StringIO):
            def close(self):
                self.recorded = self.getvalue()
                super().close()
        process = unittest.mock.Mock()
        process.stdin = Recording()
        process.stdout = io.StringIO(json.dumps({'id': 1, 'result': {}})+'\n'+json.dumps({
            'id': 2, 'result': {'rateLimits': {'primary': {'usedPercent': 5}}}})+'\n')
        process.poll.return_value = None
        with tempfile.TemporaryDirectory() as temporary:
            executable = Path(temporary)/'codex.exe'
            executable.write_bytes(b'')
            with patch.object(quota, 'read_json', return_value={'codex': str(executable)}), patch.object(quota.subprocess, 'Popen', return_value=process):
                self.assertEqual(quota.fetch()[0]['used_percent'], 5)
        sent = [json.loads(line)['method'] for line in process.stdin.recorded.splitlines()]
        self.assertEqual(sent, ['initialize', 'initialized', 'account/rateLimits/read'])
        process.terminate.assert_called_once()
        process.wait.assert_called_once()

    def test_auto_settings_reject_unsafe_or_invalid_values(self):
        for settings in [{'auto_interval_seconds': 0}, {'auto_interval_seconds': float('nan')},
                         {'auto_interact': 'yes'}, {'codex_path': 'evil.exe'}]:
            with self.subTest(settings=settings), self.assertRaises(ValueError):
                core.validate_command({'action': 'settings', 'settings': settings}, {})


class LoopbackTests(unittest.TestCase):
    def setUp(self):
        from app import make_server
        class FakePet:
            endpoint_token = 'a'*43
            commands = queue.Queue()
            catalog = {}
        self.pet = FakePet()
        self.server = make_server(self.pet)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f'http://127.0.0.1:{self.server.server_port}/command'

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()

    def test_unauthenticated_request_never_enters_gui_queue(self):
        req = urllib.request.Request(self.url, data=b'{"action":"stop"}')
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req, timeout=2)
        self.assertEqual(ctx.exception.code, 403)
        self.assertTrue(self.pet.commands.empty())

    def test_authenticated_command_and_reply(self):
        def worker():
            value, done, box = self.pet.commands.get(timeout=3)
            box['result'] = {'running': True, 'action': value['action']}
            done.set()
        thread = threading.Thread(target=worker)
        thread.start()
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            core.atomic_json(directory/'endpoint.json', {'port': self.server.server_port, 'token': self.pet.endpoint_token})
            with patch.object(bridge, 'DATA', directory):
                self.assertEqual(bridge.request({'action': 'state'}, 3), {'running': True, 'action': 'state'})
        thread.join(timeout=3)


if __name__ == '__main__':
    unittest.main()
