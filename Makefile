.PHONY: build-morph test bench bench-quick bench-pareto bench-exact bench-all

build-morph:
	$(MAKE) -C vendor/morph_src dump_morph
	@echo "export MORPH_DUMP_BIN=$$(pwd)/vendor/morph_src/dump_morph"

test:
	PYTHONPATH=vendor/clan_src python -m pytest tests -q

bench: build-morph
	MORPH_DUMP_BIN=$${MORPH_DUMP_BIN:-$(PWD)/vendor/morph_src/dump_morph} \
	PYTHONPATH=vendor/clan_src python benchmarks/run_benchmark.py --mode scaling

bench-quick: build-morph
	MORPH_DUMP_BIN=$${MORPH_DUMP_BIN:-$(PWD)/vendor/morph_src/dump_morph} \
	PYTHONPATH=vendor/clan_src python benchmarks/run_benchmark.py --mode all --quick

bench-pareto: build-morph
	MORPH_DUMP_BIN=$${MORPH_DUMP_BIN:-$(PWD)/vendor/morph_src/dump_morph} \
	PYTHONPATH=vendor/clan_src python benchmarks/run_benchmark.py --mode pareto

bench-exact: build-morph
	MORPH_DUMP_BIN=$${MORPH_DUMP_BIN:-$(PWD)/vendor/morph_src/dump_morph} \
	PYTHONPATH=vendor/clan_src python benchmarks/run_benchmark.py --mode exact

bench-all: build-morph
	MORPH_DUMP_BIN=$${MORPH_DUMP_BIN:-$(PWD)/vendor/morph_src/dump_morph} \
	PYTHONPATH=vendor/clan_src python benchmarks/run_benchmark.py --mode all

bench-pareto-dense: build-morph
	MORPH_DUMP_BIN=$${MORPH_DUMP_BIN:-$(PWD)/vendor/morph_src/dump_morph} \
	PYTHONPATH=vendor/clan_src python benchmarks/run_benchmark.py --mode pareto \
	  --families ER --avg-deg-list 12 \
	  --n-list 200,500,1000,2000 \
	  --budgets 10,50,100,500 --reps 5 --seed 42

api:
	PYTHONPATH=src:vendor/clan_src python -m ztge.api.server --host 127.0.0.1 --port 8080
