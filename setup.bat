@echo off
cd /d "%~dp0"
echo.
echo  Setting up Studio - AI Creative Agency. This takes a few minutes the first time.
echo.
where py >nul 2>nul
if %errorlevel%==0 (set "PY=py -3") else (set "PY=python")
%PY% --version >nul 2>nul
if errorlevel 1 (
  echo  Python was not found. Install it from https://www.python.org/downloads/
  echo  and tick "Add python.exe to PATH" on the first installer screen. Then run setup.bat again.
  pause
  exit /b 1
)
if not exist .venv %PY% -m venv .venv
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements.txt
if errorlevel 1 ( echo. & echo  Installing packages failed - check your internet connection and run setup.bat again. & pause & exit /b 1 )
python -m playwright install chromium
if errorlevel 1 ( echo. & echo  Installing the image renderer failed - run setup.bat again. & pause & exit /b 1 )
echo.
echo  Installing the photo cut-out tool (optional, about 200 MB on first use)...
pip install "rembg[cpu]"
if errorlevel 1 echo  Cut-outs could not be installed. The app still works without them.
echo.
echo  Downloading the public-link tool for Instagram publishing (cloudflared)...
if not exist tools mkdir tools
if not exist tools\cloudflared.exe curl -L -o tools\cloudflared.exe https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe
if errorlevel 1 echo  Could not download cloudflared. Publishing to Instagram needs it - run setup.bat again later.
if not exist .env copy .env.example .env >nul
echo.
echo  Setup complete!
echo  Notepad will now open the .env file: paste your OpenAI API key after OPENAI_API_KEY= and save.
echo  Then double-click start.bat
echo.
pause
notepad .env
