import React, {useEffect, useState} from 'react';
import {Composition, continueRender, delayRender} from 'remotion';
import '@fontsource/poppins/600.css';
import '@fontsource/poppins/700.css';
import '@fontsource/inter/400.css';
import '@fontsource/inter/500.css';
import {FPS, Spec, layoutFor, slideDurations} from './design';
import {CarouselSlide, Reel} from './Reel';
import specJson from '../spec.json';

/** Block rendering until the webfonts are usable — every text measurement
 *  taken against a fallback face produces a wrong layout. */
function withFonts<P extends object>(Inner: React.FC<P>): React.FC<P> {
  return (props: P) => {
    const [ready, setReady] = useState(false);
    const [handle] = useState(() => delayRender('loading fonts'));
    useEffect(() => {
      Promise.all([
        document.fonts.load('700 100px Poppins'),
        document.fonts.load('600 100px Poppins'),
        document.fonts.load('400 100px Inter'),
        document.fonts.load('500 100px Inter'),
      ])
        .then(() => document.fonts.ready)
        .then(() => {
          setReady(true);
          continueRender(handle);
        });
    }, [handle]);
    if (!ready) return null;
    return <Inner {...props} />;
  };
}

const ReelWithFonts = withFonts(Reel);
const SlideWithFonts = withFonts(CarouselSlide);
const reel = layoutFor('reel');
const carousel = layoutFor('carousel');

export const RemotionRoot: React.FC = () => (
  <>
    <Composition
      id="Reel"
      component={ReelWithFonts}
      width={reel.width}
      height={reel.height}
      fps={FPS}
      durationInFrames={300}
      defaultProps={{spec: specJson as Spec}}
      calculateMetadata={({props}) => ({
        durationInFrames: slideDurations(props.spec.slides).reduce((a, b) => a + b, 0),
      })}
    />
    <Composition
      id="CarouselSlide"
      component={SlideWithFonts}
      width={carousel.width}
      height={carousel.height}
      fps={FPS}
      durationInFrames={1}
      defaultProps={{spec: specJson as Spec, index: 0}}
    />
  </>
);
