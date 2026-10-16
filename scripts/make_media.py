#!/usr/bin/env python3
"""生成演示用的录音（macOS 语音合成 + ffmpeg）：事故电话会议。输出 mp3 + 带时间戳的转写 json，随仓库提交。
运行一次即可；运行时不需要 macOS（入库用的是已提交的文件）。"""
import json
import subprocess
import tempfile
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "seed" / "enterprise" / "media"
LINES = [
    ("Raj Patel", "Daniel", "This is Raj, incident commander for I N C twenty two ninety one. Payment service started returning five hundreds at about two ten A M Singapore time. Error rate is above thirty percent."),
    ("Alice Tan", "Samantha", "Alice from payments. The connection pool for payment service is pinned at fifty out of fifty. The config service rollout at one fifty five lowered the max pool size from two hundred to fifty."),
    ("Raj Patel", "Daniel", "Understood. So the root cause is the pool limit, not the database. Alice, can you push the config revert?"),
    ("Alice Tan", "Samantha", "Reverting now. Pool size is back to two hundred. Error rate is dropping."),
    ("Raj Patel", "Daniel", "Confirmed. Error rate is back under one percent at two thirty one A M. Follow ups: add a saturation alert, load test the pool size, and update the runbook. I will write the postmortem."),
]


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    segs, t, parts = [], 0.0, []
    with tempfile.TemporaryDirectory() as tmp:
        for i, (who, voice, text) in enumerate(LINES):
            f = Path(tmp) / f"{i}.wav"
            subprocess.run(["say", "-v", voice, "-r", "175", "-o", str(f), "--data-format=LEI16@22050", text], check=True)
            dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(f)], capture_output=True, text=True).stdout)
            segs.append({"speaker": who, "start": round(t, 1), "end": round(t + dur, 1), "text": text.replace("I N C", "INC").replace("A M", "AM")})
            parts.append(f)
            t += dur + 0.4
        lst = Path(tmp) / "list.txt"
        lst.write_text("".join(f"file '{p}'\n" for p in parts))
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(lst), "-ac", "1", "-b:a", "48k", str(OUT / "inc-2291-bridge-call.mp3")], check=True)
    (OUT / "inc-2291-bridge-call.json").write_text(json.dumps({"duration": round(t, 1), "segments": segs}, ensure_ascii=False, indent=1), encoding="utf-8")
    print("ok", round(t, 1), "s")


if __name__ == "__main__":
    main()
