"""Повтор сценариев из отчёта тестировщика (CSV из виджета/QA-инструмента) против бота.
    python qa/replay_report.py report.json [--base URL] [--pause СЕК] [--verdicts fail,partial]
report.json — список строк отчёта (id, turn, user_message, verdict, review_note)."""
import argparse, json, time, collections
from datetime import datetime
from pathlib import Path
import httpx

ap = argparse.ArgumentParser()
ap.add_argument("report"); ap.add_argument("--base", default="https://backend-fawn-nine-72.vercel.app")
ap.add_argument("--pause", type=float, default=6); ap.add_argument("--verdicts", default="fail,partial")
a = ap.parse_args()
rows = json.load(open(a.report, encoding="utf-8"))
cases = collections.OrderedDict()
for r in rows:
    cases.setdefault(r["id"], []).append(r)
want = set(a.verdicts.split(","))
out = []
with httpx.Client() as c:
    for qid, steps in cases.items():
        if not any(s["verdict"] in want for s in steps):
            continue
        hist, state, sid, res = [], None, None, []
        for s in sorted(steps, key=lambda x: int(x["turn"])):
            r = c.post(f"{a.base}/api/chat", json={"session_id": sid, "message": s["user_message"], "history": hist,
                                                   "state": state}, timeout=90).json()
            sid, state = r["session_id"], r.get("state")
            hist += [{"role": "user", "content": s["user_message"]}, {"role": "assistant", "content": r["reply"]}]
            res.append({"user": s["user_message"], "reply": r["reply"], "intent": r.get("intent"),
                        "was": s["verdict"], "note": s["review_note"]})
            time.sleep(a.pause)
        out.append({"id": qid, "steps": res})
        print(qid, "|", res[-1]["user"][:50], "|", res[-1]["intent"], "|", res[-1]["reply"][:170].replace("\n", " "), flush=True)
p = Path(__file__).parent / "results" / f"{datetime.now():%Y%m%d_%H%M}_replay_report.json"
p.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
print("saved", p)
