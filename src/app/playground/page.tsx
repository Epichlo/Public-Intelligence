"use client";

import { useRef, useState } from "react";
import { PageShell } from "@/components/page-shell";
import { ModelSelector } from "@/components/playground/model-selector";
import { LatencyMetricsCard, LatencyMetrics } from "@/components/playground/latency-metrics-card";
import { ErrorRateLimitBanner, PlaygroundError } from "@/components/playground/error-rate-limit-banner";
import { PlaygroundControls } from "@/components/playground/playground-controls";
import { ChatMessages, ChatMessage } from "@/components/playground/chat-messages";
import { PromptInput } from "@/components/playground/prompt-input";

function estimateTokens(text: string): number {
  if (!text) return 0;
  return Math.max(1, Math.floor(text.length / 4));
}

export default function PlaygroundPage() {
  const [selectedModel, setSelectedModel] = useState("llama3");
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [temperature, setTemperature] = useState(0.7);
  const [topP, setTopP] = useState(0.9);
  const [maxTokens, setMaxTokens] = useState(1024);
  const [systemPrompt, setSystemPrompt] = useState(
    "You are a helpful, respectful, and honest assistant participating in the Public Intelligence decentralized AI network."
  );
  const [jwtToken, setJwtToken] = useState("");
  const [isGenerating, setIsGenerating] = useState(false);
  const [errorState, setErrorState] = useState<PlaygroundError | null>(null);

  const [metrics, setMetrics] = useState<LatencyMetrics>({
    ttftMs: null,
    tokensPerSec: null,
    elapsedTimeSec: null,
    promptTokens: 0,
    completionTokens: 0,
  });

  const abortControllerRef = useRef<AbortController | null>(null);

  const handleStop = () => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      abortControllerRef.current = null;
    }
    setIsGenerating(false);
  };

  const handleSendPrompt = async (promptText: string) => {
    setErrorState(null);
    setIsGenerating(true);

    const userMessage: ChatMessage = {
      id: `usr-${Date.now()}`,
      role: "user",
      content: promptText,
      timestamp: new Date().toLocaleTimeString(),
    };

    const updatedMessages = [...messages, userMessage];
    setMessages(updatedMessages);

    // Prepare assistant placeholder message
    const assistantId = `ast-${Date.now()}`;
    const assistantPlaceholder: ChatMessage = {
      id: assistantId,
      role: "assistant",
      content: "",
      timestamp: new Date().toLocaleTimeString(),
    };

    setMessages([...updatedMessages, assistantPlaceholder]);

    // Build payload messages including system prompt if provided
    const payloadMessages = [];
    if (systemPrompt.trim()) {
      payloadMessages.push({ role: "system", content: systemPrompt.trim() });
    }
    for (const m of updatedMessages) {
      payloadMessages.push({ role: m.role, content: m.content });
    }

    const estimatedPromptTokens = estimateTokens(
      payloadMessages.map((m) => m.content).join(" ")
    );

    setMetrics({
      ttftMs: null,
      tokensPerSec: null,
      elapsedTimeSec: 0,
      promptTokens: estimatedPromptTokens,
      completionTokens: 0,
    });

    const startTime = Date.now();
    let firstTokenTime: number | null = null;
    let accumulatedText = "";
    let completionTokenCount = 0;

    const controller = new AbortController();
    abortControllerRef.current = controller;

    try {
      const headers: Record<string, string> = {
        "Content-Type": "application/json",
      };

      if (jwtToken.trim()) {
        headers["Authorization"] = jwtToken.startsWith("Bearer ")
          ? jwtToken.trim()
          : `Bearer ${jwtToken.trim()}`;
      }

      const response = await fetch("/api/chat/completions", {
        method: "POST",
        headers,
        body: JSON.stringify({
          model: selectedModel,
          messages: payloadMessages,
          stream: true,
          temperature,
          top_p: topP,
          max_tokens: maxTokens,
        }),
        signal: controller.signal,
      });

      if (!response.ok) {
        const errText = await response.text();
        let errMsg = errText;
        try {
          const parsed = JSON.parse(errText);
          errMsg = parsed.detail || parsed.error || errText;
        } catch {
          // ignore
        }

        setErrorState({
          statusCode: response.status,
          message: errMsg || `Request failed with status ${response.status}`,
        });

        // Remove empty assistant placeholder on error
        setMessages(updatedMessages);
        setIsGenerating(false);
        return;
      }

      if (!response.body) {
        throw new Error("No response body received from server");
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder("utf-8");
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() || "";

        for (const line of lines) {
          const trimmed = line.trim();
          if (!trimmed || !trimmed.startsWith("data: ")) continue;

          const dataStr = trimmed.slice(6).trim();
          if (dataStr === "[DONE]") break;

          try {
            const parsed = JSON.parse(dataStr);
            const deltaContent =
              parsed.choices?.[0]?.delta?.content ||
              parsed.choices?.[0]?.text ||
              "";

            if (deltaContent) {
              if (firstTokenTime === null) {
                firstTokenTime = Date.now();
                const ttft = firstTokenTime - startTime;
                setMetrics((prev) => ({ ...prev, ttftMs: ttft }));
              }

              accumulatedText += deltaContent;
              completionTokenCount += estimateTokens(deltaContent);

              const now = Date.now();
              const elapsedSec = Math.max(0.01, (now - startTime) / 1000);
              const speed = completionTokenCount / elapsedSec;

              setMetrics((prev) => ({
                ...prev,
                elapsedTimeSec: elapsedSec,
                tokensPerSec: speed,
                completionTokens: completionTokenCount,
              }));

              // Update assistant message text in real time
              setMessages((prevMsgs) =>
                prevMsgs.map((m) =>
                  m.id === assistantId ? { ...m, content: accumulatedText } : m
                )
              );
            }
          } catch {
            // Raw text delta fallback
            if (dataStr && dataStr !== "[DONE]") {
              accumulatedText += dataStr;
              setMessages((prevMsgs) =>
                prevMsgs.map((m) =>
                  m.id === assistantId ? { ...m, content: accumulatedText } : m
                )
              );
            }
          }
        }
      }

      const finalElapsed = (Date.now() - startTime) / 1000;
      setMetrics((prev) => ({
        ...prev,
        elapsedTimeSec: finalElapsed,
        tokensPerSec:
          completionTokenCount > 0 ? completionTokenCount / Math.max(0.01, finalElapsed) : 0,
      }));
    } catch (err: unknown) {
      if (err instanceof Error && err.name === "AbortError") {
        // User manually stopped streaming
      } else {
        setErrorState({
          statusCode: 500,
          message: err instanceof Error ? err.message : "Inference stream failed",
        });
      }
    } finally {
      setIsGenerating(false);
      abortControllerRef.current = null;
    }
  };

  const handleClearMessages = () => {
    setMessages([]);
    setErrorState(null);
    setMetrics({
      ttftMs: null,
      tokensPerSec: null,
      elapsedTimeSec: null,
      promptTokens: 0,
      completionTokens: 0,
    });
  };

  return (
    <PageShell>
      <div className="py-8 space-y-8">
        {/* Header Title */}
        <div>
          <h1 className="text-3xl font-bold tracking-tight text-foreground sm:text-4xl">
            Requester Chat Playground
          </h1>
          <p className="mt-2 text-base text-muted-foreground">
            Test prompt execution with real-time Server-Sent Events (SSE) token streaming via the OpenAI-compatible REST API Gateway (<code className="font-mono text-xs text-foreground">POST /v1/chat/completions</code>).
          </p>
        </div>

        {/* Error / Rate Limit Alert Banner */}
        <ErrorRateLimitBanner error={errorState} onDismiss={() => setErrorState(null)} />

        {/* Main Playground Split Grid */}
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
          {/* Left Column: Chat Area (2 cols) */}
          <div className="lg:col-span-2 space-y-4">
            <ChatMessages
              messages={messages}
              isStreaming={isGenerating}
              onClearMessages={handleClearMessages}
            />

            <PromptInput
              onSubmit={handleSendPrompt}
              onStop={handleStop}
              isGenerating={isGenerating}
            />
          </div>

          {/* Right Column: Model Selector, Telemetry Metrics & Parameter Drawer (1 col) */}
          <div className="space-y-5">
            {/* Model Selector Card */}
            <div className="rounded-xl border border-border/40 bg-card p-5 shadow-sm">
              <ModelSelector
                value={selectedModel}
                onChange={setSelectedModel}
                disabled={isGenerating}
              />
            </div>

            {/* Latency Metrics Card */}
            <LatencyMetricsCard metrics={metrics} isStreaming={isGenerating} />

            {/* Inference Parameters Controls */}
            <PlaygroundControls
              temperature={temperature}
              setTemperature={setTemperature}
              topP={topP}
              setTopP={setTopP}
              maxTokens={maxTokens}
              setMaxTokens={setMaxTokens}
              systemPrompt={systemPrompt}
              setSystemPrompt={setSystemPrompt}
              jwtToken={jwtToken}
              setJwtToken={setJwtToken}
              disabled={isGenerating}
            />
          </div>
        </div>
      </div>
    </PageShell>
  );
}
