## What and why

<!-- One or two sentences: what changes, and what problem it solves. -->

## Definition of done

<!-- Applies to every pull request; tick each box, or write under it why it does not apply. -->

- [ ] New code sits in the right layer, and every import points down
      (`tests/unit/test_layering.py` passes).
- [ ] Module docstring with the "can be imported" list; class docstring;
      `:param:` and `:returns:` on every public function.
- [ ] Any new dependency is in the correct extra (or core), pinned to an exact version.
- [ ] Any new environment variable is read in `config.py` and listed in `.env.example`.
- [ ] At least one test under `tests/unit/`; `make test` passes.
- [ ] `make lint` passes, docstring gate included.
- [ ] `CHANGELOG.md` and the affected pages in `docs/` are updated.
- [ ] Validated on a real run, not just unit tests.
