"use client";

import Script from "next/script";
import { useEffect } from "react";

declare global {
  interface Window {
    twttr?: {
      widgets?: {
        load?: (element?: HTMLElement | null) => void;
      };
    };
  }
}

export function TwitterTimeline() {
  useEffect(() => {
    if (typeof window !== "undefined" && window.twttr?.widgets?.load) {
      window.twttr.widgets.load();
    }
  }, []);

  return (
    <div className="w-full flex flex-col items-center justify-center space-y-4">
      <div className="w-full flex justify-center min-h-[600px]">
        <a
          className="twitter-timeline font-medium text-foreground underline underline-offset-4 hover:text-foreground/80"
          data-theme="dark"
          data-height="600"
          data-chrome="noheader nofooter noborders transparent"
          href="https://x.com/PublicIntelTech"
          target="_blank"
          rel="noreferrer"
        >
          Tweets by @PublicIntelTech
        </a>
      </div>

      <div className="pt-2 text-center">
        <a
          href="https://x.com/PublicIntelTech"
          target="_blank"
          rel="noreferrer"
          className="inline-flex items-center gap-2 px-4 py-2 text-xs font-medium text-foreground bg-muted/40 hover:bg-muted/80 rounded-md border border-border/60 transition-colors"
        >
          <svg className="w-4 h-4 fill-current" viewBox="0 0 24 24" aria-hidden="true">
            <path d="M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-5.214-6.817L4.99 21.75H1.68l7.73-8.835L1.254 2.25H8.08l4.713 6.231zm-1.161 17.52h1.833L7.084 4.126H5.117z" />
          </svg>
          Follow @PublicIntelTech on X
        </a>
      </div>

      <Script
        src="https://platform.twitter.com/widgets.js"
        strategy="afterInteractive"
        onLoad={() => {
          if (typeof window !== "undefined" && window.twttr?.widgets?.load) {
            window.twttr.widgets.load();
          }
        }}
      />
    </div>
  );
}
