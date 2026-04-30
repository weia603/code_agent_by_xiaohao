#!/usr/bin/env bash
set -euo pipefail
cd /data/openclaw/youware
export PYTHONPATH=/data/openclaw/youware/scripts
python3 scripts/run_minibatch_parallel.py /data/openclaw/youware_0423/inputs/t0046_sample_input.json --concurrency 6
