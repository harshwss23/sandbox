#!/usr/bin/env python3
"""The grade as a page you can read: every criterion, its verdict, and why.

The judge answered one question per criterion and said why in its own words.
This lays those answers out to be checked -- the reasoning is what says whether
the judge read a criterion the way it was meant, and a criterion it read
differently is a criterion to reword rather than a result about the model.

The file is self-contained: one HTML document with its own styling, no fonts,
scripts or images loaded from anywhere. Download it out of the sandbox and open
it in your own browser, offline, and it looks the same.

    python3 bin/view_grade.py               # the last graded run
    python3 bin/view_grade.py --job PATH    # a specific one
"""

from __future__ import annotations

import argparse
import html
import json
import sys
from datetime import datetime
from pathlib import Path

BIN_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BIN_DIR))

import flc_state as st  # noqa: E402
import grade_report as gr  # noqa: E402
import view_run as vr  # noqa: E402

# Why a criterion went ungraded, in the contributor's terms. The key is what
# judge.py records; anything else it may record later falls back to the text
# below, so an unknown reason is still shown as ungraded rather than dropped.
UNMEASURED = {
    "judge_refused": ("the judge declined to read this one",
                      "Its safety filter refused the wording rather than "
                      "judging your task. Grading again is worth one try -- the "
                      "filter is not consistent. If it declines again, say the "
                      "same thing in plainer words."),
    "judge_no_score": ("the judge never gave a verdict",
                       "It replied, but never in the yes-or-no form the "
                       "criterion asks for, through every retry. Grading again "
                       "is worth one attempt; if it comes back the same, the "
                       "criterion is most likely not a yes-or-no question "
                       "about the answer. Delivery refuses until it is fixed."),
}
UNMEASURED_OTHER = ("this criterion was not graded",
                    "The judge returned nothing usable for it.")


def esc(value) -> str:
    return html.escape(str(value), quote=True)


# --- reading the results ------------------------------------------------------


def read_json(path: Path, default):
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return default


def unit_weight(test: dict) -> int:
    """What one test is worth. A row with no weight is worth the default.

    A run graded before the weights existed records none, and reading that as
    nothing would turn the whole suite into zero points.
    """
    value = test.get("weight")
    return value if isinstance(value, int) and not isinstance(value, bool) \
        else st.DEFAULT_TEST_WEIGHT


def unit_points(tests: list) -> int:
    return sum(unit_weight(t) for t in tests if str(t.get("status")) == "passed")


def unit_available(tests: list) -> int:
    return sum(unit_weight(t) for t in tests)


def unit_tests(logs: Path) -> tuple[str, list[dict]]:
    """The suite's own account of itself: its status and every check in it.

    `unit_test_results.json` is what test.sh scores from, so it is read first.
    A results file from a run that did not keep it still has the checks in
    `ctrf.json`, where they sit after the rubrics -- told apart by name, since
    a rubric's name there is its criterion text.
    """
    units = read_json(logs / "unit_test_results.json", None)
    if isinstance(units, dict):
        tests = [t for t in units.get("tests") or [] if isinstance(t, dict)]
        return str(units.get("status") or "skipped"), tests

    ctrf = read_json(logs / "ctrf.json", None)
    rows = (((ctrf or {}).get("results") or {}).get("tests")
            if isinstance(ctrf, dict) else None)
    if not isinstance(rows, list):
        return "skipped", []
    titles = {str(e.get("title", "")).strip()
              for e in gr.load(logs)[0] if isinstance(e, dict)}
    tests = [t for t in rows if isinstance(t, dict)
             and str(t.get("name", "")).strip() not in titles
             and str(t.get("name", "")) != "rubrics"]
    return ("ran" if tests else "skipped"), tests


