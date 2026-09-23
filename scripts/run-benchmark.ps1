[CmdletBinding()]
param([Parameter(ValueFromRemainingArguments = $true)][string[]]$BenchmarkArgs)

$ErrorActionPreference = 'Stop'

try {
    if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
        throw 'python is unavailable. Install Python 3, then retry.'
    }

    $benchmark = Join-Path $PSScriptRoot '..\llm_benchmark\benchmark.py'
    if (-not (Test-Path -LiteralPath $benchmark -PathType Leaf)) {
        throw 'llm_benchmark submodule is unavailable. Run git submodule update --init --recursive.'
    }

    Write-Host 'benchmark: prerequisites ready; starting interactive Ollama benchmark'
    & python $benchmark @BenchmarkArgs
    exit $LASTEXITCODE
}
catch [System.Management.Automation.PipelineStoppedException] {
    Write-Error 'benchmark: interrupted'
    exit 130
}
catch {
    Write-Error "benchmark: $($_.Exception.Message)"
    exit 1
}
