$ErrorActionPreference = 'Stop'
$Here = Split-Path -Parent $MyInvocation.MyCommand.Path
Push-Location $Here
try {
    python render.py --audio
    if ($LASTEXITCODE -ne 0) { throw 'Audio render failed' }
    python render.py
    if ($LASTEXITCODE -ne 0) { throw 'Horizontal render failed' }
    python render.py --portrait
    if ($LASTEXITCODE -ne 0) { throw 'Vertical render failed' }
    ffprobe -v error -show_entries format=duration:stream=codec_name,width,height,avg_frame_rate -of compact ../../../NORA_showcase_horizontal_1920x1080.mp4
    ffprobe -v error -show_entries format=duration:stream=codec_name,width,height,avg_frame_rate -of compact ../../../NORA_showcase_vertical_1080x1920.mp4
} finally {
    Pop-Location
}
