import React from 'react';
import {
  AbsoluteFill,
  Audio,
  Img,
  Series,
  interpolate,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
} from 'remotion';
import {
  BAR_H,
  BODY_LINE_HEIGHT,
  COLORS,
  CONTENT_W,
  ENTER_FRAMES,
  FONT_BODY,
  FONT_DISPLAY,
  Format,
  LINE_HEIGHT,
  MARGIN,
  Slide,
  Spec,
  layoutFor,
  slideDurations,
} from './design';
import {fitAuthored, fitProse} from './fit';

type Block = {
  lines: string[][]; // paragraphs, each a list of laid-out lines
  fontSize: number;
  fontFamily: string;
  fontWeight: number;
  color: string;
  lineHeight: number;
  marginBottom: number;
};

const authored = (
  text: string,
  o: {max: number; family: string; weight: number; color: string; mb: number},
): Block => {
  const {lines, fontSize} = fitAuthored({
    text,
    width: CONTENT_W,
    fontFamily: o.family,
    fontWeight: o.weight,
    maxFontSize: o.max,
  });
  return {
    lines: [lines],
    fontSize,
    fontFamily: o.family,
    fontWeight: o.weight,
    color: o.color,
    lineHeight: LINE_HEIGHT,
    marginBottom: o.mb,
  };
};

const prose = (
  text: string,
  o: {max: number; maxLines: number; family: string; weight: number; color: string; mb: number},
): Block => {
  const {paragraphs, fontSize} = fitProse({
    text,
    width: CONTENT_W,
    maxLines: o.maxLines,
    fontFamily: o.family,
    fontWeight: o.weight,
    maxFontSize: o.max,
  });
  return {
    lines: paragraphs,
    fontSize,
    fontFamily: o.family,
    fontWeight: o.weight,
    color: o.color,
    lineHeight: BODY_LINE_HEIGHT,
    marginBottom: o.mb,
  };
};

const buildBlocks = (s: Slide): Block[] => {
  const kind = s.kind ?? 'line';
  const B: Block[] = [];

  if (kind === 'hook') {
    if (s.title) B.push(authored(s.title, {max: 136, family: FONT_DISPLAY, weight: 700, color: COLORS.fg, mb: 46}));
    if (s.footer) B.push(authored(s.footer, {max: 58, family: FONT_BODY, weight: 500, color: COLORS.accent, mb: 0}));
    return B;
  }
  if (kind === 'persona') {
    if (s.title) B.push(authored(s.title, {max: 82, family: FONT_DISPLAY, weight: 700, color: COLORS.accent, mb: 46}));
    if (s.body) B.push(authored(s.body, {max: 62, family: FONT_BODY, weight: 400, color: COLORS.fg, mb: 0}));
    return B;
  }
  if (kind === 'cta') {
    if (s.title) B.push(authored(s.title, {max: 102, family: FONT_DISPLAY, weight: 700, color: COLORS.fg, mb: 46}));
    if (s.body)
      B.push(prose(s.body, {max: 56, maxLines: 9, family: FONT_BODY, weight: 400, color: COLORS.muted, mb: 46}));
    if (s.footer) B.push(authored(s.footer, {max: 54, family: FONT_DISPLAY, weight: 600, color: COLORS.accent, mb: 0}));
    return B;
  }

  if (s.title) B.push(authored(s.title, {max: 94, family: FONT_DISPLAY, weight: 600, color: COLORS.fg, mb: 16}));
  if (s.amount) B.push(authored(s.amount, {max: 150, family: FONT_DISPLAY, weight: 700, color: COLORS.accent, mb: 42}));
  if (s.includes)
    B.push(prose(`Includes: ${s.includes}`, {max: 46, maxLines: 3, family: FONT_BODY, weight: 400, color: COLORS.muted, mb: 34}));
  if (s.body) B.push(prose(s.body, {max: 58, maxLines: 6, family: FONT_BODY, weight: 400, color: COLORS.fg, mb: 0}));
  return B;
};

