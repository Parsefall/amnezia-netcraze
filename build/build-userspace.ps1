param([string]$Go = '')
$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path $PSScriptRoot -Parent
if (-not $Go) { $Go = Join-Path $ProjectRoot 'outputs/toolchain/go/bin/go.exe' }
if (-not (Test-Path -LiteralPath $Go)) { throw 'Supply -Go with a Go 1.25+ executable path.' }
$Source = Join-Path $ProjectRoot 'outputs/src/amneziawg-go'
if (-not (Test-Path -LiteralPath (Join-Path $Source '.git'))) {
    git clone --depth 1 --branch v3.1.20260828 https://github.com/amnezia-vpn/amneziawg-go.git $Source
    if ($LASTEXITCODE) { throw 'Clone failed' }
}
$Revision = git -C $Source rev-parse HEAD
if ($Revision -ne 'b5928efb6ca19f0153958460c3d141f04abc5c2e') { throw 'Source revision mismatch' }
$Patch = Join-Path $ProjectRoot 'build/patches/002-go-tun-padding-refresh.patch'
if (-not (git -C $Source status --porcelain)) {
    git -C $Source apply $Patch
    if ($LASTEXITCODE) { throw 'Patch failed' }
}
if ((git -C $Source status --porcelain) -ne ' M device/send.go') { throw 'Unexpected source modifications' }
$ActualPatch = (git -C $Source diff -- device/send.go) -join "`n"
$ExpectedPatch = [IO.File]::ReadAllText($Patch).Replace("`r`n", "`n").TrimEnd()
if ($ActualPatch -ne $ExpectedPatch) { throw 'Source patch mismatch' }
$env:GOCACHE = Join-Path $ProjectRoot 'outputs/go-cache'
$env:GOMODCACHE = Join-Path $ProjectRoot 'outputs/go-mod'
$env:GOTOOLCHAIN = 'local'
$env:GOOS = 'linux'
$env:GOARCH = 'arm64'
$env:CGO_ENABLED = '0'
Push-Location $Source
try {
    & $Go build -trimpath -buildvcs=true -ldflags '-s -w' -o (Join-Path $ProjectRoot 'prebuilt/kn-1012/amneziawg-go') .
    if ($LASTEXITCODE) { throw 'Build failed' }
    & $Go version -m (Join-Path $ProjectRoot 'prebuilt/kn-1012/amneziawg-go')
} finally { Pop-Location }
