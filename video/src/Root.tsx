import React from "react";
import { Composition } from "remotion";
import { Recoup, TOTAL_FRAMES } from "./Recoup";
import { Smoke } from "./Smoke";
import { FPS, HEIGHT, WIDTH } from "./theme";

export const RemotionRoot: React.FC = () => (
  <>
    <Composition
      id="recoup"
      component={Recoup}
      durationInFrames={TOTAL_FRAMES}
      fps={FPS}
      width={WIDTH}
      height={HEIGHT}
    />
    {/* Kept: the toolchain check that ran before any content existed. */}
    <Composition
      id="smoke"
      component={Smoke}
      durationInFrames={3 * FPS}
      fps={FPS}
      width={WIDTH}
      height={HEIGHT}
    />
  </>
);
