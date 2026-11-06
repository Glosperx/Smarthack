"""
The layering guard: every dependency inside the package points down.

The architecture's first rule is that a layer may import from its own rank or
below, never above. Written down, it is a habit; checked here, it is a failed
build. Every `.py` file in the package is parsed with `ast` — read, never
executed — and every import that points back into the package is collected at
**any depth**: the top of the file, inside a function, under `if TYPE_CHECKING`.
A local import that points up is still an import that points up.

Three things keep the guard from passing on nothing:

- a module whose top-level folder has no rank fails, so a new layer cannot
  arrive unranked and unchecked;
- relative imports are resolved, not skipped;
- the scan must find a realistic number of imports.

What it cannot see: a module named in a string, `importlib.import_module("...")`.
Do not use it for internal imports.

**Adding a layer** is a decision made here: give its top-level folder a rank in
`RANKS`, at the rank of the highest layer it imports from. Foundation modules
(`config`, `constants`, `utils`) are rank 0 and import nothing above them.
"""

import ast
from pathlib import Path
import textwrap

import pytest

import smarthack

PACKAGE = smarthack.__name__
PACKAGE_DIR = Path(smarthack.__file__).parent

#: The rank of each top-level module or folder of the package. The empty key is
#: the package root, which holds only `__version__` and imports nothing. A new
#: layer goes between the foundation and the entry point: renumber `__main__`
#: above it, since the entry point imports whatever it starts and nothing imports it.
RANKS: dict[str, int] = {
    "": 0,
    "config": 0,
    "constants": 0,
    "utils": 0,
    "__main__": 1,
}

#: Below this, the scan is assumed to have missed files rather than found a
#: small package. 5 internal imports existed when the guard was written; raise
#: it as the package grows, so it keeps meaning "the scan found things".
MINIMUM_IMPORTS = 5

#: Names directly under the package root that are modules or folders. Needed to
#: tell `from smarthack import utils` (a layer) from `from smarthack import
#: __version__` (an attribute of the root).
SUBMODULES = {path.stem for path in PACKAGE_DIR.glob("*.py")} | {
    path.name for path in PACKAGE_DIR.iterdir() if (path / "__init__.py").is_file()
}


