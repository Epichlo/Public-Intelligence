"""In-memory Radix Trie Cache with LRU eviction for prompt prefix acceleration."""

import time


class RadixTrieNode:
    """A node in the Radix Trie representing a compressed path of tokens."""

    def __init__(self, path: list[str]) -> None:
        """Initialize the RadixTrieNode.

        Args:
            path: Compressed path of string tokens.
        """
        self.path = path
        self.children: list[RadixTrieNode] = []
        self.is_leaf: bool = False


class RadixTrieCache:
    """In-memory Radix Trie Cache with bounded LRU eviction."""

    def __init__(self, capacity: int = 500) -> None:
        """Initialize the RadixTrieCache.

        Args:
            capacity: Configurable maximum number of distinct prompt paths
                before eviction.
        """
        self.capacity = capacity
        self.root = RadixTrieNode([])
        self.prompts: dict[str, float] = {}  # prompt string -> last accessed timestamp

    async def lookup_prefix(self, prompt: str) -> tuple[str, str]:
        """Search the cache for the longest matching prefix of the prompt.

        Args:
            prompt: The input prompt string.

        Returns:
            A tuple of (matched prefix string, remaining suffix string).
        """
        prefix_tokens, suffix_tokens = self._search_trie(prompt)
        prefix_str = "".join(prefix_tokens)
        suffix_str = "".join(suffix_tokens)

        # Update last accessed times of matching cached prompt paths
        if prefix_str:
            now = time.time()
            for p in list(self.prompts.keys()):
                if p.startswith(prefix_str):
                    self.prompts[p] = now

        return prefix_str, suffix_str

    async def insert_prefix(self, prompt: str) -> None:
        """Insert a prompt path into the Radix Trie, executing LRU eviction.

        Eviction occurs if capacity is exceeded.

        Args:
            prompt: The prompt string to insert.
        """
        self.prompts[prompt] = time.time()

        if len(self.prompts) > self.capacity:
            # Bounded LRU eviction: pop the least recently used path
            oldest_prompt = min(self.prompts, key=self.prompts.get)  # type: ignore[arg-type]
            self.prompts.pop(oldest_prompt, None)
            # Rebuild the trie to flush out the dead path
            self._rebuild_trie()
        else:
            self._insert_into_trie(prompt)

    def _tokenize(self, prompt: str) -> list[str]:
        """Tokenize prompt into character tokens for exact suffix preservation."""
        return list(prompt)

    def _get_common_prefix_length(self, path1: list[str], path2: list[str]) -> int:
        """Calculate the length of the common prefix between two paths."""
        length = 0
        for t1, t2 in zip(path1, path2, strict=False):
            if t1 == t2:
                length += 1
            else:
                break
        return length

    def _search_trie(self, prompt: str) -> tuple[list[str], list[str]]:
        """Search the trie for the longest matching prefix path."""
        tokens = self._tokenize(prompt)
        prefix: list[str] = []
        curr = self.root
        remaining = tokens

        while remaining:
            matched_child = None
            for child in curr.children:
                common = self._get_common_prefix_length(child.path, remaining)
                if common == len(child.path):
                    matched_child = child
                    break

            if matched_child is not None:
                prefix.extend(matched_child.path)
                remaining = remaining[len(matched_child.path) :]
                curr = matched_child
            else:
                break

        return prefix, remaining

    def _insert_into_trie(self, prompt: str) -> None:
        """Helper to tokenize and insert a prompt into the Radix Trie."""
        tokens = self._tokenize(prompt)
        self._insert_node(self.root, tokens)

    def _insert_node(self, parent: RadixTrieNode, tokens: list[str]) -> None:
        """Recursively insert tokens into Trie, performing splits if needed."""
        if not tokens:
            parent.is_leaf = True
            return

        for child in parent.children:
            common = self._get_common_prefix_length(child.path, tokens)
            if common > 0:
                if common < len(child.path):
                    # Split compressed node
                    split_child = RadixTrieNode(child.path[common:])
                    split_child.children = child.children
                    split_child.is_leaf = child.is_leaf

                    child.path = child.path[:common]
                    child.children = [split_child]
                    child.is_leaf = False

                self._insert_node(child, tokens[common:])
                return

        new_child = RadixTrieNode(tokens)
        new_child.is_leaf = True
        parent.children.append(new_child)

    def _rebuild_trie(self) -> None:
        """Rebuild trie from active prompts to perform LRU eviction cleanup."""
        self.root = RadixTrieNode([])
        for prompt in self.prompts:
            self._insert_into_trie(prompt)
