param(
    [Parameter(Mandatory=$true)][string]$AppId,
    [Parameter(Mandatory=$true)][string]$Version,
    [Parameter(Mandatory=$true)][string]$ZipPath,
    [string]$Repo = "joaovictorasousa2019/KBL-Updates"
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path $ZipPath)) { throw "Arquivo não encontrado: $ZipPath" }
if (-not (Get-Command gh -ErrorAction SilentlyContinue)) {
    throw "GitHub CLI (gh) não encontrado. Instale o GitHub CLI e execute gh auth login uma vez."
}

$manifestPath = "apps/$AppId/version.json"
$file = Get-Item $ZipPath
$fileName = $file.Name
$sha256 = (Get-FileHash -Path $file.FullName -Algorithm SHA256).Hash.ToLower()
$tag = "$AppId-v$Version"

Write-Host "Publicando $AppId v$Version..."
Write-Host "SHA-256: $sha256"

$releaseExists = $false
gh release view $tag --repo $Repo 1>$null 2>$null
if ($LASTEXITCODE -eq 0) { $releaseExists = $true }

if ($releaseExists) {
    gh release upload $tag $file.FullName --repo $Repo --clobber
} else {
    gh release create $tag $file.FullName --repo $Repo --title "$AppId v$Version" --notes "Atualização $AppId v$Version"
}
if ($LASTEXITCODE -ne 0) { throw "Falha ao publicar a Release." }

$escapedFile = [System.Uri]::EscapeDataString($fileName).Replace("%2F","/")
$downloadUrl = "https://github.com/$Repo/releases/download/$tag/$escapedFile"

$rawManifest = gh api "repos/$Repo/contents/$manifestPath" -H "Accept: application/vnd.github.raw+json"
if ($LASTEXITCODE -ne 0) { throw "Não foi possível ler $manifestPath." }

$manifest = $rawManifest | ConvertFrom-Json
$manifest.version = $Version
$manifest.published = $true
$manifest.download_url = $downloadUrl
$manifest.sha256 = $sha256
$manifest.file_name = $fileName
$manifest.published_at = (Get-Date).ToUniversalTime().ToString("o")

$json = $manifest | ConvertTo-Json -Depth 20
$bytes = [System.Text.Encoding]::UTF8.GetBytes($json)
$b64 = [Convert]::ToBase64String($bytes)
$currentSha = gh api "repos/$Repo/contents/$manifestPath" --jq ".sha"
if ($LASTEXITCODE -ne 0) { throw "Não foi possível obter o SHA do manifesto." }

gh api --method PUT "repos/$Repo/contents/$manifestPath" -f "message=Publica $AppId v$Version" -f "content=$b64" -f "sha=$currentSha" 1>$null
if ($LASTEXITCODE -ne 0) { throw "Release enviada, mas o manifesto não pôde ser atualizado." }

Write-Host ""
Write-Host "Atualização publicada com sucesso."
Write-Host "Versão: $Version"
Write-Host "Arquivo: $fileName"
Write-Host "Download: $downloadUrl"
Write-Host "Manifesto: $manifestPath"