def module_name(path: Path) -> str:
    """
    Turn a file of the package into its dotted module name.

    :param path: A `.py` file under the package folder.

    :returns name: Such as `smarthack.utils.logging_utils`; a package's
        `__init__.py` is named after the package itself.
    """
    parts = list(path.relative_to(PACKAGE_DIR.parent).with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def rank_of(module: str) -> int | None:
    """
    Look up the layer a module belongs to.

    :param module: A dotted name inside the package, or the package itself.

    :returns rank: The rank of its top-level module or folder, or None when that
        name has no rank.
    """
    parts = module.split(".")
    return RANKS.get(parts[1] if len(parts) > 1 else "")


def is_internal(module: str) -> bool:
    """
    Report whether a dotted name is the package or something inside it.

    :param module: A dotted module name.

    :returns internal: True for the package and `<package>.<anything>`, False for
        a lookalike such as `<package>_extra`.
    """
    return module == PACKAGE or module.startswith(f"{PACKAGE}.")


def internal_imports(source: str, module: str, is_package: bool) -> list[tuple[int, str]]:
    """
    Collect every import of the package made anywhere in a source file.

    `ast.walk` visits every node, so an import inside a function, a class, a
    `try` or an `if TYPE_CHECKING` block is found like one at the top of the file.

    :param source: The file's source code.
    :param module: The file's dotted module name, used to resolve relative imports.
    :param is_package: True when the file is a package's `__init__.py`, where a
        relative import starts from the package itself rather than its parent.

    :returns imports: `(line, imported module)` pairs, in the order found.
    """
    found: list[tuple[int, str]] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            found += [(node.lineno, alias.name) for alias in node.names if is_internal(alias.name)]
            continue
        if not isinstance(node, ast.ImportFrom):
            continue

        base = node.module or ""
        if node.level:
            package = module.split(".") if is_package else module.split(".")[:-1]
            anchor = package[: len(package) - (node.level - 1)]
            base = ".".join(anchor + ([node.module] if node.module else []))
        if not is_internal(base):
            continue

        if base != PACKAGE:
            found.append((node.lineno, base))
            continue
        # From the root, a name is either a layer or an attribute of the root itself.
        for alias in node.names:
            target = f"{PACKAGE}.{alias.name}" if alias.name in SUBMODULES else PACKAGE
            found.append((node.lineno, target))
    return found


def package_files() -> list[Path]:
    """
    List every source file of the package.

    :returns paths: Every `.py` file under the package folder, sorted.
    """
    return sorted(PACKAGE_DIR.rglob("*.py"))


def all_internal_imports() -> list[tuple[Path, int, str, str]]:
    """
    Scan the whole package.

    :returns imports: `(file, line, importing module, imported module)` for every
        internal import in the package.
    """
    scanned: list[tuple[Path, int, str, str]] = []
    for path in package_files():
        importer = module_name(path)
        source = path.read_text(encoding="utf-8")
        for line, imported in internal_imports(source, importer, path.name == "__init__.py"):
            scanned.append((path, line, importer, imported))
    return scanned


def find_violations(imports: list[tuple[Path, int, str, str]]) -> list[str]:
    """
    Pick out the imports that point to a higher rank than the importer's.

    An import whose either side has no rank is skipped here: that is reported by
    `test_every_module_has_a_rank`, once, rather than once per import.

    :param imports: `(file, line, importing module, imported module)` tuples, as
        `all_internal_imports` returns them.

    :returns violations: One message per offending import, with file and line.
    """
    violations: list[str] = []
    for path, line, importer, imported in imports:
        importer_rank, imported_rank = rank_of(importer), rank_of(imported)
        if importer_rank is None or imported_rank is None:
            continue
        if imported_rank > importer_rank:
            where = path.relative_to(PACKAGE_DIR.parent)
            violations.append(
                f"{where}:{line}: {importer} (rank {importer_rank}) imports "
                f"{imported} (rank {imported_rank})"
            )
    return violations


def test_every_module_has_a_rank() -> None:
    """
    A module outside the rank table is a module the guard cannot judge.

    Without this, a new top-level folder would get `None` as its rank and every
    comparison involving it would have to be skipped — the guard would stay green
    while checking nothing about the new layer.
    """
    unranked = [module_name(path) for path in package_files() if rank_of(module_name(path)) is None]

    assert not unranked, (
        f"no rank for {unranked}. Add the top-level name to RANKS in this file, "
        f"at the rank of the highest layer it imports from."
    )


def test_no_module_imports_from_a_layer_above_its_own() -> None:
    """
    The rule itself: the imported rank is never higher than the importer's.

    Every violation in the package is reported at once, with the file and line,
    rather than stopping at the first.
    """
    violations = find_violations(all_internal_imports())

    assert not violations, "imports that point up a layer:\n" + "\n".join(violations)


def test_the_guard_reports_an_upward_import() -> None:
    """
    The rule is not vacuous: an import that points up is named, with file and line.

    Fed a made-up import of the entry point from the foundation, which the real
    package does not contain, so a broken comparison cannot hide behind a clean tree.
    """
    made_up = [(PACKAGE_DIR / "utils" / "x.py", 7, f"{PACKAGE}.utils.x", f"{PACKAGE}.__main__")]

    assert find_violations(made_up) == [
        f"{PACKAGE}/utils/x.py:7: {PACKAGE}.utils.x (rank 0) imports {PACKAGE}.__main__ (rank 1)"
    ]


def test_the_scan_finds_the_package_imports() -> None:
    """
    Guard against the guard passing on nothing.

    A wrong package path or a broken filter would find zero imports, and zero
    imports contain zero violations.
    """
    assert len(all_internal_imports()) >= MINIMUM_IMPORTS


@pytest.mark.parametrize(
    "source, module, is_package, expected",
    [
        pytest.param(
            f"from {PACKAGE}.__main__ import main",
            f"{PACKAGE}.utils.logging_utils",
            False,
            [(1, f"{PACKAGE}.__main__")],
            id="from-import",
        ),
        pytest.param(
            f"import {PACKAGE}.utils.logging_utils as logging_utils",
            f"{PACKAGE}.config",
            False,
            [(1, f"{PACKAGE}.utils.logging_utils")],
            id="plain-import-with-alias",
        ),
        pytest.param(
            f"""
            def run():
                from {PACKAGE}.utils import logging_utils
            """,
            f"{PACKAGE}.config",
            False,
            [(3, f"{PACKAGE}.utils")],
            id="inside-a-function",
        ),
        pytest.param(
            f"""
            from typing import TYPE_CHECKING
            if TYPE_CHECKING:
                from {PACKAGE} import utils
            """,
            f"{PACKAGE}.config",
            False,
            [(4, f"{PACKAGE}.utils")],
            id="under-type-checking",
        ),
        pytest.param(
            f"from {PACKAGE} import utils, __version__",
            f"{PACKAGE}.config",
            False,
            [(1, f"{PACKAGE}.utils"), (1, PACKAGE)],
            id="layer-and-attribute-from-the-root",
        ),
        pytest.param(
            "from ..utils.logging_utils import configure_logging",
            f"{PACKAGE}.utils.optional_imports",
            False,
            [(1, f"{PACKAGE}.utils.logging_utils")],
            id="relative-from-a-module",
        ),
        pytest.param(
            "from . import logging_utils",
            f"{PACKAGE}.utils",
            True,
            [(1, f"{PACKAGE}.utils")],
            id="relative-from-a-package-init",
        ),
        pytest.param(
            f"import numpy\nimport {PACKAGE}_extra\nfrom dotenv import load_dotenv",
            f"{PACKAGE}.config",
            False,
            [],
            id="third-party-and-lookalikes-ignored",
        ),
    ],
)
def test_the_scanner_finds_imports_in_every_form(
    source: str, module: str, is_package: bool, expected: list[tuple[int, str]]
) -> None:
    """
    Each way of writing an import is seen, and resolved to the right module.

    These pin the scanner itself: a form it silently missed would make the guard
    green on exactly the imports it exists to catch.
    """
    assert internal_imports(textwrap.dedent(source), module, is_package) == expected


def test_ranks_follow_the_top_level_name() -> None:
    """A module takes the rank of its top-level folder; the root package is rank 0."""
    assert rank_of(PACKAGE) == 0
    assert rank_of(f"{PACKAGE}.utils.logging_utils") == 0
    assert rank_of(f"{PACKAGE}.__main__") == 1
    assert rank_of(f"{PACKAGE}.not_a_layer") is None