const blockHeight = (b: Block) => {
  const n = b.lines.reduce((a, p) => a + p.length, 0);
  const gaps = (b.lines.length - 1) * b.fontSize * 0.55;
  return n * b.fontSize * b.lineHeight + gaps;
};

/** "R2 400 p/m" -> 2400 */
const randValue = (s?: string): number | null => {
  if (!s) return null;
  const m = s.replace(/ /g, ' ').match(/R\s?([\d ]+)/);
  if (!m) return null;
  const n = Number(m[1].replace(/ /g, ''));
  return Number.isFinite(n) && n > 0 ? n : null;
};

/**
 * Share-of-salary rail, pinned to a fixed y on every line-item slide.
 * The playbook's core mechanic is handing the viewer another number to measure
 * themselves against on each slide -- this is that number, and it doubles as
 * the bottom anchor of the composition.
 */
const ShareRail: React.FC<{
  amount?: string;
  income?: number;
  label: string;
  opacity: number;
  y: number;
}> = ({amount, income, label, opacity, y}) => {
  const value = randValue(amount);
  if (!value || !income) return null;
  const share = Math.min(1, value / income);
  return (
    <div style={{position: 'absolute', left: MARGIN, top: y, width: 1080 - MARGIN * 2, opacity}}>
      <div style={{fontFamily: FONT_BODY, fontWeight: 500, fontSize: 40, color: COLORS.muted, marginBottom: 18}}>
        <span style={{color: COLORS.accent, fontWeight: 600}}>{Math.round(share * 100)}%</span> {label}
      </div>
      <div style={{width: '100%', height: 14, borderRadius: 14, backgroundColor: COLORS.bgLift, overflow: 'hidden'}}>
        <div style={{width: `${share * 100}%`, height: '100%', borderRadius: 14, backgroundColor: COLORS.accent}} />
      </div>
    </div>
  );
};

