import pathlib

p = pathlib.Path(__file__).resolve().parent
html = (p / 'index.html').read_text(encoding='utf-8')
html = html.replace('<link rel="stylesheet" href="styles.css?v=20261112-db">', '<style>' + (p / 'styles.css').read_text(encoding='utf-8') + '</style>')
html = html.replace('<script src="data.js"></script>', '<script>' + (p / 'data.js').read_text(encoding='utf-8') + '</script>')
if (p/'menus.js').exists():
    html = html.replace('<script src="menus.js?v=20261109-mamas-dedup"></script>', '<script>' + (p/'menus.js').read_text(encoding='utf-8') + '</script>')
html = html.replace('<script src="location.js?v=20261106-diagnostics"></script>', '<script>' + (p / 'location.js').read_text(encoding='utf-8') + '</script>')
html = html.replace('<script src="routes.js?v=route-connect-20261108"></script>', '<script>' + (p / 'routes.js').read_text(encoding='utf-8') + '</script>')
for asset in ('business-hours-data.js', 'business-hours.js'):
    html = html.replace(f'<script src="{asset}?v=20261109-mamas-dedup"></script>', '<script>' + (p / asset).read_text(encoding='utf-8') + '</script>')
html = html.replace('<script src="cuisine.js?v=20261108-cuisine-options"></script>', '<script>' + (p / 'cuisine.js').read_text(encoding='utf-8') + '</script>')
html = html.replace('<script src="cuisine-data.js?v=20261109-mamas-dedup"></script>', '<script>' + (p / 'cuisine-data.js').read_text(encoding='utf-8') + '</script>')
html = html.replace('<script src="nearby-data.js?v=20261109-mamas-dedup"></script>', '<script>' + (p / 'nearby-data.js').read_text(encoding='utf-8') + '</script>')
for asset in ('nearby-search.js',):
    html = html.replace(f'<script src="{asset}?v=20261109-mamas-dedup"></script>', '<script>' + (p / asset).read_text(encoding='utf-8') + '</script>')
html = html.replace('<script src="pin-overlaps.js?v=20261109"></script>', '<script>' + (p / 'pin-overlaps.js').read_text(encoding='utf-8') + '</script>')
html = html.replace('<script src="app.js?v=20261112-supabase"></script>', '<script>' + (p / 'app.js').read_text(encoding='utf-8') + '</script>')
html = html.replace('<script src="db-details.js?v=20261112-hours-first"></script>', '<script>' + (p / 'db-details.js').read_text(encoding='utf-8') + '</script>')

html = html.replace('<script src="live-config.js?v=20261112-api-only"></script>', '<script>' + (p / 'live-config.js').read_text(encoding='utf-8') + '</script>')

destination = p.parent / '지도핀_예시.html'
destination.write_text(html, encoding='utf-8')
assert 'KAKAO_REST_API_KEY' not in html
print(destination)