def points(results: list) -> tuple[int, int, int]:
    """What the rubric put up, what was earned, and what negatives cost.

    Same arithmetic as judge._aggregate and grade_report.report, over the
    criteria that were actually scored.
    """
    scored = [e for e in results if gr.verdict(e)[0] in ("PASS", "FAIL")]
    passed = [e for e in scored if gr.verdict(e)[0] == "PASS"]
    failed = [e for e in scored if gr.verdict(e)[0] == "FAIL"]
    available = sum(int(e.get("weight", 5)) for e in scored
                    if int(e.get("weight", 5)) > 0)
    earned = sum(int(e.get("weight", 5)) for e in passed
                 if int(e.get("weight", 5)) > 0)
    lost = sum(abs(int(e.get("weight", 5))) for e in failed
               if int(e.get("weight", 5)) < 0)
    return available, earned, lost


# --- the page -----------------------------------------------------------------


STYLE = """
:root { color-scheme: light dark; }
* { box-sizing: border-box; }
body {
  margin: 0 auto; padding: 2rem 1.25rem 6rem; max-width: 60rem;
  font: 16px/1.6 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto,
        Helvetica, Arial, sans-serif;
  color: #1b1b1f; background: #fbfbfd;
}
h1 { font-size: 1.6rem; margin: 0 0 .25rem; }
h2 { font-size: 1.05rem; margin: 2rem 0 .75rem; letter-spacing: .01em; }
.meta { color: #6b6b76; margin: 0 0 1.5rem; font-size: .875rem; }
.note {
  border-left: 3px solid #c7c7d1; padding: .5rem 0 .5rem .9rem; margin: 0 0 2rem;
  color: #45454f; font-size: .925rem;
}
.score {
  border: 1px solid #d9d9e3; border-radius: 10px; padding: 1.1rem 1.25rem;
  background: #fff; margin: 0 0 1.5rem;
}
.score .big { font-size: 2.4rem; font-weight: 600; line-height: 1.1; }
.score .of { color: #6b6b76; font-size: .9rem; margin: .35rem 0 0; }
.parts { display: flex; flex-wrap: wrap; gap: 1.5rem; margin: 1rem 0 0; }
.part { font-size: .9rem; }
.part .label {
  display: block; color: #6b6b76; font-size: .75rem; text-transform: uppercase;
  letter-spacing: .06em;
}
.alarm {
  border: 1px solid #e6c9c9; border-left-width: 3px; border-radius: 10px;
  background: #fdf6f6; padding: .9rem 1.1rem; margin: 0 0 1.5rem;
  font-size: .925rem; color: #6d2f2f;
}
.alarm h2 { margin: 0 0 .4rem; font-size: .95rem; }
.alarm p { margin: .4rem 0 0; }
.controls { display: flex; gap: .6rem; margin: 0 0 1rem; }
.controls input {
  flex: 1; padding: .5rem .7rem; border: 1px solid #d9d9e3; border-radius: 8px;
  font: inherit; font-size: .925rem; background: #fff; color: inherit;
}
.controls button {
  padding: .5rem .9rem; border: 1px solid #d9d9e3; border-radius: 8px;
  background: #fff; font: inherit; font-size: .875rem; cursor: pointer;
  color: inherit;
}
ol.crits { list-style: none; margin: 0; padding: 0; }
li.crit {
  border: 1px solid #e4e4ec; border-radius: 10px; background: #fff;
  padding: .9rem 1.1rem; margin: 0 0 .75rem;
}
li.crit[data-verdict="fail"] { background: #fdfafa; }
li.crit[data-verdict="ungraded"] { background: #faf9f6; }
.who { display: flex; align-items: baseline; gap: .6rem; margin-bottom: .5rem; }
.badge {
  font-size: .72rem; text-transform: uppercase; letter-spacing: .06em;
  padding: .15rem .5rem; border-radius: 999px; border: 1px solid transparent;
}
.badge.pass { background: #eef6ec; color: #2c5a2c; border-color: #cfe6cd; }
.badge.fail { background: #fbeceb; color: #8a2f28; border-color: #f0cfcc; }
.badge.ungraded { background: #f6f1e6; color: #6d5626; border-color: #e8dcc2; }
.n { color: #9a9aa6; font-size: .78rem; }
.section { color: #6b6b76; font-size: .78rem; }
.text { margin: 0 0 .6rem; }
.trap { color: #6b6b76; font-size: .8rem; }
.why {
  border-left: 3px solid #dcdce4; padding: .1rem 0 .1rem .85rem; margin: .6rem 0 0;
}
.why .label {
  display: block; color: #6b6b76; font-size: .75rem; text-transform: uppercase;
  letter-spacing: .06em; margin-bottom: .25rem;
}
.why p { margin: 0; font-size: .95rem; }
.remedy { margin: .6rem 0 0; font-size: .9rem; color: #45454f; }
pre {
  white-space: pre-wrap; overflow-wrap: anywhere; margin: 0;
  font: 13.5px/1.55 ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
}
table.units { border-collapse: collapse; width: 100%; font-size: .925rem; }
table.units th, table.units td {
  text-align: left; padding: .5rem .6rem; border-bottom: 1px solid #e4e4ec;
  vertical-align: top;
}
table.units th { font-size: .75rem; text-transform: uppercase; color: #6b6b76;
  letter-spacing: .06em; }
table.units code { word-break: break-all; }
footer {
  margin-top: 3rem; padding-top: 1.25rem; border-top: 1px solid #e4e4ec;
  color: #6b6b76; font-size: .875rem;
}
footer code { word-break: break-all; }
@media (prefers-color-scheme: dark) {
  body { color: #e6e6ea; background: #16161a; }
  .score, li.crit, .controls input, .controls button { background: #1e1e24; }
  .score, li.crit { border-color: #2e2e38; }
  li.crit[data-verdict="fail"] { background: #211c1c; }
  li.crit[data-verdict="ungraded"] { background: #201e19; }
  .controls input, .controls button { border-color: #2e2e38; }
  .note { border-left-color: #3a3a46; color: #b8b8c2; }
  .why { border-left-color: #2e2e38; }
  .alarm { background: #241a1a; border-color: #4a2f2f; color: #e6b8b8; }
  table.units th, table.units td { border-bottom-color: #2e2e38; }
  footer { border-top-color: #2e2e38; }
}
"""

