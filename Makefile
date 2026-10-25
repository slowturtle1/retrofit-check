# Retrofit Check: tests and the approach scorecard.
PY ?= $(shell [ -x .venv/bin/python ] && echo .venv/bin/python || echo python3)

.PHONY: test approach approach-live

test:            ## all tests in sample mode (no Zetaris, Nightshift, H-MEM or keys)
	SAMPLE_MODE=true $(PY) -m pytest -q tests

approach:        ## Tiers 1 to 3: writes approach/report.md and report.json, fails on any gap
	$(PY) scripts/approach_check.py

approach-live:   ## also Tier 4: Zetaris, H-MEM, GitHub and files outside the repo (this Mac)
	$(PY) scripts/approach_check.py --live
