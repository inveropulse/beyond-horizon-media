# Beyond Horizon — content production spec

The reference definition of a valid Beyond Horizon post. Written to become a
skill: prescriptive, so following it exactly produces predictable output.

One carousel spec produces **both** deliverables:

| Platform | Format | Output |
|---|---|---|
| TikTok | photo carousel | `out/carousel/slide_NN.png`, 1080×1350 |
| Facebook + Instagram | Reel | `out/reel.mp4`, 1080×1920 |

Same design system, same brand, one source file. Rendered with **Remotion**
(React → deterministic video), not ffmpeg filters — the earlier `zoompan`
approach quantised its zoom steps and juddered visibly on static slides.

---

## 1. Why this split

The `beyond-horizon-carousels` playbook is built on a 268-post extraction from a
competing SA account: **264 of 268 posts were photo carousels, and the four
videos averaged under 2K views against a carousel median of ~2,900.** In this
niche, on TikTok, static slides win — the content is numbers, and numbers reward
pausing and re-reading.

That evidence says nothing about Facebook and Instagram, where Meta actively
pushes Reels distribution. Hence: carousels to TikTok, reels to Meta.

## 2. Motion rules

The earlier build felt unsteady because the frame was in constant motion and
each slide composed differently. The rules that fix it:

1. **Nothing zooms, pans or drifts.** After a slide's entrance it is completely
   still.
2. **One entrance, used everywhere.** 11 frames, rise 26 px with a cubic ease-out,
   fade in over 8. Every slide, no exceptions.
3. **Persistent chrome.** Logo, counter and progress bar are mounted once for the
   whole video and never re-animate — so nothing flickers at a slide boundary.
4. **One anchor for the body.** Every line-item slide starts its copy at exactly
   the same y. The eye never has to re-find the text mid-swipe. Only the three
   title cards (hook, persona, close) centre instead, because top-anchoring a
   four-line slide leaves an obvious hole.

## 3. Layout

| | Reel (1080×1920) | Carousel (1080×1350) |
|---|---|---|
| Logo top / height | 96 / 92 | 72 / 84 |
| Content top | 470 | 330 |
| Content bottom | 1520 | 1040 |
| Share rail | 1300 | 1090 |
| Counter + progress bar | 1600 | 1240 |

Left/right gutter 84 px, with a further 30 px right keep-out for platform action
rails. Below the progress bar is left empty — that band is platform UI.

**Type:** Poppins 600/700 for display (matches the logo's geometric sans), Inter
400/500 for body. Sizes are maxima; copy is measured with
`@remotion/layout-utils` and stepped down until it fits. Long copy gets smaller,
it never clips or overflows.

**Never wraps:** amounts, hook lines and the persona block. Authored line breaks
are honoured and no new ones are introduced, so `R26 500 p/m` cannot break after
the rand figure. SA amounts use a space as the thousands separator, which naive
wrapping splits — a non-breaking space is substituted before measuring.

## 4. The share-of-salary rail

Every line-item slide carries a fixed rail showing what proportion of the salary
that category eats — `23% of my salary` with a filled track. On the reckoning
slide it reads `6% of my salary is left`.

It is computed automatically from the slide's `amount` and the spec's `income`;
no extra authoring. It exists for two reasons: the playbook's core mechanic is
giving the viewer another number to measure themselves against on every slide,
and it anchors the bottom of the composition so the frame isn't half empty.

## 5. Spec schema

```jsonc
{
  "income": 26500,              // net monthly salary — drives the share rail
  "slides": [
    {"kind": "hook",      "title": "How I spend\nmy R26 500\np/m salary",
                          "footer": "South Africa"},
    {"kind": "persona",   "title": "Living in Durban",
                          "body": "Female, 31\nSingle, no kids\n..."},
    {"kind": "line",      "title": "Rent", "amount": "R6 200 p/m",
                          "includes": "1 bed in Berea, water, refuse",
                          "body": "one or two lines of first-person commentary"},
    {"kind": "reckoning", "title": "What's left", "amount": "R1 650",
                          "body": "Out of R26 500. ..."},
    {"kind": "cta",       "title": "I stopped guessing", "body": "...",
                          "footer": "beyondhorizon.app — free to start"}
  ]
}
```

Content rules carried from the playbook: 12–16 slides; rand figure in the hook;
net salary not gross; line items ordered largest to smallest; at least one number
the persona isn't proud of; include the lines most budget content omits (black
tax, stokvel, funeral policy); **the line items must sum exactly to income minus
the reckoning figure.**

## 6. Producing a post

```bash
cd reel
npm install                 # once
node render-all.mjs         # reads spec.json, writes out/
```

Roughly 6 minutes for a 16-slide post on 2 cores. Outputs `out/reel.mp4` and
`out/carousel/slide_01..NN.png`.

Assets in `public/`: `logo.png` (the on-dark lockup) and `bed.wav` (the audio
bed). Audio **must be WAV** — the headless Chromium used for rendering has no
AAC decoder, so an `.m4a` bed fails at frame 0.

## 7. Acceptance checklist

- [ ] `ffprobe`: h264, yuv420p, 1080×1920, 30 fps
- [ ] duration 3–90 s, and not within 2 s of 90
- [ ] audio stream present, AAC, RMS between −22 and −16 dBFS, not silent
- [ ] 12–16 slides
- [ ] rand figure in the hook
- [ ] line items sum exactly to income − reckoning
- [ ] no amount wraps across two lines
- [ ] logo legible on first and last frame
- [ ] nothing rendered below the progress bar
- [ ] caption ends in a question, exactly 5 hashtags

## 8. Open items

**Buffer caps TikTok carousels at 10 images**, but the playbook says 12+ slides
roughly doubles median views against ≤8, and TikTok itself allows up to 35. So
scheduling TikTok through Buffer costs you six slides on a 16-slide post. Either
post TikTok by hand, use a scheduler without that cap, or accept 10 — worth
deciding deliberately rather than discovering it in the queue.

**The audio bed is synthesised.** `make_bed.py` produces a 112 BPM
amapiano-shaped placeholder so the pipeline can be demonstrated end to end. It is
not licensed music — replace with Meta Sound Collection (safest on Facebook,
since Meta never flags its own catalogue) or Mixkit before publishing.

**Trending sound cannot be attached through any API** on either platform. Burned-in
audio is the only automated option.
