#!/usr/bin/env bash
set -euo pipefail
BASE=${BASE:-http://localhost:8000}
PYTHON=${PYTHON:-.venv-runtime/bin/python}
EXP=${EXP:-exp-001}
TASK=${1:-分析 $EXP 的 bad case，找出低分原因并生成图表}
BODY=$("$PYTHON" -c 'import json,sys; print(json.dumps({"task":sys.argv[1],"experiment_id":sys.argv[2],"created_by":"demo","params":{"score_threshold":0.5}}))' "$TASK" "$EXP")
ID=$(curl --fail --silent --show-error -X POST "$BASE/analyses" -H 'Content-Type: application/json' \
    --data-binary "$BODY" | "$PYTHON" -c 'import json,sys; print(json.load(sys.stdin)["analysis_id"])')
echo "analysis_id=$ID"
for ((i=0; i<150; i++)); do
    RESULT=$(curl --fail --silent --show-error "$BASE/analyses/$ID")
    STATUS=$("$PYTHON" -c 'import json,sys; print(json.load(sys.stdin)["status"])' <<< "$RESULT")
    echo "status=$STATUS"
    case "$STATUS" in
      succeeded)
        "$PYTHON" -m json.tool --no-ensure-ascii <<< "$RESULT"
        echo "图表：$BASE/analyses/$ID/artifacts/workspace/out/<图表文件名>"
        exit 0 ;;
      failed)
        "$PYTHON" -m json.tool --no-ensure-ascii <<< "$RESULT"
        exit 1 ;;
    esac
    sleep 5
done
echo "Polling timed out; inspect $BASE/analyses/$ID" >&2
exit 1
