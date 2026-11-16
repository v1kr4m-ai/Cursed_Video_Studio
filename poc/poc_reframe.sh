#!/usr/bin/env bash
# Phase 0 proof of concept: OSV dual fisheye -> flat reframe -> D-Log M LUT -> H.264 (NVENC).
# Usage: poc_reframe.sh <input.OSV> <start_seconds> <duration_seconds> <output.mp4>
# Reads the source only. Lens field of view (195) was chosen by eye; see TECHNICAL_RISKS R-04.
set -euo pipefail
IN="$1"; SS="$2"; DUR="$3"; OUT="$4"
LUT='C\:/Program Files/DJI Studio/1.0.0.30440/filter/LUT/LOG_Avata360_DLogM/DJI Avata 360 D-Log M to Rec.709 V1.cube'
REFRAME="v360=dfisheye:flat:ih_fov=195:iv_fov=195:pitch=80:h_fov=100:v_fov=64:w=1920:h=1080:interp=lanczos"

ffmpeg -hide_banner -v error -stats -y -ss "$SS" -t "$DUR" -i "$IN" \
  -filter_complex "[0:v:0][0:v:1]hstack,$REFRAME,lut3d=file='$LUT':interp=tetrahedral,format=yuv420p" \
  -c:v h264_nvenc -preset p5 -cq 20 -movflags +faststart "$OUT"

# Minimal check: fails if the output has no video frames or contains black/frozen sections.
FRAMES=$(ffprobe -v error -select_streams v:0 -show_entries stream=nb_frames -of csv=p=0 "$OUT")
[ "$FRAMES" -gt 0 ] || { echo "FAIL: no frames"; exit 1; }
if ffmpeg -hide_banner -i "$OUT" -vf "blackdetect=d=0.2,freezedetect=d=0.5" -an -f null - 2>&1 \
   | grep -qE "black_start|freeze_start"; then echo "FAIL: black or frozen frames"; exit 1; fi
echo "PASS: $FRAMES frames"
