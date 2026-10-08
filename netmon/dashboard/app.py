"""Local-only HTTP dashboard with bounded API and allowlisted CSV downloads."""
from pathlib import Path
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from starlette.middleware.trustedhost import TrustedHostMiddleware
from .readers import FILES, read_rows, snapshot

STATIC = Path(__file__).resolve().parent / 'static'

def create_app(data_dir):
    data_dir = Path(data_dir).expanduser().resolve()
    app = FastAPI(title='NetMon Dashboard', version='0.7.0', docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=['127.0.0.1', 'localhost', '[::1]', 'testserver'])

    @app.get('/')
    def index():
        return FileResponse(STATIC / 'index.html', media_type='text/html', headers={'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff'})

    @app.get('/static/{filename}')
    def static(filename: str):
        if filename not in ('app.js', 'styles.css'):
            raise HTTPException(404)
        return FileResponse(STATIC / filename, headers={'X-Content-Type-Options': 'nosniff'})

    @app.get('/api/summary')
    def summary():
        return snapshot(data_dir)

    @app.get('/api/history/{kind}')
    def history(kind: str, hours: int = Query(24, ge=1, le=720), limit: int = Query(600, ge=1, le=3000)):
        if kind not in FILES:
            raise HTTPException(404, 'Unknown dataset')
        return {'kind': kind, 'rows': read_rows(data_dir, kind, hours=hours, limit=limit)}

    @app.get('/api/download/{kind}')
    def download(kind: str):
        if kind not in FILES:
            raise HTTPException(404, 'Unknown dataset')
        path = data_dir / FILES[kind]
        if not path.is_file():
            raise HTTPException(404, 'No data recorded yet')
        return FileResponse(path, filename=FILES[kind], media_type='text/csv', headers={'X-Content-Type-Options': 'nosniff'})

    return app

def serve(data_dir, host='127.0.0.1', port=8080):
    try:
        import uvicorn
    except ImportError as exc:
        raise SystemExit('Dashboard dependencies missing: pip install -r requirements-dashboard.txt') from exc
    uvicorn.run(create_app(data_dir), host=host, port=port, access_log=False)
    return 0
