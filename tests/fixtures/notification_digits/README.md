# Real prize-fund crops

`star_vase.png` is a read-only BlueStacks capture from 2026-11-01 of the
star-vase event at 1080 x 1080. Its visible value is 28700. Dim blue scenery
must be permitted only after all three star-vase interface anchors match;
the pipeline must still require independent OCR agreement. No wishes were
made to capture this fixture. The matching label-only templates are stored
in assets/templates/layout/*_star_vase.png.

`star_vase_video.png` is a decoded H.264 frame crop from the same BlueStacks
event. Its visible value is 27450. It exercises the video-anchor path together
with the background permission, rather than only the still-image path.

These crops come from the bounded 20-wish recording on 2026-09-09.
They cover clean digits, a dark moving notification, white overlapping text,
and reward icons. They contain no inferred or cached OCR labels.

Manually visible values: 000 = 10050; 005 = 10200; 006 = 10250;
007 = 10300; 008 = 10350; 014 = 10650.
Crops 010, 017 and 022 contain substantial overlap and have no complete label.

The automated tests exercise the visibility veto and engine-control contract.
They use stub engines; actual RapidOCR/PaddleOCR replay results remain local
under runtime/fast_notification_20260909_102914/visibility_fix.json.
