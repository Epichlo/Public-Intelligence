"""Local boundary isolation engine for client/edge split-inference in Scheduler."""

import math
import random
import struct
from typing import Any

from scheduler.models.pipeline import TensorPayload


class LocalBoundaryEngine:
    """Executes Layer 0 (Embedding) and Layer N (LM Head) locally on client.

    Ensures raw prompt text and token IDs remain strictly inside local client memory.
    """

    def __init__(
        self,
        model_id: str = "default",
        vocab_size: int = 32000,
        hidden_dim: int = 4096,
        seed: int = 42,
    ) -> None:
        """Initialize local boundary weights and vocabulary tables.

        Args:
            model_id: Target model identifier.
            vocab_size: Size of local vocabulary.
            hidden_dim: Model hidden vector dimension (d_model).
            seed: Random seed for deterministic weight initialization.
        """
        self.model_id = model_id
        self.vocab_size = vocab_size
        self.hidden_dim = hidden_dim
        self.seed = seed

        # Local vocabulary mapping tables
        self._token_to_id: dict[str, int] = {}
        self._id_to_token: dict[int, str] = {}
        self._init_vocabulary()

        # Local weight matrices for Layer 0 (Embedding E) and Layer N (LM Head W_lm)
        self.embedding_matrix: list[list[float]] = []
        self.lm_head_matrix: list[list[float]] = []
        self._init_local_weights()

        # Local execution history tracking (remains local to client memory)
        self._local_token_history: list[int] = []

    def _init_vocabulary(self) -> None:
        """Initialize local vocabulary tables for tokenization and detokenization."""
        special_tokens = ["<pad>", "<bos>", "<eos>", "<unk>"]
        for idx, tok in enumerate(special_tokens):
            self._token_to_id[tok] = idx
            self._id_to_token[idx] = tok

        words = [
            "the",
            "be",
            "to",
            "of",
            "and",
            "a",
            "in",
            "that",
            "have",
            "i",
            "it",
            "for",
            "not",
            "on",
            "with",
            "he",
            "as",
            "you",
            "do",
            "at",
            "this",
            "but",
            "his",
            "by",
            "from",
            "they",
            "we",
            "say",
            "her",
            "she",
            "or",
            "an",
            "will",
            "my",
            "one",
            "all",
            "would",
            "there",
            "their",
            "what",
            "so",
            "up",
            "out",
            "if",
            "about",
            "who",
            "get",
            "which",
            "go",
            "me",
            "when",
            "make",
            "can",
            "like",
            "time",
            "no",
            "just",
            "him",
            "know",
            "take",
            "people",
            "into",
            "year",
            "your",
            "good",
            "some",
            "could",
            "them",
            "see",
            "other",
            "than",
            "then",
            "now",
            "look",
            "only",
            "come",
            "its",
            "over",
            "think",
            "also",
            "back",
            "after",
            "use",
            "two",
            "how",
            "our",
            "work",
            "first",
            "well",
            "way",
            "even",
            "new",
            "want",
            "because",
            "any",
            "these",
            "give",
            "day",
            "most",
            "us",
            "hello",
            "world",
            "public",
            "intelligence",
            "ai",
            "node",
            "split",
            "inference",
            "privacy",
            "boundary",
            "secure",
            "local",
            "layer",
            "activation",
            "tensor",
            "payload",
        ]
        curr_id = len(special_tokens)
        for w in words:
            if curr_id >= self.vocab_size:
                break
            if w not in self._token_to_id:
                self._token_to_id[w] = curr_id
                self._id_to_token[curr_id] = w
                curr_id += 1

    def _init_local_weights(self) -> None:
        """Initialize Layer 0 Embedding matrix E and Layer N LM Head matrix W_lm."""
        rng = random.Random(self.seed)
        scale = 1.0 / math.sqrt(self.hidden_dim)
        self.embedding_matrix = [
            [rng.gauss(0.0, scale) for _ in range(self.hidden_dim)] for _ in range(self.vocab_size)
        ]
        self.lm_head_matrix = [
            [rng.gauss(0.0, scale) for _ in range(self.hidden_dim)] for _ in range(self.vocab_size)
        ]

    def _tokenize(self, prompt: str) -> list[int]:
        """Tokenize input text prompt into token IDs deterministically."""
        if not prompt.strip():
            return [self._token_to_id.get("<bos>", 1)]

        raw_tokens = prompt.lower().strip().split()
        token_ids: list[int] = []
        for token_str in raw_tokens:
            cleaned = "".join(c for c in token_str if c.isalnum() or c in ("_", "-"))
            if not cleaned:
                continue
            if cleaned in self._token_to_id:
                token_ids.append(self._token_to_id[cleaned])
            else:
                h_val = abs(hash(cleaned)) % (self.vocab_size - 100) + 100
                token_ids.append(h_val)

        if not token_ids:
            token_ids = [self._token_to_id.get("<bos>", 1)]

        return token_ids

    def embed_prompt(
        self, prompt: str, task_id: str = "", target_stage_index: int = 1
    ) -> TensorPayload:
        """Tokenize text prompt and compute Layer 0 hidden activation vectors H_0.

        Guarantees that raw prompt tokens remain inside local memory.

        Args:
            prompt: Text prompt string.
            task_id: Unique task execution identifier.
            target_stage_index: Pipeline stage index receiving H_0 (default 1).

        Returns:
            TensorPayload containing H_0 activations with is_split_inference=True.
        """
        token_ids = self._tokenize(prompt)
        self._local_token_history = list(token_ids)

        seq_len = len(token_ids)
        h0_flat: list[float] = []
        for tid in token_ids:
            emb_vec = self.embedding_matrix[tid % self.vocab_size]
            h0_flat.extend(emb_vec)

        return TensorPayload(
            task_id=task_id,
            stage_index=0,
            target_stage_index=target_stage_index,
            is_split_inference=True,
            tensor_type="activation",
            data=h0_flat,
            shape=[1, seq_len, self.hidden_dim],
            dtype="float32",
            sequence_id=0,
        )

    def generate_speculative_candidates(self, prompt: str, k: int = 5, task_id: str = "") -> Any:
        """Generate candidate token block (K=5) locally on the edge boundary engine.

        Args:
            prompt: Text prompt string.
            k: Speculative candidate block size (default 5).
            task_id: Unique task identifier.

        Returns:
            DraftBlockPayload containing candidate tokens and batched activations.
        """
        from scheduler.models.pipeline import DraftBlockPayload

        token_ids = self._tokenize(prompt)
        candidate_tokens: list[int] = []
        curr_ids = list(token_ids)

        for _ in range(k):
            next_id = (curr_ids[-1] * 7 + 13) % self.vocab_size
            candidate_tokens.append(next_id)
            curr_ids.append(next_id)

        all_ids = token_ids + candidate_tokens
        seq_len = len(all_ids)
        h_flat: list[float] = []
        for tid in all_ids:
            h_flat.extend(self.embedding_matrix[tid % self.vocab_size])

        activation_payload = TensorPayload(
            task_id=task_id,
            stage_index=0,
            target_stage_index=1,
            is_split_inference=True,
            tensor_type="activation",
            data=h_flat,
            shape=[1, seq_len, self.hidden_dim],
            dtype="float32",
            is_speculative=True,
            speculative_block_size=k,
        )

        return DraftBlockPayload(
            task_id=task_id,
            sequence_start_id=0,
            speculative_k=k,
            candidate_tokens=candidate_tokens,
            draft_logprobs=[-0.5] * k,
            activation_payload=activation_payload,
        )

    def unembed_logits(
        self, activation_payload: TensorPayload, temperature: float = 1.0
    ) -> tuple[int, str]:
        """Apply Layer N LM Head projection W_lm and sample next token locally.

        Args:
            activation_payload: TensorPayload containing activations H_(N-1).
            temperature: Sampling temperature (default 1.0).

        Returns:
            Tuple of (token_id, decoded_token_text).
        """
        if not isinstance(activation_payload, TensorPayload):
            raise TypeError("activation_payload must be an instance of TensorPayload")

        activation_payload.validate_split_activation_boundary()

        data = activation_payload.data
        h_last: list[float] = []

        if isinstance(data, bytes):
            if len(data) == 0 or len(data) % 4 != 0:
                raise ValueError("Activation payload bytes length is invalid or empty")
            num_floats = len(data) // 4
            fmt = f">{num_floats}f" if data.startswith(b"PITP") else f"{num_floats}f"
            try:
                unpacked = list(struct.unpack(fmt, data))
            except struct.error as err:
                raise ValueError(f"Failed to unpack activation payload bytes: {err}") from err
            h_last = unpacked[-self.hidden_dim :] if len(unpacked) >= self.hidden_dim else unpacked
        elif isinstance(data, list):
            if not data:
                raise ValueError("Activation payload data list is empty")
            if data and isinstance(data[0], list):
                last_elem: Any = data[-1]
                while isinstance(last_elem, list) and last_elem and isinstance(last_elem[0], list):
                    last_elem = last_elem[-1]
                h_last = [float(x) for x in last_elem]
            else:
                flat_data = [float(x) for x in data]
                h_last = (
                    flat_data[-self.hidden_dim :]
                    if len(flat_data) >= self.hidden_dim
                    else flat_data
                )

        if not h_last:
            raise ValueError("Activation payload contains no float vector data")

        if len(h_last) < self.hidden_dim:
            h_last = h_last + [0.0] * (self.hidden_dim - len(h_last))
        elif len(h_last) > self.hidden_dim:
            h_last = h_last[: self.hidden_dim]

        logits: list[float] = []
        for tid in range(self.vocab_size):
            weight_vec = self.lm_head_matrix[tid]
            dot_product = sum(w * h for w, h in zip(weight_vec, h_last, strict=False))
            logits.append(dot_product)

        if temperature <= 0.01:
            token_id = max(range(self.vocab_size), key=lambda i: logits[i])
        else:
            scaled_logits = [val / temperature for val in logits]
            max_l = max(scaled_logits)
            exp_logits = [math.exp(val - max_l) for val in scaled_logits]
            sum_exp = sum(exp_logits)
            probs = [e / sum_exp for e in exp_logits]

            sampled_indices = random.choices(range(self.vocab_size), weights=probs, k=1)
            token_id = sampled_indices[0]

        token_text = self._id_to_token.get(token_id, f"token_{token_id}")
        self._local_token_history.append(token_id)

        return token_id, token_text