# Progressive enhancement only: the controls are hidden until this runs, so a
# browser that will not run it shows a page with no dead buttons on it. Nothing
# here is required to read anything.
SCRIPT = """
(function () {
  var bar = document.getElementById('controls');
  var box = document.getElementById('find');
  var all = document.getElementById('only');
  var crits = Array.prototype.slice.call(document.querySelectorAll('li.crit'));
  if (!bar || !box || !all) { return; }
  bar.hidden = false;
  function apply() {
    var needle = box.value.toLowerCase();
    var failing = all.getAttribute('data-on') === 'yes';
    crits.forEach(function (crit) {
      var text = !needle || crit.textContent.toLowerCase().indexOf(needle) >= 0;
      var kind = !failing || crit.getAttribute('data-verdict') !== 'pass';
      crit.style.display = (text && kind) ? '' : 'none';
    });
  }
  box.addEventListener('input', apply);
  all.addEventListener('click', function () {
    var on = all.getAttribute('data-on') !== 'yes';
    all.setAttribute('data-on', on ? 'yes' : 'no');
    all.textContent = on ? 'show every criterion' : 'hide the ones it passed';
    apply();
  });
})();
"""


def render_criterion(entry: dict) -> str:
    mark, why = gr.verdict(entry)
    weight = int(entry.get("weight", 5))
    kind = {"PASS": "pass", "FAIL": "fail"}.get(mark, "ungraded")
    parts = [f'<li class="crit" data-verdict="{kind}">',
             f'<div class="who"><span class="badge {kind}">{esc(mark)}</span>',
             f'<span class="n">[{weight:+d}]</span>',
             f'<span class="section">{esc(gr.kind(entry))}</span>']
    if weight < 0:
        parts.append('<span class="trap">a mistake the answer was meant to '
                     'avoid</span>')
    parts.append("</div>")
    parts.append(f'<p class="text">{esc(entry.get("title") or "(untitled)")}</p>')

    if kind == "ungraded":
        label, remedy = UNMEASURED.get(str(entry.get("unmeasured") or ""),
                                       UNMEASURED_OTHER)
        parts.append(f'<p class="remedy"><strong>{esc(label)}.</strong> '
                     f'{esc(remedy)}</p>')
        reason = entry.get("unmeasured_reason") or why
        if reason:
            parts.append('<div class="why"><span class="label">what it said'
                         f'</span><p>{esc(reason)}</p></div>')
    elif why:
        # The reasoning is the thing being checked, so it is never behind a
        # click.
        parts.append('<div class="why"><span class="label">the judge\'s '
                     f'reasoning</span><p>{esc(why)}</p></div>')
    else:
        parts.append('<div class="why"><span class="label">the judge\'s '
                     'reasoning</span><p>It gave none.</p></div>')
    parts.append("</li>")
    return "".join(parts)


