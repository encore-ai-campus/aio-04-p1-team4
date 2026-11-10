"""Server-side Kakao walking routes. Credentials never reach the browser."""
import json
import math
import pathlib
import urllib.error
import urllib.parse
import urllib.request


class RouteError(Exception):
    def __init__(self, message, status=502):
        self.message, self.status = message, status


def read_env(root):
    path = pathlib.Path(root) / '.env'
    values = {}
    if path.exists():
        for line in path.read_text(encoding='utf-8-sig').splitlines():
            if '=' in line and not line.lstrip().startswith('#'):
                name, value = line.split('=', 1)
                values[name.strip()] = value.strip().strip('\"\'')
    return values


def point(value):
    if not isinstance(value, dict):
        raise RouteError('출발지와 도착지를 선택해주세요.', 400)
    lat, lng = value.get('lat'), value.get('lng')
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in [lat, lng]):
        raise RouteError('올바른 위치 좌표가 필요해요.', 400)
    if not (-90 <= lat <= 90 and -180 <= lng <= 180):
        raise RouteError('위치 좌표 범위를 확인해주세요.', 400)
    return lat, lng


def normalize_route(data):
    if not isinstance(data, dict):
        raise RouteError('도보 경로 응답 형식을 확인하지 못했어요.')
    status = data.get('status', 'OK' if data.get('route') else '')
    if status == 'SAME_POINT':
        return dict(distance=0, duration=0, paths=[], steps=[])
    if status != 'OK':
        raise RouteError({'START_LINK_NOT_FOUND': '출발지 주변의 도보 길을 찾지 못했어요. 출발지를 도로 가까이로 바꿔주세요.',
                          'END_LINK_NOT_FOUND': '가게 입구 주변의 도보 길을 찾지 못했어요.',
                          'TOO_FAR_AWAY': '도보 경로를 찾기에는 출발지가 너무 멀어요.',
                          'ROUTE_RESULT_NOT_FOUND': '연결되는 도보 경로를 찾지 못했어요.'}.get(status, '도보 경로를 찾지 못했어요.'), 422)
    route = data.get('route', {})
    props = route.get('properties', {})
    distance, duration = props.get('totalDistance'), props.get('totalTime')
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or v < 0 for v in [distance, duration]):
        raise RouteError('경로의 거리와 시간을 확인하지 못했어요.')
    paths, steps = [], []
    for leg in route.get('legs', []):
        for step in leg.get('steps', []):
            path = []
            for xy in step.get('path', {}).get('points', []):
                if not isinstance(xy, list) or len(xy) != 2:
                    raise RouteError('경로 좌표 형식이 올바르지 않아요.')
                lat, lng = point({'lng': xy[0], 'lat': xy[1]})
                path.append([lng, lat])
            if len(path) > 1:
                paths.append(path)
            guidance = step.get('properties', {}).get('guidance')
            if guidance:
                steps.append(str(guidance))
    if distance > 0 and not paths:
        raise RouteError('표시할 도보 경로를 받지 못했어요.')
    return dict(distance=distance, duration=duration, paths=paths, steps=steps)


def walking_route(body, root, opener=urllib.request.urlopen):
    start = point(body.get('origin'))
    end = point(body.get('destination'))
    env = read_env(root)
    key = env.get('KAKAO_REST_API_KEY') or env.get('KAKAO_REST_KEY')
    if not key:
        raise RouteError('도보 길찾기 연결 설정이 필요해요. 카카오맵에서 길찾기를 이용해주세요.', 503)
    query = urllib.parse.urlencode(dict(start_x=start[1], start_y=start[0], end_x=end[1], end_y=end[0], input_coord='WGS84', output_coord='WGS84'))
    headers = {'Authorization': 'KakaoAK ' + key}
    req = urllib.request.Request('https://dapi.kakao.com/v2/routing/walk?' + query, headers=headers)
    try:
        with opener(req, timeout=15) as response:
            data = json.load(response)
    except urllib.error.HTTPError as exc:
        messages = {401: '카카오 길찾기 인증을 확인해야 해요. 카카오맵에서 길찾기를 이용해주세요.',
                    403: '카카오 도보 경로 API 이용 권한을 확인해야 해요. 카카오맵에서 길찾기를 이용해주세요.',
                    404: '카카오 도보 경로 API에 연결하지 못했어요. 카카오맵에서 길찾기를 이용해주세요.',
                    429: '도보 경로 조회 한도에 도달했어요. 잠시 후 다시 시도해주세요.'}
        raise RouteError(messages.get(exc.code, '카카오 도보 경로 조회에 실패했어요. 잠시 후 다시 시도해주세요.'), 503) from None
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        raise RouteError('도보 경로 서버에 연결하지 못했어요. 잠시 후 다시 시도해주세요.', 503) from None
    return normalize_route(data)
