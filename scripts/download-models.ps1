# Weights belong to MTG, not to this repository.
$ErrorActionPreference = "Stop"
$dir = Join-Path $PSScriptRoot "..\models"
New-Item -ItemType Directory -Force -Path $dir | Out-Null
$base = "https://essentia.upf.edu/models"
$files = @(
  @("feature-extractors/discogs-effnet", "discogs-effnet-bsdynamic-1.onnx"),
  @("classification-heads/mtg_jamendo_moodtheme", "mtg_jamendo_moodtheme-discogs-effnet-1.onnx"),
  @("classification-heads/mtg_jamendo_moodtheme", "mtg_jamendo_moodtheme-discogs-effnet-1.json"),
  @("classification-heads/mtg_jamendo_genre", "mtg_jamendo_genre-discogs-effnet-1.onnx"),
  @("classification-heads/mtg_jamendo_genre", "mtg_jamendo_genre-discogs-effnet-1.json"),
  @("classification-heads/voice_instrumental", "voice_instrumental-discogs-effnet-1.onnx"),
  @("classification-heads/voice_instrumental", "voice_instrumental-discogs-effnet-1.json")
)
foreach ($item in $files) {
  $url = "$base/$($item[0])/$($item[1])"
  $path = Join-Path $dir $item[1]
  if (!(Test-Path $path)) {
    Write-Host "Downloading $url"
    Invoke-WebRequest -Uri $url -OutFile $path
  }
  if ((Get-Item $path).Length -eq 0) { throw "Empty model: $path" }
}
Write-Host "Model files ready in $dir"
