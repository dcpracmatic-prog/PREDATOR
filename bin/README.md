# bin/

Build `dump_morph` from sources:

```bash
cd ../vendor/morph_src && make dump_morph
cp dump_morph ../../bin/  # optional
export MORPH_DUMP_BIN="$(pwd)/dump_morph"
```
