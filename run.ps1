param(
    [switch]$Local,
    [Alias("completion-no-database-access")][switch]$CompletionNoDatabaseAccess,
    [Alias("host")][string]$BindHost,
    [switch]$Reload,
    [switch]$NoReload,
    [Alias("backend-port")]
    [ValidateRange(1, 65535)][int]$BackendPort = 8301,
    [string]$PythonExecutable
)

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
if ($Local -and $BindHost) {
    throw "Use either -Local or -BindHost, not both."
}
$backendPython = Join-Path $root ".venv\Scripts\python.exe"
if ($PythonExecutable) {
    $backendPython = $PythonExecutable
}
elseif ($env:VIRTUAL_ENV) {
    $backendPython = Join-Path $env:VIRTUAL_ENV "Scripts\python.exe"
}
elseif ($env:CONDA_PREFIX) {
    $backendPython = Join-Path $env:CONDA_PREFIX "python.exe"
}
if (-not (Test-Path -LiteralPath $backendPython)) {
    $backendPython = "python"
}
if ($Reload -and $NoReload) {
    throw "Use either -Reload or -NoReload, not both."
}

$arguments = @()
if ($Local) { $arguments += "--local" }
elseif ($BindHost) { $arguments += @("--host", $BindHost) }
if ($PSBoundParameters.ContainsKey("BackendPort")) { $arguments += @("--port", [string]$BackendPort) }
if ($CompletionNoDatabaseAccess) { $arguments += "--completion-no-database-access" }
if ($Reload) { $arguments += "--reload" }

& $backendPython (Join-Path $root "run.py") @arguments
exit $LASTEXITCODE

