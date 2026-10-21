import collections, json, pathlib, sys, tempfile
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "src"))
from doublecast.config import Config
from doublecast.engine import Engine

corpus = [json.loads(l) for l in open(sys.argv[1], encoding="utf-8")]
mode = sys.argv[2] if len(sys.argv) > 2 else "shared"  # shared engine (learning) or fresh per doc
out_path = sys.argv[3] if len(sys.argv) > 3 else None

def engine():
    return Engine(Config(workspace="eval", home=pathlib.Path(tempfile.mkdtemp()), ner_enabled="off",
                         languages=["el", "en", "de", "fr", "it", "es"]))

e = engine()
leak = collections.Counter(); tot = collections.Counter(); lang_leak = collections.Counter(); lang_tot = collections.Counter()
keep_lost = keep_tot = rt_ok = 0
rows = []
for d in corpus:
    if mode == "fresh":
        e = engine()
    out = e.scramble(d["text"]).text
    rt = e.restore(out) == d["text"]
    rt_ok += rt
    leaked = []
    for s in d["sensitive"]:
        tot[s["category"]] += 1; lang_tot[d["lang"]] += 1
        if s["text"] in out:
            leak[s["category"]] += 1; lang_leak[d["lang"]] += 1; leaked.append(s)
    lost = [k for k in d.get("keep", []) if k not in out]
    keep_tot += len(d.get("keep", [])); keep_lost += len(lost)
    rows.append({"id": d["id"], "leaked": leaked, "lost_keep": lost, "roundtrip": rt})
print(f"Doublecast ({mode}): docs {len(corpus)}  round-trip {rt_ok}/{len(corpus)}")
for c in sorted(tot):
    print(f"  {c:13s} leaked {leak[c]:4d} / {tot[c]:4d}  ({leak[c]/tot[c]:.1%})")
nm = sum(tot[c] for c in tot if c != "MONEY"); nl = sum(leak[c] for c in tot if c != "MONEY")
print(f"  ALL but MONEY leaked {nl}/{nm} ({nl/nm:.1%});  all {sum(leak.values())}/{sum(tot.values())}")
for l in sorted(lang_tot):
    print(f"  lang {l:6s} {lang_leak[l]}/{lang_tot[l]} ({lang_leak[l]/lang_tot[l]:.1%})")
print(f"  over-protection: {keep_lost}/{keep_tot} ordinary phrases changed ({keep_lost/max(keep_tot,1):.1%})")
if out_path:
    json.dump(rows, open(out_path, "w"), ensure_ascii=False, indent=1)
