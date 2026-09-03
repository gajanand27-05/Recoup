import React from "react";
import { useCurrentFrame } from "remotion";

export const Smoke: React.FC = () => {
  const frame = useCurrentFrame();
  return (
    <div style={{
      flex: 1, backgroundColor: "#0d1117", color: "#e6edf3",
      display: "flex", alignItems: "center", justifyContent: "center",
      fontFamily: "monospace", fontSize: 64,
    }}>
      toolchain smoke — frame {frame}
    </div>
  );
};
