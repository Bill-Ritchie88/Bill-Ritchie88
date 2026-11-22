#!/usr/bin/env python3
"""Clipper: turn a long video into short vertical clips with burned-in captions.

Pipeline:
  1. Get a word-level transcript (Whisper, or an .srt/.vtt file you provide).
  2. Score every 15-60s window that starts and ends on a sentence boundary
     (hook strength, energy/loudness, speech pace, complete thought).
  3. Pick the best non-overlapping windows (or use times you give).
  4. Render each as a 1080x1920 clip with big word-by-word captions.

Only clip videos you have permission to use (your own, a paid clipping
campaign, or a creator who hired you).
"""
import argparse
import json
import math
import re
import shutil
import subprocess
import sys
from pathlib import Path

W, H = 1080, 1920

HOOK_WORDS = {
    "secret", "secrets", "never", "always", "nobody", "everyone", "truth", "mistake",
    "mistakes", "crazy", "insane", "shocking", "worst", "best", "biggest", "why", "how",
    "stop", "wrong", "actually", "honestly", "money", "million", "millions", "billion",
    "rich", "broke", "free", "hack", "trick", "lie", "lied", "fired", "quit", "died",
    "hate", "love", "afraid", "scared", "warning", "problem", "real", "really", "listen",
    "imagine", "story", "first", "last", "only", "nobody", "everybody", "change", "changed",
}
STOPWORDS = set("""a an the and or but if then so to of in on at for with from by is are was were be been
being it its this that these those i you he she we they me him her us them my your our their his
not no yes do does did have has had just like know think yeah um uh oh okay ok right gonna wanna
what when where who which there here can could would should will about out up down get got go going
really very all some any more most one two also than as into because been im dont thats its""".split())


# ----------------------------------------------------------------- helpers
def run(cmd, **kw):
    return subprocess.run(cmd, check=True, capture_output=True, text=True, **kw)


def ts(t):
    t = max(0.0, t)
    return f"{int(t // 3600)}:{int(t % 3600 // 60):02d}:{t % 60:05.2f}"


def parse_time(s):
    parts = [float(p) for p in s.strip().split(":")]
    sec = 0.0
    for p in parts:
        sec = sec * 60 + p
    return sec


def duration_of(path):
    out = run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
               "-of", "default=nw=1:nk=1", str(path)]).stdout
    return float(out.strip())


def has_audio(path):
    out = run(["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries",
               "stream=index", "-of", "csv=p=0", str(path)]).stdout
    return bool(out.strip())


# -------------------------------------------------------------- transcript
def transcribe(video, model_name, language):
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        sys.exit("faster-whisper is not installed. Run: pip install faster-whisper\n"
                 "(or pass --transcript your_subtitles.srt)")
    print(f"Transcribing with Whisper '{model_name}' (first run downloads the model)...")
    model = WhisperModel(model_name, device="auto", compute_type="int8")
    # decode audio with ffmpeg (16 kHz mono float) - avoids PyAV version problems
    import numpy as np
    raw = subprocess.run(["ffmpeg", "-nostdin", "-loglevel", "error", "-i", str(video), "-vn",
                          "-ac", "1", "-ar", "16000", "-f", "f32le", "-"],
                         check=True, capture_output=True).stdout
    audio = np.frombuffer(raw, dtype=np.float32)
    segments, info = model.transcribe(audio, word_timestamps=True, vad_filter=True,
                                      language=language)
    words = []
    for seg in segments:
        for w in seg.words or []:
            text = w.word.strip()
            if text:
                words.append({"start": w.start, "end": w.end, "text": text})
        print(f"  ...{ts(seg.end)}", end="\r", flush=True)
    print()
    return words


