"""Which environment variable names a pydantic-settings model actually reads.

One copy, imported by `test_compose_env_matches_settings.py` and
`test_installer_env_binds.py`. It was two copies for about an hour, which in this
repo is the beginning of a drift budget.

**The subtle part, and the reason this file exists:** the first version of this
helper added the bare field name as an accepted alias --

    names.add(field_name.upper())

-- which is correct only when the model sets no `env_prefix`. With `env_prefix
= "NODE_"`, the field `node_id` is read from `NODE_NODE_ID` and from nothing else.
But the bare-name line adds `NODE_ID`, so the checker declared the exact broken
variable valid.

That is not hypothetical. `test_compose_env_matches_settings.py` says in its own
docstring that it "would have caught the original bug" of `NODE_ID` where
`NODE_NODE_ID` was meant. With this line present it would not have: it would have
accepted `NODE_ID` and reported the file clean. The compose file was fixed by hand
and the test took the credit.

Verified against the real model rather than reasoned about:

    NODE_ID=x       -> node_id stays "node-local"
    NODE_NODE_ID=x  -> node_id becomes "x"
"""

from __future__ import annotations

from pydantic_settings import BaseSettings


def accepted_env_names(settings_cls: type[BaseSettings]) -> set[str]:
    """Every env var name `settings_cls` will read, and no name it will not.

    Over-accepting is the dangerous direction. A checker built on this set exists to
    say "you set something nothing reads"; a name wrongly in the set turns that
    warning off for precisely the variable that is broken.
    """
    prefix = settings_cls.model_config.get("env_prefix", "") or ""
    names: set[str] = set()

    for field_name, field in settings_cls.model_fields.items():
        # The prefixed form is what pydantic-settings resolves for a plain field.
        names.add(f"{prefix}{field_name}".upper())

        # The BARE field name is readable only when there is no prefix. With one,
        # adding it here is what made this helper bless `NODE_ID`.
        if not prefix:
            names.add(field_name.upper())

        # An explicit validation_alias REPLACES the prefixed form rather than adding
        # to it, so every choice is live and must be accepted.
        alias = field.validation_alias
        if alias is None:
            continue
        if isinstance(alias, str):
            names.add(alias.upper())
        else:  # AliasChoices
            for choice in getattr(alias, "choices", []):
                if isinstance(choice, str):
                    names.add(choice.upper())

    return names
