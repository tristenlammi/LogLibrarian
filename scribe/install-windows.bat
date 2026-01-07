@echo off
REM Scribe Agent - Windows Service Installation (Alternative Method)
REM Run as Administrator

echo ================================
echo Scribe Agent Service Installer
echo ================================
echo.

REM Check for administrator privileges
net session >nul 2>&1
if %errorLevel% neq 0 (
    echo Error: Please run as Administrator
    echo Right-click and select "Run as administrator"
    pause
    exit /b 1
)

echo [1/4] Creating directories...
mkdir "C:\Program Files\Scribe" 2>nul
mkdir "C:\ProgramData\Scribe" 2>nul
mkdir "C:\ProgramData\Scribe\logs" 2>nul
echo Done.

echo.
echo [2/4] Copying binary...
if not exist "scribe-agent.exe" (
    echo Error: scribe-agent.exe not found in current directory
    echo Please build the agent first: go build -o scribe-agent.exe .
    pause
    exit /b 1
)
copy /Y scribe-agent.exe "C:\Program Files\Scribe\" >nul
echo Done.

echo.
echo [3/4] Creating configuration...
if not exist "C:\ProgramData\Scribe\config.json" (
    echo {> "C:\ProgramData\Scribe\config.json"
    echo   "server_host": "127.0.0.1:8000",>> "C:\ProgramData\Scribe\config.json"
    echo   "api_key": "",>> "C:\ProgramData\Scribe\config.json"
    echo   "agent_name": "%COMPUTERNAME%",>> "C:\ProgramData\Scribe\config.json"
    echo   "log_file": "C:\\Windows\\System32\\winevt\\Logs\\Application.evtx",>> "C:\ProgramData\Scribe\config.json"
    echo   "metrics_interval": 60,>> "C:\ProgramData\Scribe\config.json"
    echo   "log_batch_size": 50,>> "C:\ProgramData\Scribe\config.json"
    echo   "log_batch_interval": 5,>> "C:\ProgramData\Scribe\config.json"
    echo   "ssl_enabled": false,>> "C:\ProgramData\Scribe\config.json"
    echo   "ssl_verify": true,>> "C:\ProgramData\Scribe\config.json"
    echo   "agent_id": "">> "C:\ProgramData\Scribe\config.json"
    echo }>> "C:\ProgramData\Scribe\config.json"
    echo Configuration created.
    echo.
    echo *** IMPORTANT: Edit C:\ProgramData\Scribe\config.json ***
    echo *** Set "server_host" and "api_key" from LogLibrarian ***
) else (
    echo Configuration already exists, skipping.
)
echo Done.

echo.
echo [4/4] Installing Windows Service...

REM Stop existing service if running
sc query Scribe >nul 2>&1
if %errorLevel% equ 0 (
    echo Stopping existing service...
    net stop Scribe >nul 2>&1
    sc delete Scribe >nul 2>&1
    timeout /t 2 /nobreak >nul
)

REM Create new service
sc create Scribe binPath= "\"C:\Program Files\Scribe\scribe-agent.exe\" install -config \"C:\ProgramData\Scribe\config.json\"" start= auto DisplayName= "Scribe Monitoring Agent" obj= LocalSystem
if %errorLevel% neq 0 (
    echo Error: Failed to create service
    pause
    exit /b 1
)

REM Set service description
sc description Scribe "Collects system metrics, processes, and logs for LogLibrarian" >nul

REM Set recovery options
sc failure Scribe reset= 86400 actions= restart/5000/restart/10000/restart/30000 >nul

echo Done.

echo.
echo ================================
echo Installation Complete!
echo ================================
echo.
echo Binary:  C:\Program Files\Scribe\scribe-agent.exe
echo Config:  C:\ProgramData\Scribe\config.json
echo Logs:    C:\ProgramData\Scribe\logs\
echo.
echo IMPORTANT: Edit the configuration file before starting:
echo   notepad C:\ProgramData\Scribe\config.json
echo.
echo Update the "server_host" field with your LogLibrarian server address.
echo.
set /p START_NOW="Start Scribe service now? (Y/N): "
if /i "%START_NOW%"=="Y" (
    echo Starting service...
    net start Scribe
    if %errorLevel% equ 0 (
        echo Service started successfully!
    ) else (
        echo Failed to start service. Check logs for details.
    )
) else (
    echo Service created but not started.
    echo Run 'net start Scribe' to start the service.
)

echo.
echo Useful commands:
echo   Status:  sc query Scribe
echo   Start:   net start Scribe
echo   Stop:    net stop Scribe
echo   Restart: net stop Scribe ^&^& net start Scribe
echo   Logs:    type C:\ProgramData\Scribe\logs\stdout.log
echo.
pause
