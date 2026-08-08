import {fitText, fitTextOnNLines, measureText} from '@remotion/layout-utils';
import {protectNumbers} from './design';

export type Fitted = {
  lines: string[];
  fontSize: number;
};

/**
 * Fit copy that carries deliberate line breaks (hooks, persona facts, amounts).
 * Authored newlines are preserved and NO new ones are introduced -- so
 * "R26 500 p/m" can never split after the rand figure.
 */
export const fitAuthored = ({
  text,
  width,
  fontFamily,
  fontWeight,
  maxFontSize,
}: {
  text: string;
  width: number;
  fontFamily: string;
  fontWeight: number;
  maxFontSize: number;
}): Fitted => {
  const lines = protectNumbers(text).split('\n').filter((l) => l.length > 0);
  let fontSize = maxFontSize;
  for (const line of lines) {
    const {fontSize: fits} = fitText({
      text: line,
      withinWidth: width,
      fontFamily,
      fontWeight,
      validateFontIsLoaded: true,
    });
    fontSize = Math.min(fontSize, fits);
  }
  return {lines, fontSize: Math.floor(fontSize)};
};

/**
 * Fit prose that may wrap, across one or more authored paragraphs.
 * Every paragraph shares one font size so the block reads as a single voice.
 */
export const fitProse = ({
  text,
  width,
  maxLines,
  fontFamily,
  fontWeight,
  maxFontSize,
}: {
  text: string;
  width: number;
  maxLines: number;
  fontFamily: string;
  fontWeight: number;
  maxFontSize: number;
}): {paragraphs: string[][]; fontSize: number} => {
  const paras = protectNumbers(text).split(/\n{2,}/).filter((p) => p.trim().length > 0);
  const budget = Math.max(1, Math.floor(maxLines / paras.length));

  let fontSize = maxFontSize;
  for (const p of paras) {
    const {fontSize: fits} = fitTextOnNLines({
      text: p,
      maxLines: budget,
      maxBoxWidth: width,
      fontFamily,
      fontWeight,
      maxFontSize,
      validateFontIsLoaded: true,
    });
    fontSize = Math.min(fontSize, fits);
  }
  fontSize = Math.floor(fontSize);

  const paragraphs = paras.map(
    (p) =>
      fitTextOnNLines({
        text: p,
        maxLines: 40,
        maxBoxWidth: width,
        fontFamily,
        fontWeight,
        maxFontSize: fontSize,
        validateFontIsLoaded: true,
      }).lines,
  );
  return {paragraphs, fontSize};
};

export const textHeight = ({
  text,
  fontFamily,
  fontWeight,
  fontSize,
}: {
  text: string;
  fontFamily: string;
  fontWeight: number;
  fontSize: number;
}) => measureText({text, fontFamily, fontWeight, fontSize, validateFontIsLoaded: true}).height;
