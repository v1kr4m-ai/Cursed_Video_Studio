# Environment Report

Inspected 2026-11-16. Everything below was measured on this machine unless marked otherwise.

## Machine

| Item | Value |
|---|---|
| OS | Windows 11 Home Single Language, 10.0.26300.9818 |
| GPU | NVIDIA GeForce RTX 5060 Laptop, 8151 MiB VRAM, driver 621.14 |
| CUDA | Available (PyTorch 2.12.1+cu130 reports `cuda.is_available() == True`) |
| Disk C: | 924 GB, 75 GB free (92% used) |
| Disk D: | 601 GB, 97 GB free (84% used) |

CPU and RAM were not re-measured; the brief states Core Ultra 9 275HX and 32 GB.

## Tools

| Tool | Version | Path / note |
|---|---|---|
| Python | 3.14.3 (default); 3.13, 3.10, 3.9 also via `py` | `C:\Python314` |
| uv | present | `~\.local\bin\uv` |
| Node.js / npm | 25.8.2 / 11.17.0 | |
| Git | 2.53.0.windows.2 | |
| FFmpeg / FFprobe | 8.1 essentials (gyan.dev) | `%USERPROFILE%\Videos\yt-dlp\` — lives in a yt-dlp folder, not a stable location |
| Ollama | installed, 18 models | see below |
| Docker | installed | not required |
| Rust / Cargo | **missing** | required for Tauri |
| MSVC Build Tools | 2019, 2022, 2026 | Tauri prerequisite satisfied |
| WebView2 Runtime | 157.0.4341.46 | Tauri prerequisite satisfied |
| DJI Studio | 1.0.0.30440 | `C:\Program Files\DJI Studio` |
| DaVinci Resolve | **not installed** | |
| exiftool | missing | |

### FFmpeg capabilities (confirmed present)

- Encoders: `h264_nvenc`, `hevc_nvenc`, `av1_nvenc`, `libx264`, `libx265`, QSV variants.
- Hardware acceleration: cuda, qsv, d3d11va, d3d12va, dxva2.
- Filters: `v360`, `lut3d`, `zscale`, `colorspace`, `tonemap`, `scdet`, `blackdetect`,
  `freezedetect`, `loudnorm`, `ebur128`, `vidstabdetect`/`vidstabtransform`, `libvmaf`.
- Not present: `libplacebo`.

## Git

`D:\Claude\Cursed_Video_Studio` is a subfolder of a large repository rooted at `D:\Claude`
(branch `master`, many unrelated pending changes). The project folder was empty at start.
Nothing has been committed. See DECISIONS.md D-009.

## Sample footage

The owner's local Avata 360 folder — 7 `.OSV` clips (24 GB total) with `.LRF` proxies for 6.
Originals were only read, never written.

| Clip | Resolution per lens | fps | Duration | Scene | Looks log? |
|---|---|---|---|---|---|
| 20260429132244_0001 | 3840x3840 | 29.97 | 32 s | indoor | no |
| 20260429215709_0002 | 3000x3000 | 50 | 20 s | indoor | no |
| 20260925050123_0003 | 3840x3840 | 29.97 | 83 s | indoor, dim | no |
| 20260927122159_0011 | 3840x3840 | 29.97 | 41 s | indoor, bright | unclear |
| 20261020234747_0012 | 3840x3840 | 29.97 | 180 s | night aerial | unclear |
| 20261026180320_0013 | 3840x3840 | 29.97 | 479 s | dusk aerial | probably |
| 20261026182115_0002 | 3840x3840 | 29.97 | 324 s | dusk aerial | probably |

"Looks log" is a judgement from luma statistics and a visual check, not a fact read from the
file. See TECHNICAL_RISKS.md R-02.

### OSV container (measured with FFprobe)

An OSV is an MP4-family container holding:

- Stream 0 and 1: HEVC Main 10, `yuv420p10le`, one square fisheye image per lens, ~65–78 Mbit/s each.
  Lens A looks up, lens B looks down, so the horizon sits on the stitch seam.
- Streams 2–3: `djmd` data ("CAM meta"), protobuf, schema name `dvtm_AVATA360.proto`.
- Streams 4–5: `dbgi` data. Stream 6: `camd` data.
- Stream 7: 960x540 MJPEG thumbnail.
- **No audio stream** in any of the 7 clips.
- Colour tags say bt709 for range/matrix/transfer/primaries in every clip, whatever the colour mode.

An LRF is a 1920x960 8-bit HEVC proxy, also dual fisheye (two 960x960 circles), at 25 fps
even when the original is 50 fps.

### DJI Studio install

- GUI application (Qt). No command-line interface, API or SDK was found in the install or in
  DJI's public material.
- Ships LUTs at `<install>\1.0.0.30440\filter\LUT\`. `LOG_Avata360_DLogM` contains
  `DJI Avata 360 D-Log M to Rec.709 V1.cube` (33-point, md5 `371ec662…`). It is a different
  file from the Avata 2 and Osmo 360 LUTs, which are byte-identical to each other.

## AI models and routing

### What can actually be invoked

| Model | How | Vision | Size | Use |
|---|---|---|---|---|
| Claude Fable 5.2 (this session) | Claude Code | yes | cloud | architecture, integration, hard debugging, review |
| Claude subagents (Sonnet/Haiku/Opus via Agent tool) | Claude Code | yes | cloud | development-time delegation only |
| `qwen3:8b`, `qwen2.5:7b` | Ollama HTTP, localhost:11434 | no | 5 GB | Director draft plans, metadata classification |
| `gpt-oss:20b`, `phi4` | Ollama | no | 13 / 9 GB | Director, partly on CPU (exceeds 8 GB VRAM) |
| `qwen3-coder:30b`, `glm-4.7-flash` | Ollama | no | 18–19 GB | too large for VRAM, slow; not planned |
| `llama3.2-vision` | Ollama | yes | 7.8 GB | frame understanding; tight fit in 8 GB |
| `llava`, `moondream` | Ollama | yes | 4.7 / 1.7 GB | fast frame tagging |
| `nomic-embed-text` | Ollama | no | 274 MB | shot similarity / de-duplication |
| `gemma4:31b-cloud` | Ollama cloud | unknown | cloud | off by default (footage must not leave the machine) |

None of the Ollama models was run in Phase 0. Their quality on aerial footage is unknown.

### Routing

| Task | First choice | Fallback |
|---|---|---|
| Frame tagging (scene, subject) | `moondream` / `llava` | `llama3.2-vision` |
| Composition and shot quality | deterministic metrics first, then `llama3.2-vision` | cloud vision model, only if the user enables cloud |
| Edit plan from a brief | `qwen3:8b` with JSON-schema-constrained output | `gpt-oss:20b`; cloud model if enabled |
| Colour, stitching, render, QC | no model — deterministic code | — |
| Building the application | Claude (this session and subagents) | — |

The runtime application talks to models only through `model_gateway`; the Claude models in
this table build the product and are not a runtime dependency.

### MCP servers

Connected and relevant: none required for the product. `openchatcut` failed to connect.
Blender, Canva, n8n, browser and Google connectors exist but are not part of this design.
