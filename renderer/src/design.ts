// Single source of truth for the reel's look and pacing.
// Brand colours sampled from the supplied logo.

export const FPS = 30;
export const WIDTH = 1080;
export const HEIGHT = 1920;

export const COLORS = {
  bg: '#051D3B',        // brand navy, matches the logo plate
  bgLift: '#0A2B54',    // subtle panel / rule
  fg: '#FFFFFF',
  muted: '#8FA6C4',
  accent: '#5BD748',    // brand green
};

export const FONT_DISPLAY = 'Poppins';
export const FONT_BODY = 'Inter';

// Layout grid. Everything is anchored, never centred, so nothing drifts
// between slides -- that was the main reason the earlier build felt unsteady.
export const MARGIN = 84;
export const RIGHT_KEEPOUT = 30;
export const CONTENT_W = WIDTH - MARGIN * 2 - RIGHT_KEEPOUT;

export type Format = 'reel' | 'carousel';

/** One design system, two canvases: 9:16 video for Meta, 4:5 stills for TikTok. */
export const layoutFor = (format: Format) =>
  format === 'reel'
    ? {
        width: 1080,
        height: 1920,
        logoTop: 96,
        logoH: 92,
        contentTop: 470,
        contentBottom: 1520,
        shareY: 1300,
        barY: 1600,
      }
    : {
        width: 1080,
        height: 1350,
        logoTop: 72,
        logoH: 84,
        contentTop: 330,
        contentBottom: 1040,
        shareY: 1090,
        barY: 1240,
      };

export const BAR_H = 8;

export const LINE_HEIGHT = 1.16;
export const BODY_LINE_HEIGHT = 1.34;

// Pacing: hold time is a function of copy length, so dense slides sit longer.
export const BASE_HOLD = 1.5;
export const PER_WORD = 0.26;
export const MIN_HOLD = 2.2;
export const MAX_HOLD = 5.5;
export const REEL_MAX = 90;

// Entry animation, identical on every slide.
export const ENTER_FRAMES = 11;
export const EXIT_FRAMES = 5;

export type Slide = {
  kind?: 'hook' | 'persona' | 'line' | 'reckoning' | 'cta';
  title?: string;
  amount?: string;
  includes?: string;
  body?: string;
  footer?: string;
};

export type Spec = {
  theme?: Record<string, string>;
  income?: number;   // net monthly salary, drives the share-of-salary rail
  audio?: string;    // bed filename in public/, rotated per post
  slides: Slide[];
};

const words = (s?: string) => (s ? s.trim().split(/\s+/).length : 0);

export const holdSeconds = (s: Slide) => {
  const n =
    words(s.title) + words(s.amount) + words(s.includes) + words(s.body) + words(s.footer);
  return Math.max(MIN_HOLD, Math.min(MAX_HOLD, BASE_HOLD + PER_WORD * n));
};

/** Frame counts per slide, compressed proportionally if the reel would exceed 90s. */
export const slideDurations = (slides: Slide[]): number[] => {
  let holds = slides.map(holdSeconds);
  const total = holds.reduce((a, b) => a + b, 0);
  if (total > REEL_MAX) {
    const k = (REEL_MAX - 0.5) / total;
    holds = holds.map((h) => h * k);
  }
  return holds.map((h) => Math.max(2, Math.round(h * FPS)));
};

/** SA amounts use a space as the thousands separator; keep "R26 500" unbreakable. */
export const protectNumbers = (s: string) => s.replace(/(?<=\d) (?=\d)/g, ' ');
