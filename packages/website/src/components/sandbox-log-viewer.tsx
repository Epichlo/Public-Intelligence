"use client";

import { useEffect, useRef, useState } from "react";

interface LogEntry {
  id: string;
  timestamp: string;
  stream: "stdout" | "stderr" | "system";
  message: string;
  raw: string;
}

export function SandboxLogViewer() {
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [filterStream, setFilterStream] = useState<"all" | "stdout" | "stderr">("all");
  const [searchQuery, setSearchQuery] = useState("");
  const [autoScroll, setAutoScroll] = useState(true);
  const [streamState, setStreamState] = useState<"connecting" | "streaming" | "disconnected">("connecting");
  const logContainerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let eventSource: EventSource | null = null;

    try {
      eventSource = new EventSource("/api/sandbox/logs/stream");

      eventSource.onopen = () => {
        setStreamState("streaming");
      };

      eventSource.onmessage = (event) => {
        if (!event.data || event.data.startsWith(":")) return; // ignore keep-alives

        try {
          const parsed = JSON.parse(event.data);
          const entry = parsed.entry || {};
          const formattedLog = parsed.log || event.data;

          const newEntry: LogEntry = {
            id: `${Date.now()}-${Math.random().toString(36).substr(2, 9)}`,
            timestamp: entry.timestamp || new Date().toISOString(),
            stream: entry.stream === "stderr" ? "stderr" : "stdout",
            message: entry.message || formattedLog,
            raw: formattedLog,
          };

          setLogs((prev) => [...prev.slice(-499), newEntry]);
        } catch {
          // Plain text log fallback
          const newEntry: LogEntry = {
            id: `${Date.now()}-${Math.random().toString(36).substr(2, 9)}`,
            timestamp: new Date().toISOString(),
            stream: "stdout",
            message: event.data,
            raw: event.data,
          };
          setLogs((prev) => [...prev.slice(-499), newEntry]);
        }
      };

      eventSource.onerror = () => {
        setStreamState("disconnected");
      };
    } catch {
      // EventSource initialization failed asynchronously or on unsupported environment
    }

    return () => {
      if (eventSource) {
        eventSource.close();
      }
    };
  }, []);

  useEffect(() => {
    if (autoScroll && logContainerRef.current) {
      logContainerRef.current.scrollTop = logContainerRef.current.scrollHeight;
    }
  }, [logs, autoScroll]);

  const filteredLogs = logs.filter((log) => {
    if (filterStream !== "all" && log.stream !== filterStream) return false;
    if (searchQuery && !log.raw.toLowerCase().includes(searchQuery.toLowerCase())) return false;
    return true;
  });

  const clearLogs = () => {
    setLogs([]);
  };

  return (
    <div className="rounded-xl border border-border/40 bg-card p-5 shadow-sm space-y-4">
      {/* Header Bar */}
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-center gap-3">
          <h3 className="text-base font-semibold text-foreground">Docker Sandbox Runtime Logs</h3>
          <span
            className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-mono font-medium border ${
              streamState === "streaming"
                ? "bg-emerald-950/60 border-emerald-500/30 text-emerald-400"
                : streamState === "connecting"
                ? "bg-amber-950/60 border-amber-500/30 text-amber-400"
                : "bg-zinc-900 border-zinc-700 text-zinc-400"
            }`}
          >
            <span
              className={`h-1.5 w-1.5 rounded-full ${
                streamState === "streaming"
                  ? "bg-emerald-400 animate-ping"
                  : streamState === "connecting"
                  ? "bg-amber-400 animate-pulse"
                  : "bg-zinc-500"
              }`}
            />
            {streamState === "streaming"
              ? "LIVE STREAM"
              : streamState === "connecting"
              ? "CONNECTING"
              : "IDLE / DISCONNECTED"}
          </span>
        </div>

        {/* Action Controls */}
        <div className="flex flex-wrap items-center gap-2">
          {/* Stream Filter */}
          <select
            value={filterStream}
            onChange={(e) => setFilterStream(e.target.value as "all" | "stdout" | "stderr")}
            className="rounded-md border border-zinc-800 bg-zinc-950 px-2.5 py-1 text-xs text-foreground font-mono focus:outline-none focus:border-zinc-700"
          >
            <option value="all">All Streams</option>
            <option value="stdout">STDOUT</option>
            <option value="stderr">STDERR</option>
          </select>

          {/* Search Input */}
          <input
            type="text"
            placeholder="Search logs..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="w-36 sm:w-48 rounded-md border border-zinc-800 bg-zinc-950 px-2.5 py-1 text-xs text-foreground font-mono placeholder:text-zinc-600 focus:outline-none focus:border-zinc-700"
          />

          {/* Auto Scroll Toggle */}
          <button
            onClick={() => setAutoScroll(!autoScroll)}
            className={`rounded-md border px-2.5 py-1 text-xs font-mono font-medium transition-colors ${
              autoScroll
                ? "bg-emerald-950/40 border-emerald-500/30 text-emerald-400"
                : "bg-zinc-900 border-zinc-800 text-zinc-400 hover:text-foreground"
            }`}
          >
            {autoScroll ? "Auto-scroll: ON" : "Auto-scroll: OFF"}
          </button>

          {/* Clear Button */}
          <button
            onClick={clearLogs}
            className="rounded-md border border-zinc-800 bg-zinc-900 px-2.5 py-1 text-xs font-mono text-zinc-400 hover:text-foreground hover:bg-zinc-800 transition-colors"
          >
            Clear
          </button>
        </div>
      </div>

      {/* Terminal View Container */}
      <div
        ref={logContainerRef}
        className="h-80 w-full overflow-y-auto rounded-lg border border-zinc-800 bg-zinc-950 p-4 font-mono text-xs leading-relaxed text-zinc-300 shadow-inner"
      >
        {filteredLogs.length === 0 ? (
          <div className="flex h-full items-center justify-center text-zinc-600 italic">
            {logs.length === 0
              ? "Waiting for sandbox container execution events..."
              : "No log entries match the active search filter."}
          </div>
        ) : (
          filteredLogs.map((log) => (
            <div key={log.id} className="hover:bg-zinc-900/50 rounded px-1 py-0.5 flex gap-2">
              <span className="text-zinc-500 select-none font-sans shrink-0">
                {new Date(log.timestamp).toLocaleTimeString()}
              </span>
              <span
                className={`font-semibold shrink-0 select-none ${
                  log.stream === "stderr" ? "text-red-400" : "text-emerald-400"
                }`}
              >
                [{log.stream.toUpperCase()}]
              </span>
              <span className="break-all whitespace-pre-wrap">{log.message}</span>
            </div>
          ))
        )}
      </div>

      {/* Sandbox Isolation Constraints Specs Footer */}
      <div className="flex flex-wrap items-center justify-between text-[11px] font-mono text-muted-foreground pt-1 border-t border-border/20">
        <span>Docker Worktree Isolation: Active</span>
        <span>Memory Limit: 512 MB</span>
        <span>Timeout: 60s max execution</span>
        <span>Privileges: Non-Root User</span>
      </div>
    </div>
  );
}
