"""
Turn the raw recording into the final walkthrough: trim the waits for AI replies,
lay the voice-over on the shifted timeline, and encode an MP4.
    .venv/bin/python video/make_video.py
"""
import json
import subprocess
from pathlib import Path

import imageio_ffmpeg

HERE = Path(__file__).parent
OUT = HERE / "out"
FINAL = HERE / "Churn_Radar_Walkthrough.mp4"
FF = imageio_ffmpeg.get_ffmpeg_exe()


def main(OUT=OUT, FINAL=FINAL):
    tl = json.loads((OUT / "timeline.json").read_text())
    cuts = sorted(tl["cuts"])
    keep, t = [], 0.0
    for a, b in cuts:
        if a > t:
            keep.append((t, a))
        t = max(t, b)
    keep.append((t, tl["total"] + 1))

    def shift(x):                                    # where a raw-time moment lands after trimming
        return x - sum(min(b, x) - a for a, b in cuts if a < x)

    vf = "".join(f"[0:v]trim=start={a:.3f}:end={b:.3f},setpts=PTS-STARTPTS[v{i}];" for i, (a, b) in enumerate(keep))
    vf += "".join(f"[v{i}]" for i in range(len(keep))) + f"concat=n={len(keep)}:v=1:a=0[v]"
    inputs, af = ["-i", str(OUT / "raw.webm")], []
    for k, e in enumerate(tl["events"]):
        inputs += ["-i", str(OUT / f"vo_{e['vo']}.wav")]
        ms = int(shift(e["t"]) * 1000)
        af.append(f"[{k + 1}:a]adelay={ms}|{ms}[a{k}]")
    n = len(tl["events"])
    filt = vf + ";" + ";".join(af) + ";" + "".join(f"[a{k}]" for k in range(n)) + f"amix=inputs={n}:normalize=0,volume=1.6[a]"
    (OUT / "filter.txt").write_text(filt)
    subprocess.run([FF, "-y", "-loglevel", "error", *inputs, "-filter_complex_script", str(OUT / "filter.txt"),
                    "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
                    "-r", "25", "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", "-shortest", str(FINAL)], check=True)
    print("wrote", FINAL, "·", round(shift(tl["total"]) / 60, 1), "min ·", round(sum(b - a for a, b in cuts)), "s of waiting trimmed")


if __name__ == "__main__":
    main()
