import {Config} from '@remotion/cli/config';
Config.setVideoImageFormat('jpeg');
// yuvj420p (full-range) is what jpeg frames produce by default, and some
// platforms re-encode it with shifted colour. Force standard limited-range.
Config.setPixelFormat('yuv420p');
Config.setColorSpace('bt709');
Config.setOverwriteOutput(true);
Config.setChromiumOpenGlRenderer('swangle');
