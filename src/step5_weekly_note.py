"""
STEP 5 - The AI writes the weekly note, and TWO checks look for hallucinations.

What goes to Groq: ~13 numbered facts (totals and shares only).
What never goes to Groq: subscriber IDs, names, phone numbers, raw rows.

Check 1 - number check (code, free, instant):
  every sentence must cite real facts, and every number must be in those facts.
Check 2 - AI judge (a second, different model):
  reads each sentence next to its facts and says faithful / distorted / unsupported.
  This catches changed MEANING, which check 1 cannot see.

Evaluations:
  A. The real note: unsupported-claim rate after both checks (target < 2%).
  B. Trap test: 5 planted bad sentences. Which check catches which?

Run:  .venv/bin/python src/step5_weekly_note.py
"""
import json
import sys

sys.path.insert(0, "api")
from _note_engine import judge_note, load_key, make_traps, run_pipeline, verify_note   # noqa: E402

d = json.load(open("public/data/dashboard.json"))
key = load_key()
print("Calling Groq (writer, then judge)..." if key else "No GROQ_API_KEY in .env -> demo mode")
note, facts = run_pipeline(d, key)
v = note["verification"]

print("\n" + "=" * 70 + "\n" + note["headline"] + "\n" + "=" * 70)
for p in note["paragraphs"]:
    print("\n" + p)
print("\nActions this week:")
for a in note.get("actions", []):
    print(" - " + a)

m = note["meta"]
print(f"\nWriter: {m['model']} | {m['seconds']}s | {m['input_tokens']}+{m['output_tokens']} tokens | ${m['cost_usd']}")
if "judge_meta" in v:
    j = v["judge_meta"]
    print(f"Judge:  {j['model']} | {j['seconds']}s | {j['input_tokens']}+{j['output_tokens']} tokens | ${j['cost_usd']}")
for a in note.get("attempts", []):
    print(f"Attempt {a['attempt']}: {a['flagged']} sentence(s) flagged" + ("" if a["flagged"] else " -> accepted"))
    for pr in a["problems"]:
        print(f"    {pr[:140]}")
print(f"Total cost of this note (all attempts): ${m['total_cost_usd']}")

print("\nEvaluation A - real note, sentence by sentence:")
for s in v["sentences"]:
    judge = s.get("judge", {}).get("verdict", "-")
    print(f"  numbers {'OK ' if s['ok'] else 'BAD'} | judge {judge:11s} | {s['sentence'][:70]}...")
    if s.get("judge") and judge != "faithful":
        print(f"        why: {s['judge']['why']}")
rate = v.get("unsupported_rate_final", v["unsupported_rate"])
print(f"  -> {rate:.1%} unsupported after both checks (target < 2%)  {'PASS' if rate < 0.02 else 'MISS'}")

if key:
    t = judge_note(verify_note(make_traps(facts), facts), facts, key)
    print("\nEvaluation B - trap test (5 planted bad sentences):")
    for s in t["sentences"]:
        print(f"  numbers {'caught' if not s['ok'] else 'missed'} | judge "
              f"{'caught' if s['judge']['verdict'] != 'faithful' else 'missed'} ({s['judge']['verdict']}) | {s['sentence'][:55]}")
    caught = sum(not s["ok_final"] for s in t["sentences"])
    by_numbers = sum(not s["ok"] for s in t["sentences"])
    print(f"  -> number check alone caught {by_numbers}/5, both checks together caught {caught}/5")
    note["trap_test"] = {"planted": 5, "caught_numbers_only": by_numbers, "caught_both": caught,
                         "details": [{"sentence": s["sentence"], "numbers_caught": not s["ok"],
                                      "judge": s["judge"]["verdict"], "why": s["judge"]["why"]} for s in t["sentences"]]}

json.dump(note, open("public/data/weekly_note.json", "w"), indent=1)
json.dump({"facts": facts}, open("public/data/facts.json", "w"), indent=1)
print("\nSaved public/data/weekly_note.json and public/data/facts.json")
