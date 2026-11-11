# LunchRun 실행 안내

LunchRun은 FastAPI 백엔드와 Node.js 게임 서버를 함께 실행합니다. 게임 서버는 모임방과 게임 API를 담당하고, FastAPI는 `/games/` 주소로 화면과 요청을 전달합니다.

## 준비

- Python과 Node.js가 설치되어 있어야 합니다.
- 프로젝트 루트에 `.env`와 Python 가상환경 `.venv`가 준비되어 있어야 합니다.
- 최초 실행 전 프로젝트 루트에서 의존성을 설치합니다.

```powershell
cd C:\aio-04-p1-team4
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

## 실행

PowerShell 창을 두 개 열고, 두 창 모두 프로젝트 폴더로 이동합니다.

**PowerShell 창 1 — 게임 서버**

```powershell
cd C:\aio-04-p1-team4
node games\server.mjs
```

**PowerShell 창 2 — FastAPI 백엔드**

```powershell
cd C:\aio-04-p1-team4
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

두 서버의 실행 창을 닫지 않은 상태에서 브라우저로 다음 주소를 엽니다.

- 메인 화면: http://127.0.0.1:8000/
- 게임 화면: http://127.0.0.1:8000/games/

## 종료

각 서버가 실행 중인 PowerShell 창에서 `Ctrl+C`를 눌러 종료합니다.

휴대폰으로 접속하려면 PC와 휴대폰을 같은 Wi-Fi에 연결하고, PC의 네트워크 주소와 방화벽에서 8000 포트 접속을 허용해야 합니다. 게임 Node.js 서버는 기본적으로 PC 내부의 4174 포트에서 FastAPI의 요청을 받습니다.