def load_subtitles(path):
    """Read .srt or .vtt and spread each cue's words evenly across its time."""
    raw = Path(path).read_text(encoding="utf-8", errors="ignore").replace("\r", "")
    words = []
    for block in re.split(r"\n\s*\n", raw):
        m = re.search(r"(\d[\d:.,]*)\s*-->\s*(\d[\d:.,]*)", block)
        if not m:
            continue
        start, end = (parse_time(x.replace(",", ".")) for x in m.groups())
        text_lines = block[m.end():].strip().split("\n")
        text = re.sub(r"<[^>]+>", "", " ".join(text_lines)).strip()
        toks = text.split()
        if not toks or end <= start:
            continue
        step = (end - start) / len(toks)
        for i, tok in enumerate(toks):
            words.append({"start": start + i * step, "end": start + (i + 1) * step, "text": tok})
    # de-duplicate overlapping auto-caption repeats (common in YouTube .vtt)
    clean = []
    for w in words:
        if clean and w["text"] == clean[-1]["text"] and w["start"] < clean[-1]["end"] + 0.05:
            continue
        clean.append(w)
    return clean


def get_transcript(args, video, workdir):
    if args.transcript:
        return load_subtitles(args.transcript)
    cache = workdir / "transcript.json"
    if cache.exists() and not args.retranscribe:
        print(f"Using cached transcript {cache}")
        return json.loads(cache.read_text())
    words = transcribe(video, args.model, args.language)
    cache.write_text(json.dumps(words))
    return words


# ----------------------------------------------------------------- scoring
def loudness_per_second(video, length):
    """Momentary loudness (LUFS) averaged per second via ffmpeg ebur128."""
    if not has_audio(video):
        return [0.0] * (int(length) + 1)
    p = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(video), "-vn",
                        "-af", "ebur128", "-f", "null", "-"], capture_output=True, text=True)
    buckets = {}
    for m in re.finditer(r"t:\s*([\d.]+).*?M:\s*(-?[\d.]+|-inf)", p.stderr):
        t, val = float(m.group(1)), m.group(2)
        v = -70.0 if "inf" in val else max(-70.0, float(val))
        buckets.setdefault(int(t), []).append(v)
    return [sum(buckets[s]) / len(buckets[s]) if s in buckets else -70.0
            for s in range(int(length) + 1)]


def split_sentences(words):
    sents, cur = [], []
    for i, w in enumerate(words):
        cur.append(i)
        nxt = words[i + 1] if i + 1 < len(words) else None
        ends = re.search(r"[.!?]['\")\]]*$", w["text"])
        gap = nxt and nxt["start"] - w["end"] > 0.8
        if ends or gap or nxt is None or len(cur) >= 40:
            sents.append(cur)
            cur = []
    return sents


def norm(word):
    return re.sub(r"[^a-z0-9']", "", word.lower())


def hook_score(words):
    first = [norm(w["text"]) for w in words[:12]]
    text = " ".join(w["text"] for w in words[:15])
    s = sum(1.0 for w in first if w in HOOK_WORDS)
    s += 1.0 if "?" in text else 0
    s += 0.7 if re.search(r"\d", text) else 0
    s += 0.5 if any(w in ("you", "your", "you're") for w in first) else 0
    return min(s, 5.0)


def find_highlights(words, loud, args):
    sents = split_sentences(words)
    lmean = sum(loud) / len(loud)
    lstd = math.sqrt(sum((x - lmean) ** 2 for x in loud) / len(loud)) or 1.0
    cands = []
    for i in range(len(sents)):
        start = words[sents[i][0]]["start"]
        for j in range(i, len(sents)):
            end = words[sents[j][-1]]["end"]
            dur = end - start
            if dur > args.max_len:
                break
            if dur < args.min_len:
                continue
            idx = [k for s in sents[i:j + 1] for k in s]
            cw = [words[k] for k in idx]
            content = [norm(w["text"]) for w in cw if norm(w["text"]) not in STOPWORDS]
            pace = len(cw) / dur                                    # words per second
            secs = loud[int(start):int(end) + 1] or [lmean]
            energy = (sum(secs) / len(secs) - lmean) / lstd         # z-score
            peak = (max(secs) - lmean) / lstd
            kw = sum(1 for w in content if w in HOOK_WORDS) / max(1, len(content))
            complete = 1.0 if re.search(r"[.!?]['\")\]]*$", cw[-1]["text"]) else 0.0
            length_fit = 1 - abs(dur - args.target_len) / args.max_len
            score = (2.0 * hook_score(cw) + 1.5 * energy + 0.5 * peak + 1.0 * min(pace, 4)
                     + 6.0 * kw + 1.0 * complete + 2.0 * length_fit)
            cands.append({"start": start, "end": end, "score": round(score, 2),
                          "first": idx[0], "last": idx[-1]})
    cands.sort(key=lambda c: c["score"], reverse=True)
    picked = []
    for c in cands:
        if all(c["end"] + 2 <= p["start"] or c["start"] >= p["end"] + 2 for p in picked):
            picked.append(c)
        if len(picked) >= args.count:
            break
    return sorted(picked, key=lambda c: c["start"])


