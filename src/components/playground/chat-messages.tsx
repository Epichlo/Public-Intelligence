"use client";

import { useEffect, useRef } from "react";

export interface ChatMessage {
  id: string;
  role: "system" | "user" | "assistant";
  content: string;
  timestamp?: string;
}

interface ChatMessagesProps {
  messages: ChatMessage[];
  isStreaming?: boolean;
  onClearMessages?: () => void;
}

export function ChatMessages({ messages, isStreaming, onClearMessages }: ChatMessagesProps) {
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, isStreaming]);

  const copyToClipboard = (text: string) => {
    navigator.clipboard.writeText(text);
  };

  return (
    <div className="flex flex-col h-[520px] rounded-xl border border-border/40 bg-card shadow-sm">
      {/* Header bar */}
      <div className="flex items-center justify-between border-b border-border/40 px-5 py-3">
        <div className="flex items-center gap-2">
          <span className="h-2.5 w-2.5 rounded-full bg-emerald-400" />
          <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
            Conversation History
          </h3>
        </div>

        {onClearMessages && messages.length > 0 && (
          <button
            onClick={onClearMessages}
            disabled={isStreaming}
            className="text-xs font-mono text-zinc-400 hover:text-foreground disabled:opacity-40 transition-colors"
          >
            Clear Chat
          </button>
        )}
      </div>

      {/* Messages Thread Container */}
      <div className="flex-1 overflow-y-auto p-5 space-y-4 font-sans text-sm leading-relaxed">
        {messages.length === 0 ? (
          <div className="flex h-full flex-col items-center justify-center text-center text-muted-foreground p-6">
            <div className="rounded-full bg-zinc-900/80 p-3 mb-3 border border-border/40">
              <svg className="w-6 h-6 text-[#D9F99D]" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" />
              </svg>
            </div>
            <p className="font-medium text-foreground">Interactive Prompt Playground Ready</p>
            <p className="text-xs mt-1 max-w-sm">
              Type a prompt below to initiate real-time Server-Sent Events (SSE) token streaming via the OpenAI-compatible REST API Gateway.
            </p>
          </div>
        ) : (
          messages.map((msg, idx) => {
            const isUser = msg.role === "user";
            const isSystem = msg.role === "system";
            const isLastAssistant = !isUser && !isSystem && idx === messages.length - 1;

            return (
              <div
                key={msg.id}
                className={`flex flex-col space-y-1 ${
                  isUser ? "items-end" : "items-start"
                }`}
              >
                {/* Role Header */}
                <div className="flex items-center gap-2 px-1 text-[11px] font-mono text-muted-foreground">
                  <span>
                    {isUser ? "User Prompt" : isSystem ? "System Instruction" : "Assistant (LLM)"}
                  </span>
                  {msg.timestamp && <span>• {msg.timestamp}</span>}
                </div>

                {/* Message Content Bubble */}
                <div
                  className={`group relative max-w-[85%] rounded-2xl px-4 py-3 text-sm leading-relaxed ${
                    isUser
                      ? "bg-[#D9F99D] text-zinc-950 rounded-br-none font-medium"
                      : isSystem
                      ? "bg-zinc-900 border border-zinc-800 text-zinc-400 italic rounded-md w-full"
                      : "bg-zinc-900/90 border border-zinc-800 text-foreground rounded-bl-none font-sans"
                  }`}
                >
                  <p className="whitespace-pre-wrap break-words">
                    {msg.content}
                    {isLastAssistant && isStreaming && (
                      <span className="inline-block ml-1 w-2 h-4 bg-emerald-400 animate-pulse align-middle" />
                    )}
                  </p>

                  {/* Copy Button */}
                  {!isSystem && (
                    <button
                      onClick={() => copyToClipboard(msg.content)}
                      className={`absolute right-2 top-2 opacity-0 group-hover:opacity-100 transition-opacity rounded p-1 text-xs ${
                        isUser ? "text-zinc-800 hover:bg-black/10" : "text-zinc-400 hover:bg-zinc-800"
                      }`}
                      title="Copy content"
                    >
                      📋
                    </button>
                  )}
                </div>
              </div>
            );
          })
        )}
        <div ref={bottomRef} />
      </div>
    </div>
  );
}
