# Technical Risks

Status key: OPEN (unresolved), MITIGATED (workable answer exists), CLOSED.

## R-01 No gyro stabilisation or horizon levelling — OPEN, highest impact

The proof of concept stitches and reframes correctly, but the horizon in the output is tilted
because the drone was banking. DJI Studio levels and stabilises using the gyro data in the
`djmd` track. That track is protobuf with an unpublished schema (`dvtm_AVATA360.proto`).

Options, in order of preference:
1. Guided DJI Studio step: user exports a stabilised equirectangular (panoramic) MP4, the
   application picks it up. Supported workflow, manual.
2. Visual horizon estimation per frame (sky/ground boundary) plus smoothing. Works only when
   a horizon is visible.
3. Decode the `djmd` protobuf. Unsupported reverse engineering; may break with firmware updates.

Until this is solved, the native FFmpeg path produces watchable output only for clips flown level.

## R-02 Colour mode — MITIGATED (2026-11-16)

Found in DJI metadata (DECISIONS D-014) and checked against 7 user-labelled clips. Remaining
doubt: in this sample every D-Log M clip was outdoor and every Normal clip indoor. The field
sits in the static camera header, not the GPS block, so a confound is unlikely; one indoor
D-Log M clip (5 seconds is enough) would settle it. Non-DJI files still need the statistical
fallback below.

Original note:

Every clip is tagged bt709 regardless of colour mode. Whether a clip is D-Log M or Normal is
not exposed in any readable metadata. Applying the D-Log M LUT to a Normal clip ruins it.

Mitigation: a statistical detector (low contrast, lifted blacks, capped highlights) gives a
guess with a confidence value; the user confirms per import batch; the choice is stored per
asset. Detector thresholds need a known-D-Log-M and a known-Normal clip of the same scene to
calibrate — not yet available.

## R-03 The LUT is validated only by eye — OPEN

DJI's own Avata 360 LUT was applied to a clip that is probably D-Log M. The result looks
natural, but there is no trusted reference (no colour chart, no DJI Studio export of the same
frame). Next step: export the same frame from DJI Studio with its LUT and compare numerically.

Also: the LUT lives inside the DJI Studio install. Redistribution rights are unknown, so the
application references it in place (or the copy the user downloads from DJI) and does not bundle it.

## R-14 Metadata holds GPS position — OPEN (privacy)

The `djmd` track carries latitude/longitude per frame. Never sent anywhere; never written into
exports unless the user asks. Could later name locations offline.

## R-04 Stitch quality — MITIGATED for preview, OPEN for final quality

Update 2026-11-16: the metadata header appears to hold per-lens calibration (fields 2.5.3 and
2.5.4: image centre, radius, distortion terms, orientation quaternion). Using it should give a
better stitch than the hand-picked 195°. Not yet decoded with confidence.

FFmpeg `v360` with a 195° lens field of view gives a clean result on distant scenery. It is a
hard cut with no blending, no per-lens calibration and no parallax handling. Near objects at
the seam will tear, and the seam lies on the horizon. 195° was chosen by eye from three values.

## R-05 Resolution ceiling — CLOSED (documented fact)

Each lens gives roughly 19.7 pixels per degree. A 100° wide reframe therefore holds about
2.7K of real detail. A 4K export at that field of view is a ~1.4x upscale. The 4K preset is
honest only for wide fields of view or equirectangular output.

## R-06 Render speed — MITIGATED

Measured: 6 s of 1080p output took 14.3 s (0.42x realtime) with software decode and software
`v360`, NVENC encode. A 90 s edit is therefore minutes, not hours. Proxies cut preview cost.
GPU decode and a GPU remap are possible later; not needed yet.

## R-07 DJI Studio cannot be automated — CLOSED (documented fact)

No CLI, API or SDK. GUI automation by screen coordinates is ruled out by the brief. The
reframe module therefore has two adapters: native FFmpeg, and a guided watch-folder workflow.

## R-08 DaVinci Resolve — CLOSED for now

Not installed. External scripting is a paid Studio feature, and reports say version 21.1
removed scripting from the free edition entirely (third-party source, not verified against
Blackmagic release notes). Resolve is not a dependency. An interchange export (OTIO/EDL/XML)
can be added later if the user wants a hand-off.

## R-09 No audio in the footage — CLOSED (documented fact)

None of the 7 clips has an audio stream. The audio engine is music-only for Avata 360
material; source-audio mixing and ducking matter only for other cameras.

## R-10 Disk space — OPEN

C: has 75 GB free, D: 97 GB. Source footage runs ~1.2 GB per minute. Proxies, intermediates
and renders must go to a user-chosen location with a space check before each job.

## R-11 Local model quality — OPEN

Local vision models have not been tested on fisheye or aerial frames. They must see reframed
flat frames, never raw fisheye. 8 GB VRAM means one model loaded at a time, and not while
NVENC rendering is running.

## R-12 FFmpeg location — OPEN, small

The only FFmpeg on PATH sits inside a yt-dlp folder and is an "essentials" build. The
application needs its own pinned copy.

## R-13 Python 3.14 as default — OPEN, small

Some media and machine-learning wheels lag behind new Python releases. The backend pins its
own interpreter with uv (3.12 or 3.13) rather than using the system default.
