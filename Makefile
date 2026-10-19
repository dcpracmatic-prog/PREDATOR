.PHONY: build-morph test bench bench-quick

build-morph:
	$(MAKE) -C vendor/morph_src dump_morph
	@echo "export MORPH_DUMP_BIN=$$(pwd)/vendor/morph_src/dump_morph"

test:
	PYTHONPATH=vendor/clan_src python -m pytest tests -q

bench: build-morph
	MORPH_DUMP_BIN=$${MORPH_DUMP_BIN:-$(PWD)/vendor/morph_src/dump_morph} \
	PYTHONPATH=vendor/clan_src python benchmarks/run_benchmark.py

bench-quick: build-morph
	MORPH_DUMP_BIN=$${MORPH_DUMP_BIN:-$(PWD)/vendor/morph_src/dump_morph} \
	PYTHONPATH=vendor/clan_src python benchmarks/run_benchmark.py --quick
