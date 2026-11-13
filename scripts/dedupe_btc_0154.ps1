# One-off cleanup (14 Nov 2026): a stray "mm.recorder --symbol BTCUSDT" ran next to the supervisor's
# recorder from 01:54 and wrote duplicate BTCUSDT part files. The supervisor's files (saved at ~:22-24
# past each minute) cover the whole period; the stray ones were saved at ~:50-51. This moves the
# stray files to data\live_quarantine\BTCUSDT_dup_0154 (nothing deleted). Run AFTER the stray is stopped.
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$src = Join-Path $root 'data\live\BTCUSDT'
$dst = Join-Path $root 'data\live_quarantine\BTCUSDT_dup_0154'
$start = [DateTimeOffset]::new((Get-Date '2026-11-14 01:54:00')).ToUnixTimeMilliseconds()

$stray = Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'mm\.recorder\s+--symbol\s+BTCUSDT' }
if ($stray) { Write-Host "The stray BTCUSDT recorder is still running (PID $($stray.ProcessId -join ', ')). Stop it first."; exit 1 }

$moved = 0
foreach ($k in 'book', 'trades') {
    New-Item -ItemType Directory -Force (Join-Path $dst $k) | Out-Null
    Get-ChildItem (Join-Path $src $k) -File -Filter '*.parquet' | ForEach-Object {
        $ms = [int64]($_.BaseName -replace '.*_', '')
        $sec = [DateTimeOffset]::FromUnixTimeMilliseconds($ms).LocalDateTime.Second
        if ($ms -ge $start -and $sec -ge 40 -and $sec -le 59) {
            Move-Item $_.FullName (Join-Path $dst $k); $moved++
        }
    }
}
Write-Host "Moved $moved duplicate part files to $dst"
