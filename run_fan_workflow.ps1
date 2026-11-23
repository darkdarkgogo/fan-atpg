param(
    [string]$Python = 'C:\Users\acer\.conda\envs\d2l\python.exe',
    [string]$TrainManifest = 'configs/fan_train.json',
    [string]$ValidationManifest = 'configs/fan_validation_full.json',
    [string]$Output = 'runs/fan_one_round',
    [int]$Rounds = 1,
    [switch]$SkipBuild
)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
if ($Rounds -lt 1) { throw 'Rounds must be positive.' }
if (-not $SkipBuild) {
    & $Python FAN_ATPG/setup.py build_ext --inplace
    if ($LASTEXITCODE -ne 0) { throw 'FAN extension build failed.' }
}
foreach ($manifest in @($TrainManifest, $ValidationManifest)) {
    & $Python scripts/prepare_fan_data.py --manifest $manifest
    if ($LASTEXITCODE -ne 0) { throw "Feature export failed: $manifest" }
}
& $Python -m fault_order_rl train --manifest $TrainManifest --validation-manifest $ValidationManifest --rounds $Rounds --output $Output
if ($LASTEXITCODE -ne 0) { throw 'FAN training or validation failed.' }
& $Python validation/verify_run.py --run $Output --train-manifest $TrainManifest --validation-manifest $ValidationManifest
if ($LASTEXITCODE -ne 0) { throw 'Independent pattern verification failed.' }
