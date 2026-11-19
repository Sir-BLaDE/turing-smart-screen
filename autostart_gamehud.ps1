# Registra una tarea programada que arranca main.py al iniciar sesión, SIN consola y con
# privilegios elevados (hace falta para los voltajes de LibreHardwareMonitor), sin pedir UAC.
#
# Uso: abre PowerShell COMO ADMINISTRADOR, entra en la raíz del repo (donde está main.py) y ejecuta:
#     powershell -ExecutionPolicy Bypass -File .\autostart_gamehud.ps1
#
# Quitar:   Unregister-ScheduledTask -TaskName GameHUD -Confirm:$false
# Probar:   Start-ScheduledTask -TaskName GameHUD
# Parar:    Get-Process pythonw | Stop-Process     (o "Exit" desde el icono de la bandeja)

$dir = (Get-Location).Path
$py  = Join-Path $dir ".venv\Scripts\pythonw.exe"
if (-not (Test-Path (Join-Path $dir "main.py"))) { throw "Ejecútalo desde la raíz del repo (no encuentro main.py)." }
if (-not (Test-Path $py)) { throw "No encuentro $py (¿existe la venv .venv?)." }

$user      = "$env:USERDOMAIN\$env:USERNAME"
$action    = New-ScheduledTaskAction -Execute $py -Argument "main.py" -WorkingDirectory $dir
$trigger   = New-ScheduledTaskTrigger -AtLogOn -User $user
$trigger.Delay = "PT20S"      # espera 20 s tras iniciar sesión para que USB y drivers estén listos
$principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Highest
$settings  = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
             -StartWhenAvailable -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew -Priority 5 `
             -RestartCount 5 -RestartInterval (New-TimeSpan -Minutes 1)   # si el programa se cae, lo relanza (hasta 5 veces, 1 min entre intentos)

Register-ScheduledTask -TaskName "GameHUD" -Action $action -Trigger $trigger `
    -Principal $principal -Settings $settings -Force | Out-Null
Write-Host "Tarea 'GameHUD' creada. Arrancará en el próximo inicio de sesión."
Write-Host "Para probarla ya: Start-ScheduledTask -TaskName GameHUD"
