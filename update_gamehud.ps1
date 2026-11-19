# Actualiza GameHUD con un solo comando: para la tarea, ejecuta el instalador y la vuelve a arrancar.
# Además corrige la prioridad de la tarea (Windows las crea "por debajo de lo normal") para que el HUD no se quede
# atrás cuando la CPU está muy cargada jugando.
#
# Uso: abre PowerShell COMO ADMINISTRADOR, entra en la raíz del repo (donde está main.py) y ejecuta:
#     powershell -ExecutionPolicy Bypass -File .\update_gamehud.ps1

$dir = (Get-Location).Path
$py  = Join-Path $dir ".venv\Scripts\python.exe"
if (-not (Test-Path (Join-Path $dir "main.py"))) { throw "Ejecútalo desde la raíz del repo (no encuentro main.py)." }
if (-not (Test-Path $py)) { throw "No encuentro $py (¿existe la venv .venv?)." }
if (-not (Test-Path (Join-Path $dir "install_gamehud.py"))) { throw "Falta install_gamehud.py en la raíz del repo." }

$task = Get-ScheduledTask -TaskName "GameHUD" -ErrorAction SilentlyContinue
if ($task) {
    Write-Host "Parando la tarea GameHUD..."
    Stop-ScheduledTask -TaskName "GameHUD" -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 2
}

Write-Host "Ejecutando el instalador..."
& $py (Join-Path $dir "install_gamehud.py")
if ($LASTEXITCODE -ne 0) { throw "El instalador ha fallado (código $LASTEXITCODE); la tarea NO se ha vuelto a arrancar." }

if ($task) {
    $changed = $false
    if ($task.Settings.Priority -gt 5) {
        $task.Settings.Priority = 5
        $changed = $true
        Write-Host "Prioridad de la tarea corregida a normal (5)."
    }
    if ($task.Settings.RestartCount -lt 1) {          # relanzar el programa automáticamente si se cae
        $task.Settings.RestartCount = 5
        $task.Settings.RestartInterval = "PT1M"
        $changed = $true
        Write-Host "Reinicio automático si el programa se cae: activado (5 intentos, 1 min entre ellos)."
    }
    if ($changed) { Set-ScheduledTask -InputObject $task | Out-Null }
    Write-Host "Arrancando la tarea GameHUD..."
    Start-ScheduledTask -TaskName "GameHUD"
    Write-Host "Listo."
} else {
    Write-Host "Listo. (No existe la tarea GameHUD: crea el autoarranque con autostart_gamehud.ps1 si lo quieres.)"
}
