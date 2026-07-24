#!/usr/bin/env python3
"""Pull transcripts for all 14 videos of Trades By Sci's course."""
import os, json, time
from youtube_transcript_api import YouTubeTranscriptApi, TranscriptsDisabled, NoTranscriptFound, VideoUnavailable

VIDEOS = [
    ("Day1_Trends",            "DYCAqd8xorM"),
    ("Day2_Indication",        "IGIxQD8PBMo"),
    ("Day3_LiquidityCorrections", "lTZCJYMQB9Q"),
    ("Day4_Entries",           "mUNI_MgY1g8"),
    ("Day5_UnderstandEntries", "g7xP6frMv0w"),
    ("Day6_TimeframeCorrelation","z38sGgvY9XY"),
    ("Day7_MarkUpCharts",      "dnY6INL7kXA"),
    ("Day8_TradingSimple",     "Vnwa2LaVerw"),
    ("Day9_IdentifyReversals", "kTeVIscVr2Q"),
    ("Day10_HowToMarkUp",      "qA0IgH6rohg"),
    ("Day11_MarketStructureEntries","KqVnX1Rn77M"),
    ("Day12_DecisionPsychology","t79RzQuzYfo"),
    ("Day13_PositioningPsychology","uR_F79sJXlk"),
    ("Day14_MarketStructure",  "Y7Q37vTbuNg"),
]

OUT_DIR = "/home/user/trading_bot/transcripts"
os.makedirs(OUT_DIR, exist_ok=True)

yt = YouTubeTranscriptApi()
results = {}

for name, vid in VIDEOS:
    print(f"\n=== {name} ({vid}) ===")
    transcript = None
    # Try to get a manually created English transcript first, fall back to auto
    try:
        transcript_list = yt.list(vid)
        chosen = None
        # prefer manually created en
        try:
            chosen = transcript_list.find_manually_created_transcript(['en'])
        except Exception:
            pass
        if chosen is None:
            try:
                chosen = transcript_list.find_generated_transcript(['en'])
            except Exception as e:
                print("  no generated en transcript:", e)
        if chosen is not None:
            data = chosen.fetch()
            # data is a list of FetchedTranscriptSnippet (has .text and .start)
            lines = [f"[{round(s.start,1)}s] {s.text}" for s in data]
            full = "\n".join(lines)
            plain = " ".join(s.text for s in data)
            with open(os.path.join(OUT_DIR, f"{name}_{vid}_timestamped.txt"), "w") as f:
                f.write(full)
            with open(os.path.join(OUT_DIR, f"{name}_{vid}_plain.txt"), "w") as f:
                f.write(plain)
            print(f"  OK: {len(lines)} snippets, {len(plain)} chars")
            results[name] = {"vid": vid, "snippets": len(lines), "chars": len(plain)}
        else:
            print("  NO transcript found in any language")
            results[name] = {"vid": vid, "error": "no transcript"}
    except TranscriptsDisabled:
        print("  transcripts disabled for this video")
        results[name] = {"vid": vid, "error": "disabled"}
    except VideoUnavailable:
        print("  video unavailable")
        results[name] = {"vid": vid, "error": "unavailable"}
    except Exception as e:
        print(f"  ERROR: {type(e).__name__}: {e}")
        results[name] = {"vid": vid, "error": str(e)}
    time.sleep(1)

with open(os.path.join(OUT_DIR, "_summary.json"), "w") as f:
    json.dump(results, f, indent=2)

print("\n\n===== SUMMARY =====")
ok = sum(1 for v in results.values() if "error" not in v)
print(f"{ok}/{len(VIDEOS)} transcripts retrieved")
for k, v in results.items():
    print(f"  {k}: {v}")
