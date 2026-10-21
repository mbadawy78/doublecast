import json, sys, collections
from presidio_analyzer import AnalyzerEngine
from presidio_analyzer.nlp_engine import NlpEngineProvider
from presidio_anonymizer import AnonymizerEngine

corpus = [json.loads(l) for l in open(sys.argv[1], encoding="utf-8")]
provider = NlpEngineProvider(nlp_configuration={"nlp_engine_name": "spacy", "models": [
    {"lang_code": "en", "model_name": "en_core_web_lg"}, {"lang_code": "el", "model_name": "el_core_news_lg"}]})
analyzer = AnalyzerEngine(nlp_engine=provider.create_engine(), supported_languages=["en", "el"])
anon = AnonymizerEngine()
leak = collections.Counter(); tot = collections.Counter(); lang_leak = collections.Counter(); lang_tot = collections.Counter()
keep_lost = keep_tot = 0
for d in corpus:
    lang = "el" if d["lang"] == "el" else "en"  # Presidio ships no de/fr/it/es setup by default
    res = analyzer.analyze(text=d["text"], language=lang)
    out = anon.anonymize(text=d["text"], analyzer_results=res).text
    for s in d["sensitive"]:
        tot[s["category"]] += 1; lang_tot[d["lang"]] += 1
        if s["text"] in out:
            leak[s["category"]] += 1; lang_leak[d["lang"]] += 1
    lost = [k for k in d.get("keep", []) if k not in out]
    keep_tot += len(d.get("keep", [])); keep_lost += len(lost)
print(f"Presidio (spaCy en_core_web_lg + el_core_news_lg, default recognisers): docs {len(corpus)}")
for c in sorted(tot):
    print(f"  {c:13s} leaked {leak[c]:4d} / {tot[c]:4d}  ({leak[c]/tot[c]:.1%})")
nm = sum(tot[c] for c in tot if c != "MONEY"); nl = sum(leak[c] for c in tot if c != "MONEY")
print(f"  ALL but MONEY leaked {nl}/{nm} ({nl/nm:.1%})")
for l in sorted(lang_tot):
    print(f"  lang {l:6s} {lang_leak[l]}/{lang_tot[l]} ({lang_leak[l]/lang_tot[l]:.1%})")
print(f"  over-protection: {keep_lost}/{keep_tot} ordinary phrases changed ({keep_lost/max(keep_tot,1):.1%})")
