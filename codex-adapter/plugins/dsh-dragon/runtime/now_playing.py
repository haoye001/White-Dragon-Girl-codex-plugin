"""Read Windows media sessions and synchronize optional LRC lyrics."""
import asyncio
from bisect import bisect_right
from dataclasses import dataclass
from datetime import datetime
import json
import re
from time import monotonic
from urllib.parse import urlencode
from urllib.request import Request, urlopen


@dataclass
class Track:
    source: str
    title: str
    artist: str
    album: str
    duration: int
    position: float
    playing: bool
    sampled: float

    @property
    def key(self):
        return self.source, self.title, self.artist, self.album, self.duration

    def elapsed(self):
        position = self.position + (monotonic() - self.sampled if self.playing else 0)
        return min(position, self.duration) if self.duration else position


async def read_track():
    from winrt.windows.media.control import (
        GlobalSystemMediaTransportControlsSessionManager as Manager,
        GlobalSystemMediaTransportControlsSessionPlaybackStatus as Status,
    )
    manager = await Manager.request_async()
    session = manager.get_current_session()
    if session is None:
        return None
    properties = await session.try_get_media_properties_async()
    if properties is None or not properties.title:
        return None
    timeline = session.get_timeline_properties()
    playback = session.get_playback_info()
    playing = playback is not None and playback.playback_status == Status.PLAYING
    updated = timeline.last_updated_time
    age = max(0, (datetime.now(updated.tzinfo) - updated).total_seconds()) if playing and updated.year > 1601 else 0
    return Track(session.source_app_user_model_id, properties.title, properties.artist, properties.album_title,
                 max(0, round((timeline.end_time - timeline.start_time).total_seconds())),
                 max(0, (timeline.position - timeline.start_time).total_seconds() + age), playing, monotonic())


def read_windows_track():
    return asyncio.run(asyncio.wait_for(read_track(), timeout=6))


def parse_lrc(text):
    offset = re.search(r'(?im)^\[offset:\s*([+-]?\d+)\]', text)
    shift = int(offset[1]) / 1000 if offset else 0
    lines = {}
    for line in text.splitlines():
        stamps = list(re.finditer(r'\[(\d{1,3}):([0-5]\d)(?:\.(\d{1,3}))?\]', line))
        if not stamps:
            continue
        lyric = line[stamps[-1].end():].strip()
        for stamp in stamps:
            fraction = float('0.' + (stamp[3] or '0'))
            lines[max(0, int(stamp[1]) * 60 + int(stamp[2]) + fraction + shift)] = lyric
    return tuple(sorted(lines.items()))


def current_line(lines, seconds):
    index = bisect_right(lines, seconds, key=lambda line: line[0]) - 1
    return lines[index][1] if index >= 0 else ''


def fetch_lyrics(track):
    params = {'track_name': track.title, 'artist_name': track.artist,
              'album_name': track.album, 'duration': track.duration}
    request = Request(f'https://lrclib.net/api/get?{urlencode(params)}',
                      headers={'User-Agent': 'DSH-Codex-Desktop-Pet'})
    with urlopen(request, timeout=8) as response:
        data = json.loads(response.read(262_144))
    return parse_lrc(data.get('syncedLyrics') or '')