def render_units(status: str, tests: list[dict]) -> str:
    if status == "skipped" and not tests:
        return ""
    if status == "error":
        return ("<h2>Automated checks</h2><p class=\"note\">The suite could not "
                "be run at all, so none of it was scored. <code>"
                "/flc-check-tests</code> says why.</p>")
    if not tests:
        return ""
    rows = []
    for test in tests:
        ok = str(test.get("status")) == "passed"
        kind = "pass" if ok else "fail"
        message = test.get("message") or ""
        rows.append(f'<tr><td><span class="badge {kind}">'
                    f'{"PASS" if ok else "FAIL"}</span></td>'
                    f"<td>{unit_weight(test)}</td>"
                    f'<td><code>{esc(test.get("name", ""))}</code></td>'
                    f'<td>{esc(message)}</td></tr>')
    passed = sum(1 for t in tests if str(t.get("status")) == "passed")
    return (f"<h2>Automated checks</h2>"
            f'<p class="meta">{passed} of {len(tests)} passed &middot; '
            f"{unit_points(tests)} of {unit_available(tests)} points</p>"
            f'<table class="units"><tr><th></th><th>points</th><th>check</th>'
            f"<th>what it said</th></tr>{''.join(rows)}</table>")


def render(job: Path, logs: Path, root: Path) -> str:
    results, reward, reason = gr.load(logs)
    summary = read_json(logs / "grading_summary.json", {}) or {}
    status, tests = unit_tests(logs)
    when = datetime.now().strftime("%d %B %Y at %H:%M")

    graded = [e for e in results if gr.verdict(e)[0] in ("PASS", "FAIL")]
    ungraded = [e for e in results if gr.verdict(e)[0] == "UNSCORED"]
    available, earned, lost = points(results)
    earned_units, unit_max = unit_points(tests), unit_available(tests)

    # The combined number is the score. A rubric rate on its own reads as the
    # score while the suite carries much of it.
    combined = reward.get("reward")
    headline = (f"{combined:.0%}" if isinstance(combined, (int, float))
                else "not scored")
    total_max = available + unit_max
    total_score = earned - lost + earned_units

    parts = [f'<div class="part"><span class="label">rubric</span>'
             f"{earned - lost} of {available} points</div>"]
    if lost:
        parts.append(f'<div class="part"><span class="label">lost to traps'
                     f"</span>{lost} points</div>")
    if tests:
        parts.append(f'<div class="part"><span class="label">automated checks'
                     f"</span>{earned_units} of {unit_max} points</div>")
    parts.append(f'<div class="part"><span class="label">criteria held</span>'
                 f"{sum(1 for e in graded if gr.verdict(e)[0] == 'PASS')} "
                 f"of {len(graded)}</div>")

    alarms = []
    if reason:
        alarms.append("<div class=\"alarm\"><h2>Nothing was graded</h2>"
                      f"<p>{esc(reason)}</p><p>This is not a result about the "
                      "model, and the run itself may have been fine. Report it "
                      "rather than rewriting the task around it.</p></div>")
    if ungraded:
        alarms.append("<div class=\"alarm\"><h2>"
                      f"{len(ungraded)} criterion(s) were not graded</h2>"
                      "<p>The score above is over the rest of the rubric, so it "
                      "describes less of your task than it looks like it does. "
                      "Each one says below what to do about it.</p></div>")
    if isinstance(combined, (int, float)) and combined >= st.MAX_SOLVER_REWARD:
        alarms.append("<div class=\"alarm\"><h2>This is too easy to deliver"
                      f"</h2><p>The bar is {st.MAX_SOLVER_REWARD:.0%}, and the "
                      "model scored at or above it. That is a finding rather "
                      "than a failure: we are not measuring how often models "
                      "get things wrong, we are collecting the cases where they "
                      "do, and a run with no mistake in it is a trajectory "
                      "nobody can study. The task needs to be harder.</p></div>")

    crits = "".join(render_criterion(e) for e in results)
    if not results:
        crits = ('<li class="crit" data-verdict="ungraded"><p class="text">'
                 "No criteria were graded on this run.</p></li>")

    model = summary.get("judge_model")
    which = f" &middot; judged by {esc(model)}" if model else ""

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>How your task scored -- {esc(job.name)}</title>
<style>{STYLE}</style>
</head>
<body>
<h1>How your task scored</h1>
<p class="meta">{esc(job.name)}{which} &middot; written {esc(when)}</p>

