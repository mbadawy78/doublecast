import json, sys, tempfile, pathlib, collections
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "src"))
from doublecast.config import Config, Term
from doublecast.engine import Engine
corpus = [json.loads(l) for l in open(pathlib.Path(__file__).with_name("corpus.jsonl"), encoding="utf-8")]
# what discovery would read from a master-data export: the people and companies in the CSV documents
terms = {}
for d in corpus:
    if d["kind"] == "csv":
        for s in d["sensitive"]:
            if s["category"] in ("PERSON", "ORG"):
                terms.setdefault(s["text"], s["category"])
test = [d for d in corpus if d["kind"] != "csv"]
e = Engine(Config(workspace="eval", home=pathlib.Path(tempfile.mkdtemp()), ner_enabled="off",
                  languages=["el","en","de","fr","it","es"], terms=[Term(c, v) for v, c in terms.items()]))
leak = collections.Counter(); tot = collections.Counter(); known_leak = known_tot = 0
known = {v.casefold() for v in terms}
for d in test:
    out = e.scramble(d["text"]).text
    for s in d["sensitive"]:
        if s["category"] == "MONEY": continue
        tot[s["category"]] += 1
        k = s["text"].casefold() in known
        known_tot += k
        if s["text"] in out:
            leak[s["category"]] += 1; known_leak += k
print(f"with {len(terms)} names from a master-data export, on the {len(test)} non-CSV documents:")
print(f"  names that are in the export: leaked {known_leak}/{known_tot}")
print(f"  everything (but money): leaked {sum(leak.values())}/{sum(tot.values())} ({sum(leak.values())/sum(tot.values()):.1%})")
