/**
 * Parsing the gateway's SSE stream (ROADMAP 4.1).
 *
 * This logic lived inline inside `playground/page.tsx`, tangled with React state
 * setters, which made it untestable — and it is the one piece of the website where
 * being subtly wrong is invisible: a dropped delta looks like the model simply not
 * saying that word.
 *
 * Extracted as pure functions so the edge cases below can be asserted directly. The
 * page keeps the reader loop and the state updates; this owns the wire format.
 */

/** One line of an SSE stream, already split. */
export type SseLine = string;

/**
 * Split a buffer into complete lines, returning the trailing partial separately.
 *
 * The partial matters. A chunk boundary lands in the middle of a `data:` line
 * routinely — a token is a few bytes and TCP does not respect JSON — and treating
 * the tail as a complete line drops it, or worse, parses half a JSON object and
 * silently yields nothing.
 */
export function splitSseBuffer(buffer: string): { lines: SseLine[]; rest: string } {
  const parts = buffer.split("\n");
  const rest = parts.pop() ?? "";
  return { lines: parts, rest };
}

/** `[DONE]` terminates the stream. Anything after it is not content. */
export const SSE_DONE = "[DONE]";

export interface SseEvent {
  /** Text to append, if this line carried any. */
  delta: string;
  /** True when the stream said it is finished. */
  done: boolean;
}

/**
 * Interpret one SSE line.
 *
 * Returns `delta: ""` for anything that is not content — comments, blank lines,
 * keep-alives, and malformed JSON. **Malformed JSON is skipped rather than thrown**:
 * a stream that dies mid-object should lose that fragment, not the whole
 * conversation the user has already been shown.
 */
export function parseSseLine(line: SseLine): SseEvent {
  const trimmed = line.trim();
  if (!trimmed || !trimmed.startsWith("data:")) return { delta: "", done: false };

  // `data:foo` is as valid as `data: foo` per the SSE spec; slicing a fixed 6
  // characters assumed the space and silently ate the first character without it.
  const dataStr = trimmed.slice(5).trim();
  if (dataStr === SSE_DONE) return { delta: "", done: true };

  try {
    const parsed: unknown = JSON.parse(dataStr);
    return { delta: extractDelta(parsed), done: false };
  } catch {
    return { delta: "", done: false };
  }
}

/**
 * Pull the text out of one chat-completion chunk.
 *
 * Reads `choices[0].delta.content` then `choices[0].text`. Narrowed rather than
 * indexed through `any`, so a gateway response-shape change is a type error here
 * instead of an empty string in the UI.
 *
 * **`??`, not `||`.** The old code used `||`, which treats an empty-string delta as
 * absent — correct by accident today, and wrong the moment a legitimate `""` needs
 * distinguishing from a missing field.
 */
export function extractDelta(chunk: unknown): string {
  if (typeof chunk !== "object" || chunk === null) return "";
  const choices = (chunk as { choices?: unknown }).choices;
  if (!Array.isArray(choices) || choices.length === 0) return "";

  const first = choices[0] as { delta?: { content?: unknown }; text?: unknown };
  const content = first?.delta?.content;
  if (typeof content === "string") return content;
  if (typeof first?.text === "string") return first.text;
  return "";
}

/** Tokens, estimated the same way the gateway estimates them. */
export function estimateTokens(text: string): number {
  if (!text) return 0;
  return Math.max(1, Math.floor(text.length / 4));
}
