"""한 지도 서버를 기존 5500 및 등록된 SDK 도메인 8000에서 제공한다."""
import socket
import uvicorn


def main():
    sockets = []
    try:
        for port in (5500, 8000):
            listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            try:
                if hasattr(socket, 'SO_EXCLUSIVEADDRUSE'):
                    listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
                listener.bind(('127.0.0.1', port))
                listener.setblocking(False)
                sockets.append(listener)
                print(f'지도 화면: http://127.0.0.1:{port}', flush=True)
            except OSError:
                listener.close()
                if port == 5500:
                    raise
                print('8000 포트가 사용 중입니다. 기존 서비스를 유지하며 5500에서 실행합니다.', flush=True)
        uvicorn.Server(uvicorn.Config('app.map_api:app', host='127.0.0.1', port=5500)).run(sockets=sockets)
    finally:
        for listener in sockets:
            listener.close()


if __name__ == '__main__':
    main()
