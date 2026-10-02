#!/usr/bin/env bash
# Run the solver agent against the task, as one Harbor job.
#
# This is the only sanctioned way to start a job by hand, so the command line
# never has to be retyped or reconstructed from memory. The model and agent come
# from bin/solver_model.txt.
#
# Usage:
#   run_solver.sh [TASK] [--model NAME]
#                 [--agent NAME] [--job-name NAME] [--no-proxy] [--no-preflight]
#                 [--background] [--status] [--wait] [--dry-run]
#                 [--confirm-rerun] [--limit-reason TEXT]
#
#   run_solver.sh                          # the task at ~/flc/task
#   run_solver.sh --background             # start it and hand the terminal back
#   run_solver.sh --status                 # is it still going?
#   run_solver.sh --dry-run                # print the command without running it
#
# bin/run_guard.py is asked first: the answer has to be written down, a rerun
# of all but the same task waits for --confirm-rerun, and past the run limit
# another run needs --limit-reason in the contributor's own words.
#
# One job is one attempt. Harbor writes each attempt of a multi-attempt job as
# its own trial, with its own transcript and its own finished workspace, and a
# task carries one grade and ships one run -- so a second attempt is a second
# answer nothing downstream can choose between. To see a different run, start
# another job.
#
# A run takes long enough that waiting on it is dead time, and the contributor
# has work to do meanwhile: the completion rubrics come from the ground truth
# and need nothing from the run. --background is what makes that possible, and
# is how /flc-run-solver starts it.
#
# --job-name defaults to run<N>, picking the lowest N still free under the jobs
# directory. Harbor keys a job directory by name and refuses to reuse one with a
# different config, so a name is never silently reused.

set -euo pipefail

FLC_HOME="${FLC_HOME:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
BIN="$FLC_HOME/bin"
JOBS_DIR="${FLC_JOBS_DIR:-$FLC_HOME/jobs}"

TASK_PATH="${FLC_TASK:-$FLC_HOME/task}"
ATTEMPTS=1
CONCURRENT=""
JOB_NAME=""
MODEL=""
AGENT=""
DRY_RUN=0
USE_PROXY=1
PREFLIGHT=1
BACKGROUND=0
STATUS=0
WAIT=0
CONFIRM_RERUN=0
LIMIT_REASON=""

die() { echo "run_solver.sh: $*" >&2; exit 1; }
usage() { awk 'NR>1 && /^#/ {sub(/^# ?/, ""); print; next} NR>1 {exit}' "${BASH_SOURCE[0]}"; }

while [ $# -gt 0 ]; do
  case "$1" in
    -h|--help)      usage; exit 0 ;;
    -b|--background) BACKGROUND=1; shift ;;
    --status)       STATUS=1; shift ;;
    --wait)         WAIT=1; shift ;;
    --attempts)     ATTEMPTS="${2:?}"; shift 2 ;;
    --concurrent)   CONCURRENT="${2:?}"; shift 2 ;;
    --job-name)     JOB_NAME="${2:?}"; shift 2 ;;
    --jobs-dir)     JOBS_DIR="${2:?}"; shift 2 ;;
    --model)        MODEL="${2:?}"; shift 2 ;;
    --agent)        AGENT="${2:?}"; shift 2 ;;
    --no-proxy)     USE_PROXY=0; shift ;;
    --no-preflight) PREFLIGHT=0; shift ;;
    --dry-run)      DRY_RUN=1; shift ;;
    --confirm-rerun) CONFIRM_RERUN=1; shift ;;
    --limit-reason) LIMIT_REASON="${2:?}"; shift 2 ;;
    -*)             die "unknown option: $1 (see --help)" ;;
    *)              TASK_PATH="$1"; shift ;;
  esac
done

# Argument shape, before anything is looked up or measured: a malformed request
# is answered without first telling the contributor about the state of a task
# the request was never going to act on.
case "$ATTEMPTS" in ''|*[!0-9]*) die "--attempts must be a positive integer" ;; esac
case "${CONCURRENT:-1}" in ''|*[!0-9]*) die "--concurrent must be a positive integer" ;; esac
[ "$ATTEMPTS" -ge 1 ] || die "--attempts must be at least 1"
# Harbor writes each attempt as its own trial, with its own transcript and its
# own finished workspace. A task carries one grade and ships one run, so a job
# holding several leaves every reader choosing between answers.
if [ "$ATTEMPTS" -gt 1 ] || [ "${CONCURRENT:-1}" -gt 1 ]; then
  die "one job is one attempt.
  Harbor writes each attempt as a separate trial, with its own transcript and
  its own copy of the finished workspace, and this task ships one run and one
  grade -- so nothing downstream can say which attempt the score belongs to.
  To compare runs, start a second job instead:
    bash bin/run_solver.sh --background"
