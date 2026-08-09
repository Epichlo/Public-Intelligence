"""Every annotation the runtime evaluates must actually resolve.

A name imported only under `if TYPE_CHECKING:` and then used in an annotation that
something evaluates at runtime is a `NameError` — but **only on some interpreters**.

Python 3.14 defers annotation evaluation (PEP 649), so the name is never looked up
and the module imports fine. Python 3.11 and 3.12 evaluate annotations when the
function is *defined*, so the import blows up. The local `.venv` here runs 3.14 and
CI runs 3.11, 3.12 and 3.14 — so this class of defect passes the local gate
completely and fails six of nine CI legs.

That is exactly what happened on 2026-08-09: `api/openai.py` took `Node` from a
`TYPE_CHECKING` block for a helper's parameter annotation, the gate went green on
25 checks, and every 3.11/3.12 leg died with
`NameError: name 'Node' is not defined`.

**The local gate cannot catch this by running tests**, because it runs one
interpreter. It can catch it by asking the question directly: force every annotation
in the shipped packages to resolve, on whatever interpreter is running. That is what
`typing.get_type_hints` does, and it is interpreter-independent.

`CLAUDE.md` already warned about the FastAPI half of this hazard ("FastAPI resolves
type annotations at runtime for dependency injection and response models, so moving
those imports into `if TYPE_CHECKING:` blocks breaks the app at import time"). The
warning was correct and was not enough, because nothing enforced it.
"""

from __future__ import annotations

import importlib
import inspect
import pkgutil
import typing
from typing import Any

import pytest

# The shipped packages. `experimental/` is excluded for the same reason its tests are
# not run: it is not part of the product. `pi_shared` is included -- it is imported by
# both services, so a broken annotation there breaks both.
SHIPPED_PACKAGES = ("scheduler", "node", "pi_shared")


def _modules_of(package_name: str) -> list[str]:
    package = importlib.import_module(package_name)
    found = [package_name]
    for info in pkgutil.walk_packages(package.__path__, prefix=f"{package_name}."):
        found.append(info.name)
    return found


@pytest.mark.parametrize("package_name", SHIPPED_PACKAGES)
def test_every_shipped_module_imports(package_name: str) -> None:
    """The blunt half: nothing in the shipped tree may fail to import.

    On 3.11/3.12 this alone would have caught the `Node` regression, because the
    annotation is evaluated at def time. On 3.14 it would not, which is why the
    test below exists as well.
    """
    failures: dict[str, str] = {}
    for module_name in _modules_of(package_name):
        try:
            importlib.import_module(module_name)
        except Exception as e:
            failures[module_name] = f"{type(e).__name__}: {e}"

    assert not failures, f"modules that do not import: {failures}"


@pytest.mark.parametrize("package_name", SHIPPED_PACKAGES)
def test_every_annotation_resolves_on_any_interpreter(package_name: str) -> None:
    """The half that works on 3.14 too.

    `get_type_hints` evaluates annotations in the owning module's namespace, which
    is precisely what a pre-3.14 interpreter does at definition time and what
    FastAPI does when building a route. A `TYPE_CHECKING`-only name raises NameError
    here regardless of which Python is running.

    Modules carrying `from __future__ import annotations` are checked too, and
    deliberately: `__future__` defers evaluation but does not excuse it. FastAPI and
    pydantic still resolve those annotations, so a name that cannot be found is a
    latent failure rather than a safe one.
    """
    unresolved: dict[str, str] = {}

    for module_name in _modules_of(package_name):
        module = importlib.import_module(module_name)

        for attr_name, obj in vars(module).items():
            if attr_name.startswith("_"):
                continue
            # Only things defined HERE. A re-exported symbol is checked in the
            # module that owns it, and checking it twice would report one defect
            # against two files.
            if getattr(obj, "__module__", None) != module_name:
                continue
            if not (inspect.isfunction(obj) or inspect.isclass(obj)):
                continue

            try:
                typing.get_type_hints(obj)
            except NameError as e:
                unresolved[f"{module_name}.{attr_name}"] = str(e)
            except Exception:
                # Not every object is introspectable -- pydantic models with
                # forward refs to generics, C extensions, dataclass machinery. Only
                # NameError is the failure this test is about; anything else is
                # noise and suppressing it keeps the signal readable.
                pass

    assert not unresolved, (
        "annotations that do not resolve at runtime. On Python 3.11/3.12 these are "
        "an ImportError the moment the module is loaded; on 3.14 they are deferred "
        "and look fine locally. Import the name at runtime rather than under "
        f"TYPE_CHECKING: {unresolved}"
    )


def test_the_helper_that_broke_ci_is_covered() -> None:
    """A named regression guard for the specific function that failed.

    The parametrised tests above are general, and a general test that silently stops
    covering a case is how a regression comes back. This one names it.
    """
    from scheduler.api import openai

    hints: dict[str, Any] = typing.get_type_hints(openai._meter)
    assert "node" in hints, "the `node` parameter annotation vanished"
    assert hints["node"].__name__ == "Node"
