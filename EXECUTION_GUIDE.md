# LunchRun 실행 안내

LunchRun은 FastAPI 백엔드와 Node.js 게임 서버를 함께 실행합니다. 게임 서버는 모임방과 게임 API를 담당하고, FastAPI는 `/games/` 주소로 화면과 요청을 전달합니다.

## 준비

- Python과 Node.js가 설치되어 있어야 합니다. Node.js는 LTS 버전을 권장합니다.
- 프로젝트 루트에 `.env`와 Python 가상환경 `.venv`가 준비되어 있어야 합니다.
- 최초 실행 전 프로젝트 루트에서 의존성을 설치합니다.

### Node.js 설치 (Windows)

PowerShell에서 Windows 패키지 관리자 `winget`을 사용할 수 있으면 다음 명령으로 Node.js LTS를 설치합니다.

```powershell
winget install OpenJS.NodeJS.LTS
```

설치가 끝나면 PowerShell을 새로 열고 Node.js와 npm 설치 여부를 확인합니다.

```powershell
node --version
npm --version
```

`winget`을 사용할 수 없다면 [Node.js 공식 다운로드 페이지](https://nodejs.org/en/download)에서 LTS 버전의 Windows 설치 파일을 내려받아 설치하세요. 설치 후 새 PowerShell에서 위 버전 확인 명령을 실행합니다.

### Python 의존성 설치

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
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

두 서버의 실행 창을 닫지 않은 상태에서 브라우저로 다음 주소를 엽니다.

- 메인 화면: http://127.0.0.1:8000/
- 게임 화면: http://127.0.0.1:8000/games/

`0.0.0.0`은 서버가 모든 네트워크 인터페이스에서 요청을 받도록 하는 실행 설정이지, 브라우저에 입력하는 접속 주소가 아닙니다. 휴대폰에서도 접속해야 한다면 백엔드를 다음처럼 실행하고, 휴대폰 브라우저에는 PC의 실제 로컬 네트워크 IP 주소를 입력하세요.

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

예를 들어 PC의 IP가 `192.168.0.10`이면 휴대폰에서 `http://192.168.0.10:8000/games/`를 엽니다. PC와 휴대폰은 같은 Wi-Fi에 연결되어야 하며 Windows 방화벽에서 8000 포트를 허용해야 할 수 있습니다.

## 종료

각 서버가 실행 중인 PowerShell 창에서 `Ctrl+C`를 눌러 종료합니다.

게임 Node.js 서버는 기본적으로 PC 내부의 4174 포트에서 FastAPI의 요청을 받습니다.
