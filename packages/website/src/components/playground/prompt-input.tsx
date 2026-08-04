"use client";

import { useState } from "react";

interface PromptInputProps {
  onSubmit: (prompt: string) => void;
  onStop?: () => void;
  isGenerating?: boolean;
  disabled?: boolean;
}

export function PromptInput({ onSubmit, onStop, isGenerating, disabled }: PromptInputProps) {
  const [prompt, setPrompt] = useState("");

  const handleSubmit = (e?: React.FormEvent) => {
    if (e) e.preventDefault();
    if (!prompt.trim() || isGenerating || disabled) return;
    onSubmit(prompt.trim());
    setPrompt("");
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
    }
  };

  return (
    <form onSubmit={handleSubmit} className="rounded-xl border border-border/40 bg-card p-3 shadow-sm space-y-3">
      <div className="relative">
        <textarea
          rows={3}
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          onKeyDown={handleKeyDown}
          disabled={disabled || isGenerating}
          placeholder="Enter prompt (Press Enter to submit, Shift+Enter for newline)..."
          className="w-full rounded-lg border border-border/60 bg-zinc-950 p-3 text-sm text-foreground placeholder:text-zinc-600 focus:border-emerald-500 focus:outline-none disabled:opacity-50 font-sans resize-none"
        />
      </div>

      <div className="flex items-center justify-between">
        <span className="text-[11px] text-muted-foreground font-mono">
          Model Inference Gateway • SSE Streaming Enabled
        </span>

        {isGenerating ? (
          <button
            type="button"
            onClick={onStop}
            className="inline-flex items-center gap-2 rounded-lg border border-red-500/30 bg-red-950/40 px-4 py-2 text-xs font-semibold text-red-400 hover:bg-red-950/70 transition-colors"
          >
            <span className="h-2 w-2 rounded-sm bg-red-400" />
            Stop Generation
          </button>
        ) : (
          <button
            type="submit"
            disabled={!prompt.trim() || disabled}
            className="inline-flex items-center gap-2 rounded-lg bg-[#D9F99D] px-5 py-2 text-xs font-bold text-zinc-950 hover:bg-[#bef264] transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
          >
            <span>Submit Prompt</span>
            <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2.5" d="M14 5l7 7m0 0l-7 7m7-7H3" />
            </svg>
          </button>
        )}
      </div>
    </form>
  );
}
