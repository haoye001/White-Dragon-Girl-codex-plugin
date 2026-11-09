"""Real Tk/HTTP end-to-end check, isolated from the user's running pet."""
import os
from pathlib import Path
import sys
import tempfile
import threading
import time

market = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(market/'plugins/bailong-pet/runtime'))


def main():
    with tempfile.TemporaryDirectory(prefix='bailong-smoke-') as directory:
        os.environ['BAILONG_PLUGIN_DATA'] = directory
        import core
        import bridge
        from app import Pet
        pet = Pet()
        pet.root.withdraw()
        pet.visible = False
        errors = []

        def check_auto_and_bubble():
            try:
                if pet.current != 'idle':
                    pet.root.after(20, check_auto_and_bubble)
                    return
                pet.bubble.hide()
                pet.visible = True
                for flag in ('busy', 'mouse_down', 'quota_pending'):
                    setattr(pet, flag, True)
                    pet.next_interaction = 0
                    pet.auto_tick()
                    assert pet.auto_count == 0, flag
                    setattr(pet, flag, False)
                pet.visible = False
                pet.auto_tick()
                assert pet.auto_count == 0
                pet.visible = True
                pet.auto_tick()
                assert pet.auto_count == 1
                pet.bubble.show('Codex 剩余额度\n5 小时：92.0%\n重置：10-25 18:20\n一周：99.0%\n重置：11-01 18:20\n查询于 12:34:56')
                assert pet.bubble.height > 100
                assert pet.bubble.canvas.find_all()
                assert pet.bubble.canvas.bbox('all')[3] <= pet.bubble.height+2
                pet.bubble.hide()
                pet.play('idle', loop=True)
                pet.visible = False
                threading.Thread(target=exercise, daemon=True).start()
            except BaseException as exc:
                errors.append(exc)
                pet.root.destroy()

        def exercise():
            try:
                state = bridge.request({'action': 'state'})
                assert len(state['animations']) == 25
                assert not state['visible']
                # Exercise real image decoding, timer updates, literal labels and usage.
                assert bridge.request({'action': 'play', 'animation': '01'})['requested_animation'] == '01'
                deadline = time.monotonic()+15
                while bridge.request({'action': 'state'})['animation'] != '01':
                    assert time.monotonic() < deadline, 'animation did not load'
                    time.sleep(.05)
                bridge.request({'action': 'say', 'message': '<script>literal text</script>', 'seconds': 1})
                state = bridge.request({'action': 'usage', 'windows': [{'label': 'TEST ONLY', 'used_percent': 25}]})
                assert state['usage']['windows'][0]['used_percent'] == 25
                state = bridge.request({'action': 'event', 'event': 'PreToolUse'})
                assert state['busy']
                state = bridge.request({'action': 'event', 'event': 'Stop'})
                assert not state['busy'] and state['requested_animation'] == 'idle'
                state = bridge.request({'action': 'settings', 'settings': {'auto_interact': False, 'auto_interval_seconds': 90}})
                assert state['settings'] == {'auto_interact': False, 'auto_interval_seconds': 90}
                assert json.loads((Path(directory)/'settings.json').read_text())['auto_interval_seconds'] == 90
                from unittest.mock import patch
                import quota
                with patch.object(quota, 'fetch', side_effect=RuntimeError('测试连接失败')):
                    assert bridge.request({'action': 'query_usage'})['quota_pending']
                    deadline = time.monotonic()+5
                    while bridge.request({'action': 'state'})['quota_pending']:
                        assert time.monotonic() < deadline
                        time.sleep(.02)
                    state = bridge.request({'action': 'state'})
                    assert state['quota_error'] == '测试连接失败'
                    assert state['usage']['windows'][0]['used_percent'] == 25
                    assert '测试连接失败' in state['bubble_text']
                bridge.request({'action': 'hide'})
            except BaseException as exc:
                errors.append(exc)
            finally:
                try:
                    bridge.request({'action': 'stop'})
                except Exception as exc:
                    errors.append(exc)

        import json
        pet.root.after(20, check_auto_and_bubble)
        pet.root.after(90000, pet.root.destroy)
        pet.run()
        if errors:
            raise errors[0]
        assert not (Path(directory)/'endpoint.json').exists()
        print('PASS: actual Tk animation, authenticated HTTP, speech, usage, hooks and shutdown; no user data touched.')


if __name__ == '__main__':
    main()
