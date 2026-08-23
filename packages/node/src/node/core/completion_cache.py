"""Exact-prompt completion memoization with bounded LRU eviction.

This replaced a character-level radix trie that split each prompt into a
"cached prefix" plus suffix and sent only the suffix to Ollama. That was
unsound for generation: a shared text prefix does not give the model the
continuation's context, and an exact repeat -- the one case the trie
matched completely -- computed its suffix as EMPTY, so a repeated question
reached Ollama as an empty prompt and the node served whatever came back.

Memoizing whole completions keyed by the whole prompt has neither defect:
a hit is a question already answered, served verbatim; a miss sends the
prompt through unchanged.
"""

from collections import OrderedDict


class CompletionCache:
    """Bounded LRU map of full prompt to final completion text."""

    def __init__(self, capacity: int = 500) -> None:
        """Initialize the CompletionCache.

        Args:
            capacity: Maximum number of memoized completions before eviction.
        """
        self.capacity = capacity
        # Recency is encoded by position, not by a timestamp: least-recently-used
        # first, most-recently-used last. A clock cannot be used here -- coarse
        # timer granularity makes rapid successive accesses collide on identical
        # values, and wall clocks can step backwards under NTP correction.
        self.entries: OrderedDict[str, str] = OrderedDict()

    def lookup(self, prompt: str) -> str | None:
        """Return the memoized completion for this exact prompt, or None."""
        completion = self.entries.get(prompt)
        if completion is not None:
            self.entries.move_to_end(prompt)
        return completion

    def insert(self, prompt: str, completion: str) -> None:
        """Memoize a completed generation, evicting the oldest entry if over capacity.

        popitem(last=False) takes the front of the ordering in O(1).
        """
        self.entries[prompt] = completion
        self.entries.move_to_end(prompt)
        if len(self.entries) > self.capacity:
            self.entries.popitem(last=False)
