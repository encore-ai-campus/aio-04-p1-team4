# 로컬 실행 문제 해결

## `Cannot find module ...\games\server.mjs`

프로젝트 최상위 폴더에서 파일을 확인합니다.

```powershell
Test-Path .\games\server.mjs
Get-ChildItem -Recurse -Filter server.mjs
```

- `True`이면 프로젝트 최상위 폴더에서 실행합니다.

  ```powershell
  node .\games\server.mjs
  ```

- 다른 경로가 검색되면 검색된 경로로 실행합니다.
- 파일이 검색되지 않으면 `games/server.mjs`가 포함된 브랜치나 최신 통합본을 받은 후 다시 실행합니다.

  ```powershell
  git branch --show-current
  git pull
  ```

명령 끝에는 `\`를 붙이지 않습니다.

## `Application Control policy has blocked alembic.exe`

프로젝트 최상위의 `alembic.ini` 존재 여부를 확인합니다.

```powershell
Test-Path .\alembic.ini
```

`alembic.exe`를 직접 실행하지 않고 가상환경의 Python으로 실행합니다.

```powershell
.\.venv\Scripts\python.exe -m alembic upgrade head
```

가상환경이 이미 활성화되어 있다면 다음 명령도 사용할 수 있습니다.

```powershell
python -m alembic upgrade head
```

`No module named alembic`이 나오면 의존성을 설치한 뒤 다시 실행합니다.

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m alembic upgrade head
```

Python 실행도 Application Control에 차단되면 해당 PC의 관리자에게 Python 실행 허용을 요청하거나 기관에서 허용한 Python 환경을 사용합니다.

## `listen EADDRNOTAVAIL: address not available`

예: `listen EADDRNOTAVAIL: address not available 15.165.245.138:5432`

게임 서버의 `HOST`에 실행 중인 PC에 할당되지 않은 주소가 설정된 경우 발생합니다. 게임 서버는 환경변수 `HOST`와 `PORT`를 사용하므로 DB 접속용 값과 구분합니다.

게임 서버를 실행할 PowerShell 창에서 프로젝트 최상위 폴더로 이동하고 다음 명령을 실행합니다.

```powershell
cd C:\temp_resolved
$env:HOST = '0.0.0.0'
$env:PORT = '4174'
node .\games\server.mjs
```

프로젝트를 다른 경로에 받았다면 `cd` 경로를 실제 위치로 바꿉니다. 위 환경변수는 현재 PowerShell 창에만 적용되므로 새 창에서 실행할 때도 같은 값을 설정합니다.

- `HOST=0.0.0.0`: 실행 중인 PC의 모든 IPv4 인터페이스에서 요청을 받습니다.
- `PORT=4174`: 게임 서버가 사용하는 포트입니다.
- DB 주소와 DB 포트는 `.env`의 `SUPABASE_DB_URL` 또는 `DATABASE_URL` 연결 문자열에 설정합니다. 게임 서버의 `HOST`와 `PORT`에는 넣지 않습니다.

FastAPI 서버도 실행한 뒤 브라우저에서 `http://127.0.0.1:8000/games/`로 접속합니다. `0.0.0.0`은 서버 바인딩용 주소이며 브라우저 접속 주소로 사용하지 않습니다.
