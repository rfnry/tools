SHELL := /bin/bash
.PHONY: check

check:
	@python3 scripts/lint-comment.py --self-test
	@python3 scripts/lint-comment.py
	@python3 scripts/check-repo.py --self-test
	@bash scripts/plan.sh --self-test
	@bash scripts/siblings.sh --self-test
	@bash scripts/pin.sh --self-test
	@for script in scripts/*.sh; do bash -n "$$script" || exit 1; done
	@python3 -c "import json; json.load(open('default.json'))"
	@echo "check: tools passed"
