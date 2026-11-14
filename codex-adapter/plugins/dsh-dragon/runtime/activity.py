"""Aggregate per-session Codex activity without persisting session metadata."""
from time import monotonic


PRIORITY = {'idle': 0, 'thinking': 1, 'working': 2, 'attention': 3}
TIMEOUT = 30 * 60


class Activity:
    def __init__(self):
        self.sessions = {}

    def update(self, status, session='', turn=''):
        if not isinstance(status, str) or status not in PRIORITY:
            raise ValueError('Unknown activity')
        if any(not isinstance(value, str) or len(value) > 128 for value in (session, turn)):
            raise ValueError('Invalid session or turn ID')
        previous = self.sessions.get(session)
        if status == 'idle':
            if previous and (not turn or not previous[1] or turn == previous[1]):
                self.sessions.pop(session)
        else:
            self.sessions[session] = (status, turn, monotonic())
        return self.current()

    def current(self):
        cutoff = monotonic() - TIMEOUT
        self.sessions = {key: value for key, value in self.sessions.items() if value[2] > cutoff}
        counts = {status: 0 for status in PRIORITY}
        for status, _, _ in self.sessions.values():
            counts[status] += 1
        active = [status for status in counts if counts[status]]
        status = max(active, key=PRIORITY.get) if active else 'idle'
        return status, counts[status]
