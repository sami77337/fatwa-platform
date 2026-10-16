[CmdletBinding()]
param(
    [ValidateSet('Check', 'Migrate', 'Serve', 'Test', 'ValidateSource', 'ImportSource')]
    [string] $Action = 'Serve',
    [string] $Python,
    [string] $DatabaseDirectory,
    [string] $Archive,
    [string] $ExpectedChecksum
)
$ErrorActionPreference = 'Stop'
$ProjectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
if (-not $Python) { $Python = Join-Path $ProjectRoot '.venv\Scripts\python.exe' }
if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) {
    throw 'Python 3.13 is required. Create .venv or supply -Python with its executable path.'
}
$Runtime = & $Python --version 2>&1
if ($LASTEXITCODE -ne 0 -or "$Runtime" -notmatch '^Python 3\.13\.') {
    throw 'The selected Python 3.13 executable is unavailable or inaccessible.'
}
$env:PYTHONDONTWRITEBYTECODE = '1'
$env:DJANGO_SETTINGS_MODULE = 'config.settings.development'
$env:FATWA_PRODUCTION = '0'
function Invoke-Django {
    param([string[]] $Arguments)
    & $Python (Join-Path $ProjectRoot 'manage.py') @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Django command failed (exit $LASTEXITCODE)." }
}
Push-Location -LiteralPath $ProjectRoot
try {
    if ($Action -in @('ValidateSource', 'ImportSource')) {
        if (-not $Archive -or -not (Test-Path -LiteralPath $Archive -PathType Leaf)) {
            throw 'Supply -Archive with the original owner book-622 ZIP path.'
        }
        $Archive = (Resolve-Path -LiteralPath $Archive).Path
    }
    if ($Action -eq 'ValidateSource') {
        Invoke-Django -Arguments @('import_book622', '--archive', $Archive, '--validate-only')
        return
    }
    if (-not $DatabaseDirectory -and -not $env:PGPASSWORD) {
        $DatabaseDirectory = Join-Path $ProjectRoot '..\..\worktrees\S5\infra\dev'
    }
    if ($DatabaseDirectory) {
        $DatabaseDirectory = (Resolve-Path -LiteralPath $DatabaseDirectory).Path
        $ConfigPath = Join-Path $DatabaseDirectory '.env'
        $PasswordPath = Join-Path $DatabaseDirectory '.local\app-password'
        if (-not (Test-Path -LiteralPath $PasswordPath -PathType Leaf)) {
            throw 'Existing S5 application credential file is missing. Do not regenerate credentials for an existing volume.'
        }
        $PortLine = @(Get-Content -LiteralPath $ConfigPath | Where-Object { $_ -match '^FATWA_DEV_PORT=([0-9]+)$' })
        if ($PortLine.Count -ne 1) { throw 'Expected one FATWA_DEV_PORT in the existing S5 configuration.' }
        $DevPort = [int]($PortLine[0] -replace '^FATWA_DEV_PORT=', '')
        if ($DevPort -lt 1024 -or $DevPort -gt 65535) { throw 'Invalid local PostgreSQL port.' }
        $env:PGHOST = '127.0.0.1'
        $env:PGPORT = "$DevPort"
        $env:PGDATABASE = 'fatwa_reference'
        $env:PGUSER = 'fatwa_app'
        $env:PGPASSWORD = [IO.File]::ReadAllText($PasswordPath).TrimEnd([char[]]@([char]13, [char]10))
    }
    if ($env:PGHOST -notin @('127.0.0.1', 'localhost', '::1')) {
        throw 'This development launcher only connects to loopback PostgreSQL.'
    }
    foreach ($Name in @('PGPORT', 'PGDATABASE', 'PGUSER', 'PGPASSWORD')) {
        if (-not [Environment]::GetEnvironmentVariable($Name)) { throw "Missing $Name." }
    }
    switch ($Action) {
        'Check' {
            Invoke-Django -Arguments @('check', '--database=default')
            Invoke-Django -Arguments @('makemigrations', '--check', '--dry-run')
        }
        'Migrate' {
            Invoke-Django -Arguments @('check', '--database=default')
            Invoke-Django -Arguments @('migrate', '--noinput')
        }
        'Serve' {
            Invoke-Django -Arguments @('check', '--database=default')
            Invoke-Django -Arguments @('migrate', '--check')
            Write-Host 'Open http://127.0.0.1:8000/fiqh (read-only local development).'
            Invoke-Django -Arguments @('runserver', '127.0.0.1:8000', '--noreload')
        }
        'ImportSource' {
            $ImportArguments = @('import_book622', '--archive', $Archive)
            if ($ExpectedChecksum) { $ImportArguments += @('--apply', '--expected-checksum', $ExpectedChecksum) }
            Invoke-Django -Arguments $ImportArguments
        }
        'Test' {
            if (-not $env:PGTESTDATABASE) { $env:PGTESTDATABASE = 'test_fatwa_reference_dev' }
            if ($env:PGTESTDATABASE -notmatch '^test_' -or $env:PGTESTDATABASE -eq $env:PGDATABASE) {
                throw 'Tests require a separate existing test_ database owned by the application role.'
            }
            if ($Archive) { $env:FATWA_622_ARCHIVE = $Archive }
            Invoke-Django -Arguments @('test', 'tests/reference', 'tests/integration', '--settings=config.settings.test', '--keepdb', '--noinput', '--verbosity=2')
        }
    }
} finally { Pop-Location }