export const SlideBody: React.FC<{
  slide: Slide;
  income?: number;
  format: Format;
  animate?: boolean;
}> = ({slide, income, format, animate = true}) => {
  const frame = useCurrentFrame();
  const L = layoutFor(format);
  const contentH = L.contentBottom - L.contentTop;

  const blocks = buildBlocks(slide);
  const total = blocks.reduce((a, b) => a + blockHeight(b) + b.marginBottom, 0);
  const scale = total > contentH ? contentH / total : 1;

  // The line-item slides all share one fixed anchor, so the eye never has to
  // re-find the copy mid-swipe. The three title cards centre instead, because
  // top-anchoring a four-line slide leaves an obvious hole beneath it.
  const kind = slide.kind ?? 'line';
  const centred = kind === 'hook' || kind === 'persona' || kind === 'cta';
  const offset = centred ? Math.max(0, (contentH - total * scale) / 2) : 0;
  const isLine = kind === 'line' || kind === 'reckoning';

  // one identical entrance for every slide, then dead still
  const eased = animate
    ? interpolate(frame, [0, ENTER_FRAMES], [0, 1], {
        extrapolateLeft: 'clamp',
        extrapolateRight: 'clamp',
        easing: (t) => 1 - Math.pow(1 - t, 3),
      })
    : 1;
  const opacity = animate
    ? interpolate(frame, [0, ENTER_FRAMES - 3], [0, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'})
    : 1;
  const dy = (1 - eased) * 26;

  return (
    <>
      <div
        style={{
          position: 'absolute',
          left: MARGIN,
          top: L.contentTop + offset,
          width: CONTENT_W,
          opacity,
          transform: `translateY(${dy}px) scale(${scale})`,
          transformOrigin: 'top left',
        }}
      >
        {blocks.map((b, i) => (
          <div key={i} style={{marginBottom: b.marginBottom}}>
            {b.lines.map((para, pi) => (
              <div key={pi} style={{marginTop: pi === 0 ? 0 : b.fontSize * 0.55}}>
                {para.map((line, li) => (
                  <div
                    key={li}
                    style={{
                      fontFamily: b.fontFamily,
                      fontWeight: b.fontWeight,
                      fontSize: b.fontSize,
                      lineHeight: b.lineHeight,
                      color: b.color,
                      whiteSpace: 'pre',
                      letterSpacing: b.fontFamily === FONT_DISPLAY ? '-0.015em' : '0',
                    }}
                  >
                    {line}
                  </div>
                ))}
              </div>
            ))}
          </div>
        ))}
      </div>
      {isLine ? (
        <ShareRail
          amount={slide.amount}
          income={income}
          label={kind === 'reckoning' ? 'of my salary is left' : 'of my salary'}
          opacity={opacity}
          y={L.shareY}
        />
      ) : null}
    </>
  );
};

const Chrome: React.FC<{format: Format; index: number; count: number; progress: number}> = ({
  format,
  index,
  count,
  progress,
}) => {
  const L = layoutFor(format);
  return (
    <>
      <Img
        src={staticFile('logo.png')}
        style={{position: 'absolute', left: MARGIN, top: L.logoTop, height: L.logoH}}
      />
      <div
        style={{
          position: 'absolute',
          left: MARGIN,
          top: L.barY - 54,
          fontFamily: FONT_BODY,
          fontWeight: 400,
          fontSize: 32,
          color: COLORS.muted,
        }}
      >
        {index + 1}/{count}
      </div>
      <div
        style={{
          position: 'absolute',
          left: MARGIN,
          top: L.barY,
          width: 1080 - MARGIN * 2,
          height: BAR_H,
          borderRadius: BAR_H,
          backgroundColor: COLORS.bgLift,
        }}
      />
      <div
        style={{
          position: 'absolute',
          left: MARGIN,
          top: L.barY,
          width: (1080 - MARGIN * 2) * progress,
          height: BAR_H,
          borderRadius: BAR_H,
          backgroundColor: COLORS.accent,
        }}
      />
    </>
  );
};

/** 9:16 video for Facebook and Instagram Reels. */
export const Reel: React.FC<{spec: Spec}> = ({spec}) => {
  const frame = useCurrentFrame();
  const {durationInFrames} = useVideoConfig();
  const slides = spec.slides;
  const durations = slideDurations(slides);

  let acc = 0;
  let index = 0;
  for (let i = 0; i < durations.length; i++) {
    if (frame >= acc) index = i;
    acc += durations[i];
  }

  return (
    <AbsoluteFill style={{backgroundColor: COLORS.bg}}>
      <Audio
        src={staticFile(spec.audio ?? 'bed_01.wav')}
        loop
        volume={(f) =>
          interpolate(f, [durationInFrames - 45, durationInFrames - 1], [1, 0], {
            extrapolateLeft: 'clamp',
            extrapolateRight: 'clamp',
          })
        }
      />
      <Series>
        {slides.map((s, i) => (
          <Series.Sequence key={i} durationInFrames={durations[i]}>
            <SlideBody slide={s} income={spec.income} format="reel" />
          </Series.Sequence>
        ))}
      </Series>
      <Chrome
        format="reel"
        index={index}
        count={slides.length}
        progress={interpolate(frame, [0, durationInFrames - 1], [0, 1], {extrapolateRight: 'clamp'})}
      />
    </AbsoluteFill>
  );
};

/** 4:5 still for the TikTok photo carousel -- same design system, one frame. */
export const CarouselSlide: React.FC<{spec: Spec; index: number}> = ({spec, index}) => {
  const slides = spec.slides;
  const i = Math.max(0, Math.min(slides.length - 1, index));
  return (
    <AbsoluteFill style={{backgroundColor: COLORS.bg}}>
      <SlideBody slide={slides[i]} income={spec.income} format="carousel" animate={false} />
      <Chrome format="carousel" index={i} count={slides.length} progress={(i + 1) / slides.length} />
    </AbsoluteFill>
  );
};
