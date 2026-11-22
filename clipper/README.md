# Clipper

Turns a long video (podcast, stream, interview) into short **vertical 9:16 clips with
word-by-word captions**, ready for TikTok, Reels and YouTube Shorts.

It transcribes the video, scores every 15–60 second moment (hook words, questions,
numbers, loudness/energy, speaking pace, complete sentences), picks the best ones,
and renders them. It also writes `clips.md` with a hook line and hashtags for each clip.

> Only clip videos you have the rights to: your own, a paid clipping campaign that
> allows it, or a creator who hired you.

## Install (once)

1. **Python 3.9+** – https://www.python.org/downloads/
2. **ffmpeg** – Mac: `brew install ffmpeg` · Windows: `winget install ffmpeg` · Linux: `sudo apt install ffmpeg`
3. Python packages:
   ```bash
   pip install -r clipper/requirements.txt
   ```

## Use

```bash
# 5 best clips from a video file
python3 clipper/clipper.py podcast.mp4

# 8 clips, with the hook shown as a title bar at the top
python3 clipper/clipper.py podcast.mp4 -n 8 --title

# fill the whole screen (crop) instead of blurred background; shift crop left
python3 clipper/clipper.py stream.mp4 --layout crop --crop-x 0.3

# GAMING / STREAMS: pick by hype (screams, big reactions) instead of by words
python3 clipper/clipper.py --url "https://youtu.be/VIDEO_ID" --mode hype -n 6 --title
# long stream? download only part of it first (much faster)
python3 clipper/clipper.py --url "https://youtu.be/VIDEO_ID" --section "0:30:00-1:30:00" --mode hype -n 6
# hype mode without speech-to-text (fastest, no captions)
python3 clipper/clipper.py stream.mp4 --mode hype --no-transcript -n 6

# choose the moments yourself
python3 clipper/clipper.py podcast.mp4 --times "1:20-1:55,12:03-12:40"

# just preview which moments it would pick (fast, no rendering)
python3 clipper/clipper.py podcast.mp4 --dry-run

# download from a link a campaign gave you (needs yt-dlp)
python3 clipper/clipper.py --url "https://..." -n 6
```

Output goes to `clips/`: `clip_01.mp4`, `clip_02.mp4`, … plus `clips.md`
(hook + hashtags + transcript per clip) and `clips.json`.

The first run downloads the Whisper speech model. The transcript is cached in
`clips/.work/`, so re-running with different settings is fast.

## Useful options

| Option | What it does |
|---|---|
| `-n 8` | number of clips |
| `--mode talk\|hype` | talk = podcasts (by what is said), hype = gaming/streams (by loud reactions) |
| `--section "1:00:00-1:45:00"` | with `--url`, download only that part of a long stream |
| `--min-len / --max-len / --target-len` | clip length in seconds (default 15 / 60 / 35) |
| `--layout blur\|crop\|fit\|stack` | blurred background (default), fill screen, black bars, or facecam-on-top split screen |
| `--facecam "x,y,w,h"` | for `stack`: where the facecam is in the source video (pixels), e.g. `"15,430,425,266"` |
| `--title` | hook text bar at the top of the clip |
| `--titles "ONE|TWO|..."` | your own title for each clip, in order |
| `--model tiny\|base\|small\|medium\|large-v3` | Whisper accuracy vs speed (default `small`) |
| `--language en` | force language |
| `--transcript file.srt` | use existing subtitles (.srt/.vtt) instead of Whisper |
| `--highlight 00FF88` | colour of the current word |
| `--font "Montserrat Black" --font-size 90` | caption style |
| `--no-uppercase`, `--no-captions` | caption tweaks |

## Tips for earning from clips
- The first 1–2 seconds decide everything – check the clip starts on the hook; use `--times` to trim if not.
- Post several clips per day per account; most flop, a few carry.
- Track views per clip per campaign so you know what pays.
