# Common dev tasks for microzoo. Run `make help` for a list.
# Dev runs on the Mac Studio via uv; the Pi installs requirements.txt with pip.

UV ?= uv
RUN := $(UV) run

.PHONY: help install-dev lint fmt test-unit test-integration test-all requirements demo clean

help:  ## Show this help.
	@awk 'BEGIN{FS=":.*##"} /^[a-zA-Z_-]+:.*##/ { printf "  \033[1m%-18s\033[0m %s\n", $$1, $$2 }' $(MAKEFILE_LIST)

install-dev:  ## Create .venv with runtime + dev deps (locked).
	$(UV) sync --locked

lint:  ## ruff check + format check + ty.
	./scripts/lint.sh

fmt:  ## ruff format + autofix.
	./scripts/fmt.sh

test-unit:  ## Fast tests (pure functions, no video I/O).
	./scripts/test.sh unit

test-integration:  ## CLI end to end on synthetic clips.
	./scripts/test.sh integration

test-all:  ## Everything.
	./scripts/test.sh all

requirements:  ## Regenerate requirements.txt (pinned, hashed) for the Pi.
	$(UV) export --no-dev --no-emit-project -o requirements.txt

demo:  ## Render a synthetic clip into data/ and track it.
	./scripts/demo.sh

clean:  ## Remove caches and demo outputs.
	rm -rf .pytest_cache .ruff_cache .hypothesis data/demo*