fi

# The model and agent are read from one file.
conf="$BIN/solver_model.txt"
[ -f "$conf" ] || die "no $conf"
[ -n "$MODEL" ] || MODEL="$(sed -n 's/^[[:space:]]*model[[:space:]]*=[[:space:]]*\(.*\)$/\1/p' "$conf" | head -n1)"
[ -n "$AGENT" ] || AGENT="$(sed -n 's/^[[:space:]]*agent[[:space:]]*=[[:space:]]*\(.*\)$/\1/p' "$conf" | head -n1)"
[ -n "$MODEL" ] || die "no model in $conf"
[ -n "$AGENT" ] || die "no agent in $conf"

# Provider-prefixed: the agents reject a bare name with
# `ValueError: Model name must be in the format provider/model_name`.
case "$MODEL" in */*) ;; *) die "model must be provider-prefixed, e.g. anthropic/claude-opus-5 (got '$MODEL')" ;; esac

[ -d "$TASK_PATH" ] || die "not a directory: $TASK_PATH"
[ -f "$TASK_PATH/task.toml" ] || die "no task.toml in $TASK_PATH -- is this a task folder?"
TASK_PATH="$(cd -- "$TASK_PATH" && pwd)"

state_get() { FLC_TASK="$TASK_PATH" python3 "$BIN/flc_state.py" get "$1" 2>/dev/null \
              | python3 -c 'import json,sys; v=json.load(sys.stdin); print("" if v is None else v)' 2>/dev/null; }
state_set() { FLC_TASK="$TASK_PATH" python3 "$BIN/flc_state.py" set "$1" "$2" >/dev/null 2>&1 || true; }

# A pid we can signal is the whole liveness test. Harbor writes its results only
# at the end, so nothing in the job directory distinguishes "still going" from
# "died in the middle" -- which is the difference the contributor is asking about.
run_alive() {
  local pid; pid="$(state_get run_pid)"
  [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null
}

report_status() {
  local pid job log
  pid="$(state_get run_pid)"; job="$(state_get last_job)"; log="$(state_get run_log)"
  if [ -z "$pid" ] && [ -z "$job" ]; then
    echo "No run has been started yet. Start one with /flc-run-solver."
    return 0
  fi
  if run_alive; then
    echo "STILL RUNNING (pid $pid)"
    echo "  results will land in: $job"
    [ -n "$log" ] && echo "  live output:          $log"
    echo
    echo "This is the time to write your completion criteria -- they come from"
    echo "your ground truth and need nothing from the run. Run /flc-rubrics."
  else
    echo "FINISHED"
    [ -n "$job" ] && echo "  results: $job"
    [ -n "$log" ] && echo "  output:  $log"
    echo
    # Said here as well as at grading.
    FLC_TASK="$TASK_PATH" python3 "$BIN/context_report.py" 2>/dev/null || true
    echo
    # The step that gets skipped is reading the run, and this message is the
    # moment it gets skipped at. Resolving the paths is done in Python, where
    # the job layout is already understood and the selftest can cover it.
    FLC_TASK="$TASK_PATH" python3 "$BIN/view_run.py" --where 2>/dev/null || true
    echo
    echo "Read the run before you write anything about it. Run /flc-inspect."
    echo "The non-hallucination criteria come from what the model actually"
    echo "claimed, and the answer alone does not show you that."
  fi
}

if [ "$STATUS" -eq 1 ]; then
  report_status
  exit 0
fi

if [ "$WAIT" -eq 1 ]; then
  if ! run_alive; then report_status; exit 0; fi
  echo "waiting for the run to finish (pid $(state_get run_pid)) ..."
  while run_alive; do sleep 10; done
  report_status
  exit 0
fi

if run_alive; then
  die "a run is already going -- /flc-status shows how it is getting on; wait for it to finish"
fi

# instruction.md is generated from prompt.md, which the contributor edits by
# hand. Regenerating here is what stops a run being spent on a stale prompt,
# and it comes before the gate below, which compares generated files.
FLC_TASK="$TASK_PATH" python3 "$BIN/flc_state.py" regenerate

# The cheap checks come first: a run will not start until check_inputs has
# passed, and passed on the workspace as it stands rather than an earlier one.
if ! FLC_TASK="$TASK_PATH" python3 "$BIN/check_inputs.py" --gate; then
  die "the run cannot start yet: do what the line above says, then start it again"
fi

# And not until this script is the one the seed shipped. A run is the
# expensive artefact and everything else is measured against it, so a
# transcript produced by a changed solver is worth nothing to compare with.
if ! FLC_TASK="$TASK_PATH" python3 "$BIN/check_integrity.py" \
     --step run_solver --quiet; then
  exit 1
fi

# And not until this machine can start the container task.toml describes. This
# runs before the job directory is created, so a refusal here leaves nothing
# behind that later reads as a run.
if ! FLC_TASK="$TASK_PATH" python3 "$BIN/flc_state.py" check-resources; then
  exit 1
fi

# Harbor runs the verifier as part of `harbor run`, straight after the agent.
# This step is meant to produce a transcript and nothing else: the hallucination
# criteria are written from that transcript, so grading now
# would score a rubric with its second half missing, and /flc-grade would report
# it. task.toml passes this into the verifier, where test.sh reads it; grading
# happens later, on request, through run_grader.py.
export FLC_DEFER_GRADING=1

CONCURRENT="${CONCURRENT:-$ATTEMPTS}"

if [ -n "$JOB_NAME" ]; then
  [ -e "$JOBS_DIR/$JOB_NAME" ] && \
    die "job directory already exists: $JOBS_DIR/$JOB_NAME (pick a fresh --job-name)"
else
  # The log counts as taking the name too, so a run that dies before Harbor
  # creates its directory does not hand the same name to the next one.
  n=1
  while [ -e "$JOBS_DIR/run${n}" ] || [ -e "$JOBS_DIR/run${n}.log" ]; do n=$((n + 1)); done
  JOB_NAME="run${n}"
fi

# Whether this run is worth starting. Before the job directory exists, so a
# refusal or a question leaves nothing behind that reads as a run. Exit 3 is
# a question for the contributor, and is passed back as it is.
GUARD_ARGS=(--job-name "$JOB_NAME" --jobs-dir "$JOBS_DIR")
[ "$CONFIRM_RERUN" -eq 1 ] && GUARD_ARGS+=(--confirm-rerun)
[ -n "$LIMIT_REASON" ] && GUARD_ARGS+=(--limit-reason "$LIMIT_REASON")
[ "$DRY_RUN" -eq 1 ] && GUARD_ARGS+=(--dry-run)
guard_rc=0
FLC_TASK="$TASK_PATH" python3 "$BIN/run_guard.py" "${GUARD_ARGS[@]}" || guard_rc=$?
[ "$guard_rc" -eq 0 ] || exit "$guard_rc"

AGENT_ENV_ARGS=()
if [ "$USE_PROXY" -eq 1 ]; then
  PROXY_DIR="$FLC_HOME/.proxy"
  mkdir -p -- "$PROXY_DIR"
  PROXY_ARGS=(--out-dir "$PROXY_DIR")
  { [ "$PREFLIGHT" -eq 1 ] && [ "$DRY_RUN" -eq 0 ]; } || PROXY_ARGS+=(--no-preflight)
  bash "$BIN/proxy_setup.sh" "${PROXY_ARGS[@]}" >&2 \
    || die "the run cannot reach the model (proxy_setup.sh found no reachable credentials). This is a technical issue on our side, not your task: please reach out to the project team."

  PROXY_ENV_SH="$PROXY_DIR/.flc_proxy_env.sh"
  PROXY_ENV_JSON="$PROXY_DIR/.flc_proxy_agent_env.json"
  [ -f "$PROXY_ENV_JSON" ] || die "proxy_setup.sh wrote no agent env at $PROXY_ENV_JSON"
  # Real keys into this shell, so Harbor can expand the ${VAR} placeholders
  # below. No key is ever written into the job config.
  # shellcheck source=/dev/null
  [ -f "$PROXY_ENV_SH" ] && . "$PROXY_ENV_SH"

  while IFS= read -r pair; do
    [ -n "$pair" ] && AGENT_ENV_ARGS+=(--agent-env "$pair")
  done < <(python3 -c '
import json, sys
for k, v in json.load(open(sys.argv[1])).items():
    print(f"{k}={v}")
' "$PROXY_ENV_JSON")
  [ "${#AGENT_ENV_ARGS[@]}" -gt 0 ] || die "proxy_setup.sh produced an empty agent env"

  # The verifier needs the same address the agent got, and for the same reason.
  # Harbor expands ${OPENAI_API_BASE} in [verifier.env] out of this shell, where
  # sourcing the proxy env leaves the gateway's own `localhost:8090` -- which
  # inside the verifier's container is that container. proxy_setup.sh rewrites
  # loopback to the host alias for the agent, the agent reaches the gateway with
  # it, and the verifier is a container of the same kind. Without this, a run
  # that does grade (one overridden with FLC_GRADE_NOW, or any harness that
  # grades in place) fails
  # every criterion on a refused connection. Only the endpoints move; the keys
  # are already in this shell and are not rewritten.
  while IFS= read -r pair; do
    [ -n "$pair" ] && export "${pair?}"
  done < <(python3 -c '
import json, sys
for k, v in json.load(open(sys.argv[1])).items():
    if k.endswith(("_BASE", "_BASE_URL")) and isinstance(v, str) and v.startswith("http"):
        print(f"{k}={v}")
' "$PROXY_ENV_JSON")

  # Harbor sources /etc/profile.d/testbed-conda.sh under `set -euo pipefail`; it
  # opens with `if [ -z "$CONDA_DEFAULT_ENV" ]`, so on an image without conda
  # `set -u` aborts the source and the trial exits before the agent starts.
  # Defined-but-empty satisfies the guard.
  AGENT_ENV_ARGS+=(--agent-env "CONDA_DEFAULT_ENV=")

  # Reaching the proxy is not enough: Harbor firewalls the agent phase, and a
  # host that is merely routable gets its connection reset -- reported as
  # UnknownApiError, indistinguishable from a bad key. Derived from the URLs
  # proxy_setup.sh just produced, so it tracks the host-alias rewrite.
  while IFS= read -r host; do
    [ -n "$host" ] && AGENT_ENV_ARGS+=(--allow-agent-host "$host")
  done < <(python3 -c '
import json, sys
from urllib.parse import urlparse
seen = []
for v in json.load(open(sys.argv[1])).values():
    if isinstance(v, str) and v.startswith(("http://", "https://")):
        h = urlparse(v).hostname
        if h and h not in seen:
            seen.append(h)
print("\n".join(seen))
' "$PROXY_ENV_JSON")
fi

CMD=(harbor run
  --path "$TASK_PATH"
  --agent "$AGENT"
  --model "$MODEL"
  --n-attempts "$ATTEMPTS"
  --n-concurrent "$CONCURRENT"
  --jobs-dir "$JOBS_DIR"
  --job-name "$JOB_NAME"
  --yes)
CMD+=(${AGENT_ENV_ARGS[@]+"${AGENT_ENV_ARGS[@]}"})

printf '%s' '$'
printf ' %q' "${CMD[@]}"
printf '\n'

if [ "$DRY_RUN" -eq 1 ]; then
  echo "(--dry-run: nothing was started)"
  exit 0
fi

command -v harbor >/dev/null 2>&1 || die "the program that runs the model is missing (harbor is not on PATH; ~/.flc/harbor_upgrade.log). This is a technical issue on our side, not your task: please reach out to the project team."

mkdir -p -- "$JOBS_DIR"
echo "results -> $JOBS_DIR/$JOB_NAME"
# Recorded so /flc-grade and /flc-deliver can find the run without asking.
state_set last_job "$JOBS_DIR/$JOB_NAME"
state_set run_started "$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
# The model this run asked for. What answered it is read back off the
# transcript afterwards by model_check.py and compared against this.
state_set solver_model "$MODEL"
state_set solver_agent "$AGENT"
# The same, kept against the job, for reading back after later runs.
FLC_TASK="$TASK_PATH" python3 "$BIN/flc_state.py" record-run \
  "$JOBS_DIR/$JOB_NAME" "$MODEL" "$AGENT" >/dev/null 2>&1 || true
# And what the model is about to be shown, so that a prompt or a workspace
# edited afterwards can be told from one the run was actually against. The
# score from this run is the evidence for the difficulty bar, and evidence
# about a version of the task that no longer exists is not evidence.
FLC_TASK="$TASK_PATH" python3 "$BIN/flc_state.py" fingerprint run_fingerprint \
  >/dev/null 2>&1 || true
# The answer as it stood before the model saw the task. Nothing is blocked on
# it moving afterwards -- the remedy for a ground truth that was wrong is to
# correct it -- but a delivery whose answer was rewritten after the score was
# taken is a different thing from one whose answer never moved, and only this
# tells them apart.
FLC_TASK="$TASK_PATH" python3 "$BIN/flc_state.py" pin-ground-truth \
  >/dev/null 2>&1 || true

# The run is followed by a look at what the agent had to install for itself,
# which is the only reliable way to learn what the image was missing, and by
# the review document and the readable page of the run, so both are waiting when
# they come back to it. Never fatal -- a reporting step must not turn a finished
# run into a failure.
POST="FLC_TASK=$(printf '%q' "$TASK_PATH") python3 $(printf '%q' "$BIN/model_check.py") --quiet || true"
POST="$POST; FLC_TASK=$(printf '%q' "$TASK_PATH") python3 $(printf '%q' "$BIN/detect_packages.py") --quiet || true"
POST="$POST; FLC_TASK=$(printf '%q' "$TASK_PATH") python3 $(printf '%q' "$BIN/context_report.py") --record || true"
POST="$POST; FLC_TASK=$(printf '%q' "$TASK_PATH") python3 $(printf '%q' "$BIN/run_guard.py") --record || true"
POST="$POST; FLC_TASK=$(printf '%q' "$TASK_PATH") python3 $(printf '%q' "$BIN/review_run.py") --quiet || true"
POST="$POST; FLC_TASK=$(printf '%q' "$TASK_PATH") python3 $(printf '%q' "$BIN/view_run.py") --quiet || true"

if [ "$BACKGROUND" -eq 1 ]; then
  LOG="$JOBS_DIR/$JOB_NAME.log"
  : > "$LOG"
  # %q keeps any ${VAR} the proxy put in an --agent-env value literal, so Harbor
  # still expands it itself, exactly as it does on the foreground path.
  runner="$(printf '%q ' "${CMD[@]}"); rc=\$?; echo; $POST; echo \"[flc] run finished, exit code \$rc\"; exit \$rc"
  # nohup exec's, so \$! really is the run: a SIGHUP when this shell goes away
  # would otherwise take the run with it, which is the whole point of detaching.
  nohup bash -c "$runner" >>"$LOG" 2>&1 </dev/null &
  RUN_PID=$!
  disown "$RUN_PID" 2>/dev/null || true
  state_set run_pid "$RUN_PID"
  state_set run_log "$LOG"

  cat <<EOF

Started in the background (pid $RUN_PID). You do not have to sit and watch it.
  live output:  $LOG
  is it done:   /flc-status

While it runs, write your completion criteria -- they come from your ground
truth and need nothing from this run. Run /flc-rubrics.
EOF
  exit 0
fi

# Recorded on this path too, so anything asking "is a run going" gets the same
# answer whether it was started in the foreground or not.
state_set run_pid "$$"
trap 'state_set run_pid ""' EXIT

"${CMD[@]}"
rc=$?

echo
# The same as the background path.
FLC_TASK="$TASK_PATH" python3 "$BIN/model_check.py" --quiet || true
FLC_TASK="$TASK_PATH" python3 "$BIN/detect_packages.py" --quiet || true
FLC_TASK="$TASK_PATH" python3 "$BIN/context_report.py" --record || true
FLC_TASK="$TASK_PATH" python3 "$BIN/run_guard.py" --record || true
FLC_TASK="$TASK_PATH" python3 "$BIN/review_run.py" --quiet || true
FLC_TASK="$TASK_PATH" python3 "$BIN/view_run.py" --quiet || true
echo
FLC_TASK="$TASK_PATH" python3 "$BIN/view_run.py" --where 2>/dev/null || true
echo
echo "Read the run before you write anything about it. Run /flc-inspect."

exit "$rc"