def hype_highlights(loud, words, args):
    """Gaming/stream mode: pick the most intense moments by audio energy.

    Favors a loud peak (scream, explosion, big reaction) that lands in the
    middle-to-late part of the clip, so the clip has build-up and payoff.
    """
    n = len(loud)
    mean = sum(loud) / n
    std = math.sqrt(sum((x - mean) ** 2 for x in loud) / n) or 1.0
    z = [(x - mean) / std for x in loud]
    sm = [sum(z[max(0, i - 1):i + 2]) / len(z[max(0, i - 1):i + 2]) for i in range(n)]
    lengths = range(int(args.min_len), int(args.max_len) + 1, 5)
    cands = []
    for L in lengths:
        for s in range(0, max(1, n - L), 2):
            seg = sm[s:s + L]
            if len(seg) < L:
                continue
            third = max(1, L // 3)
            peak = max(seg)
            pos = seg.index(peak) / L
            build = sum(seg[-third:]) / third - sum(seg[:third]) / third
            score = (2.0 * peak + 0.3 * sum(seg) / L + 0.15 * max(build, 0)
                     + (1.0 if 0.35 <= pos <= 0.85 else 0.0)
                     + 2.0 * (1 - abs(L - args.target_len) / args.max_len))
            cands.append({"start": float(s), "end": float(s + L), "score": score})
    cands.sort(key=lambda c: c["score"], reverse=True)
    picked = []
    for c in cands:
        if all(c["end"] + 3 <= p["start"] or c["start"] >= p["end"] + 3 for p in picked):
            picked.append(c)
        if len(picked) >= args.count:
            break
    if words:  # snap to sentence boundaries so clips start and end cleanly
        sents = split_sentences(words)
        starts = [words[s[0]]["start"] for s in sents]
        ends = [words[s[-1]]["end"] for s in sents]
        for c in picked:
            near_s = [t for t in starts if abs(t - c["start"]) <= 4]
            near_e = [t for t in ends if abs(t - c["end"]) <= 4]
            if near_s:
                c["start"] = max(0.0, min(near_s, key=lambda t: abs(t - c["start"])) - 0.15)
            if near_e:
                e = min(near_e, key=lambda t: abs(t - c["end"])) + 0.4
                if e - c["start"] >= args.min_len * 0.8:
                    c["end"] = e
    for c in picked:
        idx = [k for k, w in enumerate(words) if w["start"] >= c["start"] - 0.2 and w["end"] <= c["end"]]
        c["first"], c["last"] = (idx[0], idx[-1]) if idx else (None, None)
        if words and idx:
            c["score"] += 0.5 * hook_score([words[k] for k in idx])
        c["score"] = round(c["score"], 2)
    return sorted(picked, key=lambda c: c["start"])


def manual_clips(spec, words):
    clips = []
    for part in spec.split(","):
        a, b = part.split("-")
        s, e = parse_time(a), parse_time(b)
        idx = [k for k, w in enumerate(words) if w["start"] >= s and w["end"] <= e]
        clips.append({"start": s, "end": e, "score": None,
                      "first": idx[0] if idx else None, "last": idx[-1] if idx else None})
    return clips


# ---------------------------------------------------------------- captions
def ass_color(hex_rgb):
    r, g, b = hex_rgb[0:2], hex_rgb[2:4], hex_rgb[4:6]
    return f"&H00{b}{g}{r}".upper()


def ass_escape(t):
    return t.replace("\\", "").replace("{", "(").replace("}", ")")


def write_ass(path, words, clip_start, clip_end, args, title=None):
    hi = ass_color(args.highlight)
    lines = [
        "[Script Info]", "ScriptType: v4.00+", f"PlayResX: {W}", f"PlayResY: {H}",
        "WrapStyle: 0", "", "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, "
        "BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, "
        "BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        f"Style: Cap,{args.font},{args.font_size},&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,"
        f"-1,0,0,0,100,100,0,0,1,7,3,2,60,60,{args.caption_y},1",
        f"Style: Title,{args.font},64,&H00FFFFFF,&H00FFFFFF,&H00000000,&HC0000000,"
        "-1,0,0,0,100,100,0,0,3,18,0,8,80,80,180,1",
        "", "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    if title:
        lines.append(f"Dialogue: 1,{ts(0)},{ts(clip_end - clip_start)},Title,,0,0,0,,"
                     f"{ass_escape(title)}")
    # group words into short chunks (max N words / ~18 chars), then one event per word
    chunks, cur = [], []
    for w in words:
        cur.append(w)
        text = " ".join(x["text"] for x in cur)
        if len(cur) >= args.words_per_caption or len(text) > 18 or re.search(r"[.!?,]$", w["text"]):
            chunks.append(cur)
            cur = []
    if cur:
        chunks.append(cur)
    for ci, chunk in enumerate(chunks):
        chunk_end = chunks[ci + 1][0]["start"] if ci + 1 < len(chunks) else chunk[-1]["end"] + 0.3
        chunk_end = min(chunk_end, chunk[-1]["end"] + 0.6)
        for wi, w in enumerate(chunk):
            s = w["start"] - clip_start
            e = (chunk[wi + 1]["start"] if wi + 1 < len(chunk) else chunk_end) - clip_start
            if e <= 0 or s >= clip_end - clip_start:
                continue
            parts = []
            for k, x in enumerate(chunk):
                t = ass_escape(x["text"].upper() if args.uppercase else x["text"])
                parts.append(f"{{\\c{hi}}}{t}{{\\c&H00FFFFFF&}}" if k == wi else t)
            pop = "{\\fscx108\\fscy108\\t(0,80,\\fscx100\\fscy100)}" if wi == 0 else ""
            lines.append(f"Dialogue: 0,{ts(s)},{ts(e)},Cap,,0,0,0,,{pop}{' '.join(parts)}")
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")


# ----------------------------------------------------------------- render
def render(video, out_path, ass_file, start, end, args):
    if args.layout == "stack":
        # facecam on top, gameplay below (classic streamer clip layout)
        fx, fy, fw, fh = (int(v) for v in args.facecam.split(","))
        top = int(W * fh / fw) // 2 * 2
        bot = H - top
        gw = f"trunc(ih*{W}/{bot}/2)*2"
        vf = (f"split[a][b];[a]crop={fw}:{fh}:{fx}:{fy},scale={W}:{top}[cam];"
              f"[b]crop={gw}:ih:(iw-{gw})*{args.crop_x}:0,scale={W}:{bot}[g];[cam][g]vstack")
    elif args.layout == "crop":
        vf = (f"scale=-2:{H},crop={W}:{H}:(iw-{W})*{args.crop_x}:0")
    elif args.layout == "fit":
        vf = (f"scale={W}:{H}:force_original_aspect_ratio=decrease,"
              f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:black")
    else:  # blur
        vf = (f"split[a][b];[a]scale={W}:{H}:force_original_aspect_ratio=increase,"
              f"crop={W}:{H},gblur=sigma=40,eq=brightness=-0.08[bg];"
              f"[b]scale={W}:-2[fg];[bg][fg]overlay=(W-w)/2:(H-h)/2")
    if ass_file:
        vf += f",ass={ass_file.name}"
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
           "-ss", f"{start:.3f}", "-i", str(Path(video).resolve()), "-t", f"{end - start:.3f}",
           "-filter_complex", vf, "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
           "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart",
           str(out_path.resolve())]
    # run inside the output folder so the subtitle path needs no escaping
    subprocess.run(cmd, check=True, cwd=ass_file.parent if ass_file else None)


# ------------------------------------------------------------------- main
def download(url, workdir, section=None):
    if not shutil.which("yt-dlp"):
        sys.exit("yt-dlp is not installed. Run: pip install yt-dlp  (or download the video yourself)")
    for old in workdir.glob("source.*"):
        old.unlink()
    out = workdir / "source.%(ext)s"
    cmd = ["yt-dlp", "-f", "bv*[height<=1080]+ba/b[height<=1080]/b",
           "--merge-output-format", "mp4", "-o", str(out)]
    if section:  # only download part of a long stream, e.g. "1:00:00-1:45:00"
        cmd += ["--download-sections", f"*{section}", "--force-keyframes-at-cuts"]
    subprocess.run(cmd + [url], check=True)
    return next(workdir.glob("source.*"))


def main():
    ap = argparse.ArgumentParser(description="Turn a long video into short vertical captioned clips.")
    ap.add_argument("video", nargs="?", help="input video file")
    ap.add_argument("--url", help="download the video with yt-dlp instead (only if you have rights)")
    ap.add_argument("-o", "--out", default="clips", help="output folder (default: clips)")
    ap.add_argument("--section", help='with --url: download only this part, e.g. "1:00:00-1:45:00"')
    ap.add_argument("-n", "--count", type=int, default=5, help="number of clips (default 5)")
    ap.add_argument("--mode", choices=["talk", "hype"], default="talk",
                    help="talk = podcasts/interviews (by what is said); "
                         "hype = gaming/streams (by loud reactions & intensity)")
    ap.add_argument("--times", help='pick clips yourself, e.g. "1:20-1:55,12:03-12:40"')
    ap.add_argument("--min-len", type=float, default=None, help="default 15 (talk) / 12 (hype)")
    ap.add_argument("--max-len", type=float, default=None, help="default 60 (talk) / 45 (hype)")
    ap.add_argument("--target-len", type=float, default=None, help="default 35 (talk) / 25 (hype)")
    ap.add_argument("--transcript", help="use an existing .srt/.vtt instead of Whisper")
    ap.add_argument("--no-transcript", action="store_true",
                    help="skip speech-to-text (hype mode only; fast, but no captions)")
    ap.add_argument("--model", default="small", help="Whisper model: tiny/base/small/medium/large-v3")
    ap.add_argument("--language", default=None, help="force language, e.g. en")
    ap.add_argument("--retranscribe", action="store_true", help="ignore cached transcript")
    ap.add_argument("--layout", choices=["blur", "crop", "fit", "stack"], default="blur",
                    help="blur = full frame on blurred background (default), crop = fill screen, "
                         "stack = facecam on top + gameplay below (needs --facecam)")
    ap.add_argument("--facecam", help='facecam box in the source video as "x,y,w,h" pixels, e.g. "15,430,425,266"')
    ap.add_argument("--crop-x", type=float, default=0.5, help="crop position 0=left 0.5=center 1=right")
    ap.add_argument("--no-captions", action="store_true")
    ap.add_argument("--title", action="store_true", help="show the clip's hook as a title bar on top")
    ap.add_argument("--titles", help='your own title per clip, separated by |, e.g. "TITLE ONE|TITLE TWO"')
    ap.add_argument("--font", default="Arial")
    ap.add_argument("--font-size", type=int, default=86)
    ap.add_argument("--caption-y", type=int, default=520, help="caption distance from bottom (px)")
    ap.add_argument("--highlight", default="FFE400", help="active-word color (hex RGB)")
    ap.add_argument("--words-per-caption", type=int, default=3)
    ap.add_argument("--no-uppercase", dest="uppercase", action="store_false")
    ap.add_argument("--dry-run", action="store_true", help="only list picked moments, don't render")
    args = ap.parse_args()
    hype = args.mode == "hype"
    for name, talk_v, hype_v in (("min_len", 15, 12), ("max_len", 60, 45), ("target_len", 35, 25)):
        if getattr(args, name) is None:
            setattr(args, name, hype_v if hype else talk_v)

    if args.layout == "stack" and not args.facecam:
        ap.error('--layout stack needs --facecam "x,y,w,h"')
    if not shutil.which("ffmpeg"):
        sys.exit("ffmpeg is required. Install it: https://ffmpeg.org/download.html")
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    work = out / ".work"
    work.mkdir(exist_ok=True)

    if args.url:
        video = download(args.url, work, args.section)
    elif args.video:
        video = Path(args.video)
    else:
        ap.error("give a video file or --url")
    if not video.exists():
        sys.exit(f"File not found: {video}")

    length = duration_of(video)
    print(f"Video: {video} ({ts(length)})")
    words = [] if (args.no_transcript and hype) else get_transcript(args, video, work)
    if not words and not args.times and not hype:
        sys.exit("No speech found in transcript. Use --times, or --mode hype for gaming streams.")
    print(f"Transcript: {len(words)} words")

    if args.times:
        clips = manual_clips(args.times, words)
    elif hype:
        print("Finding hype moments...")
        clips = hype_highlights(loudness_per_second(video, length), words, args)
    else:
        print("Scoring moments...")
        clips = find_highlights(words, loudness_per_second(video, length), args)
        if not clips:
            sys.exit("No windows fit the length limits; try --min-len 10 or --max-len 90.")

    results = []
    for n, c in enumerate(clips, 1):
        cw = words[c["first"]:c["last"] + 1] if c["first"] is not None else []
        text = " ".join(w["text"] for w in cw)
        first_sentence = re.split(r"(?<=[.!?])\s", text, maxsplit=1)[0][:90]
        content = [norm(w["text"]) for w in cw if norm(w["text"]) not in STOPWORDS and len(norm(w["text"])) > 3]
        tags = []
        for w in sorted(set(content), key=lambda x: -content.count(x)):
            tags.append("#" + w.replace("'", ""))
            if len(tags) == 4:
                break
        name = f"clip_{n:02d}.mp4"
        print(f"[{n}/{len(clips)}] {ts(c['start'])} -> {ts(c['end'])}  score={c['score']}  {first_sentence[:60]!r}")
        if not args.dry_run:
            ass = None
            if not args.no_captions and cw:
                ass = out / f"clip_{n:02d}.ass"
                custom = args.titles.split("|") if args.titles else []
                title = (custom[n - 1].strip() if n <= len(custom) else
                         first_sentence if args.title else None)
                write_ass(ass, cw, c["start"], c["end"], args, title)
            render(video, out / name, ass, c["start"], c["end"], args)
        results.append({"file": name, "start": round(c["start"], 2), "end": round(c["end"], 2),
                        "length": round(c["end"] - c["start"], 1), "score": c["score"],
                        "hook": first_sentence, "hashtags": tags + ["#fyp", "#shorts"],
                        "transcript": text})

    (out / "clips.json").write_text(json.dumps(results, indent=2))
    md = ["# Clips", ""]
    for r in results:
        md += [f"## {r['file']}  ({ts(r['start'])} - {ts(r['end'])}, {r['length']}s)",
               f"**Hook / caption idea:** {r['hook']}", "",
               f"**Hashtags:** {' '.join(r['hashtags'])}", "",
               f"> {r['transcript']}", ""]
    (out / "clips.md").write_text("\n".join(md))
    print(f"\nDone. {'Planned' if args.dry_run else 'Rendered'} {len(results)} clips in {out.resolve()}")
    print(f"Captions & hashtags: {out / 'clips.md'}")


if __name__ == "__main__":
    main()
