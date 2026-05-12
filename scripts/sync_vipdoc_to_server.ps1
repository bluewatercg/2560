param(
  [string]$LocalRoot = "E:\zd_ciccwm\vipdoc",
  [string]$RemoteUser = "user",
  [string]$RemoteHost = "192.168.1.18",
  [string]$RemoteRoot = "/data1/2560/zd_ciccwm/vipdoc"
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path -LiteralPath $LocalRoot -PathType Container)) {
  throw "Local vipdoc directory not found: $LocalRoot"
}

$wslLocal = (wsl.exe wslpath -a "$LocalRoot").Trim()
$remote = "${RemoteUser}@${RemoteHost}:${RemoteRoot}"

Write-Host "[sync] local:  $LocalRoot"
Write-Host "[sync] wsl:    $wslLocal"
Write-Host "[sync] remote: $remote"
Write-Host "[sync] rsync requires SSH access to the server."

wsl.exe rsync -av --delete `
  --include='*/' `
  --include='*.day' `
  --include='*.lc5' `
  --exclude='*' `
  "$wslLocal/" "$remote/"

Write-Host "[sync] done"
