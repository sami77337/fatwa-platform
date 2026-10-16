[CmdletBinding()]
param(
    [ValidateSet('Start', 'Restart', 'Status', 'Healthcheck', 'RegressionTest', 'TestDB',
                 'Serve', 'Check', 'Test', 'Migrate', 'ValidateSource', 'ImportSource')]
    [string] $Action = 'Start',
    [string] $Python,
    [string] $DatabaseDirectory,
    [string] $Archive,
    [string] $ExpectedChecksum
)
$ErrorActionPreference = 'Stop'
# The call operator and argument array preserve spaces and shell characters in paths.
$NodeCommand = Get-Command node -CommandType Application -ErrorAction Stop
$Runner = Join-Path $PSScriptRoot 'host.mjs'
$Operations = @{
    Start = 'start'; Serve = 'start'; Restart = 'restart'
    Status = 'status'; Check = 'healthcheck'; Healthcheck = 'healthcheck'
    RegressionTest = 'test'; TestDB = 'test-db'; Test = 'test-db'
}
if ($Action -in @('Migrate', 'ImportSource', 'ValidateSource')) {
    throw 'A6 does not run migrations or imports. Source comparison retains its checksum safeguards in container_workflow.py --verify-source; it is separate from site operation.'
}
if ($Python -or $DatabaseDirectory -or $Archive -or $ExpectedChecksum) {
    throw 'A6 operates only the existing verified container. Runtime, source and credential overrides are not accepted.'
}
$NodeArguments = @($Runner, $Operations[$Action])
& $NodeCommand.Source @NodeArguments
exit $LASTEXITCODE
