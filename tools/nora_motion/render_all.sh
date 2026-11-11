#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
python render.py --audio
python render.py
python render.py --portrait
ffprobe -v error -show_entries format=duration:stream=codec_name,width,height,avg_frame_rate -of compact ../../../NORA_showcase_horizontal_1920x1080.mp4
ffprobe -v error -show_entries format=duration:stream=codec_name,width,height,avg_frame_rate -of compact ../../../NORA_showcase_vertical_1080x1920.mp4
