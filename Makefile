SHELL := /bin/bash
.PHONY: check

ACTIONLINT := 1.7.12
ACTIONLINT_SHA256 := 8aca8db96f1b94770f1b0d72b6dddcb1ebb8123cb3712530b08cc387b349a3d8
RENOVATE := 44.199.2

check:
	@python3 scripts/lint-comment.py --self-test
	@python3 scripts/lint-comment.py
	@python3 scripts/check-repo.py --self-test
	@bash scripts/plan.sh --self-test
	@bash scripts/siblings.sh --self-test
	@bash scripts/pin.sh --self-test
	@for script in scripts/*.sh; do bash -n "$$script" || exit 1; done
	@scratch=$$(mktemp -d) && trap 'rm -rf "$$scratch"' EXIT && \
	  curl -fsSL --retry 3 -o "$$scratch/actionlint.tar.gz" \
	    "https://github.com/rhysd/actionlint/releases/download/v$(ACTIONLINT)/actionlint_$(ACTIONLINT)_linux_amd64.tar.gz" && \
	  echo "$(ACTIONLINT_SHA256)  $$scratch/actionlint.tar.gz" | sha256sum --check --quiet --strict && \
	  tar -xzf "$$scratch/actionlint.tar.gz" -C "$$scratch" actionlint && \
	  "$$scratch/actionlint" -shellcheck= -pyflakes= .github/workflows/*.yml templates/*.yml && \
	  echo "check: actionlint $(ACTIONLINT) passed the workflows and the templates"
	@npm_config_loglevel=error npx --yes --package renovate@$(RENOVATE) -- \
	  renovate-config-validator --strict --no-global default.json renovate.json
	@echo "check: tools passed"
