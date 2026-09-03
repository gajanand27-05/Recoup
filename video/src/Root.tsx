import React from "react";
import { Composition } from "remotion";
import { Smoke } from "./Smoke";

export const FPS = 30;

export const RemotionRoot: React.FC = () => (
  <>
    {/* STEP 0a: a trivial composition rendered BEFORE any content exists.
        Discovering an ffmpeg or Chromium problem after six scenes exist is the
        expensive order. */}
    <Composition
      id="smoke"
      component={Smoke}
      durationInFrames={3 * FPS}
      fps={FPS}
      width={1920}
      height={1080}
    />
  </>
);