<p class="note">Every criterion you wrote, the verdict the judge reached, and
its reasoning in its own words. Read the reasoning rather than the verdict: it
is the only thing that says whether the judge understood a criterion the way you
meant it. Where it did not, the criterion is what to change -- <code>
/flc-check-grade</code> walks you through that.</p>

<section class="score">
<div class="big">{esc(headline)}</div>
<p class="of">{total_score} of {total_max} points</p>
<div class="parts">{''.join(parts)}</div>
</section>

{''.join(alarms)}

<div class="controls" id="controls" hidden>
<input id="find" type="search" placeholder="find a criterion, a word, a number">
<button id="only" type="button" data-on="no">hide the ones it passed</button>
</div>

<h2>Criteria</h2>
<ol class="crits">{crits}</ol>

{render_units(status, tests)}

<footer>
<p>Full results: <code>{esc(logs / 'evaluation_results.json')}</code></p>
<p>Task: <code>{esc(root)}</code></p>
</footer>
<script>{SCRIPT}</script>
</body>
</html>
"""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--job", help="a job directory (default: the last graded run)")
    ap.add_argument("--task", help="the task folder")
    ap.add_argument("--out", help="where to write the page")
    ap.add_argument("--quiet", action="store_true",
                    help="write the page and say one line about it")
    args = ap.parse_args()

    root = st.task_root(args.task)
    job = Path(args.job).resolve() if args.job else gr.latest_job(root)
    if not job or not job.is_dir():
        print("No solver run found. Start one with /flc-run-solver.",
              file=sys.stderr)
        return 2

    logs = gr.find_logs(job)
    if not logs:
        print(f"This run has not been graded yet, so there is nothing to show.\n"
              "Grade it with /flc-grade.", file=sys.stderr)
        return 2

    out = Path(args.out) if args.out else root / "review" / f"grade-{job.name}.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render(job, logs, root), encoding="utf-8")

    if args.quiet:
        print(f"  grade written:  {out}  (download and open in a browser)")
    else:
        print(f"\n  wrote {out}")
        print("\n  Download that file out of the sandbox and open it in your")
        print("  own browser. It is every criterion with the judge's reasoning")
        print("  for it, which is what /flc-check-grade asks you to check.\n")
    vr.warn_if_submitted(root)
    return 0


if __name__ == "__main__":
    sys.exit(main())
