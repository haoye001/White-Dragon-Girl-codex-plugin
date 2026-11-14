"""On-demand Open-Meteo weather for a user-selected city."""
import json
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import urlopen


class CityNotFound(ValueError):
    pass


def fetch_json(endpoint, **params):
    url = f'{endpoint}?{urlencode(params)}'
    for attempt in range(2):
        try:
            with urlopen(url, timeout=6) as response:
                return json.loads(response.read(131_072))
        except OSError as error:
            if attempt or (isinstance(error, HTTPError) and error.code < 500):
                raise


def current_weather(city):
    if city.strip().casefold() in {'成都', '成都市', 'chengdu'}:
        place = {'name': '成都', 'latitude': 30.66667, 'longitude': 104.06667}
    else:
        places = fetch_json('https://geocoding-api.open-meteo.com/v1/search',
                            name=city, count=1, language='zh').get('results')
        if not places:
            raise CityNotFound('没有找到城市，请尝试更完整的名称或拼音。')
        place = places[0]
    data = fetch_json('https://api.open-meteo.com/v1/forecast',
                      latitude=place['latitude'], longitude=place['longitude'],
                      timezone='auto',
                      current='temperature_2m,apparent_temperature,relative_humidity_2m')
    current = data['current']
    units = data['current_units']
    city = ' · '.join(dict.fromkeys(filter(None, (place['name'], place.get('admin1'), place.get('country')))))
    observed_at = current['time'].replace('T', ' ')
    return (f'{city}\n气温 {current["temperature_2m"]}{units["temperature_2m"]}，'
            f'体感 {current["apparent_temperature"]}{units["apparent_temperature"]}\n'
            f'湿度 {current["relative_humidity_2m"]}{units["relative_humidity_2m"]}\n'
            f'数据时间 {observed_at} · Open-Meteo')
