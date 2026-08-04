import * as React from "react";

type PageHeaderProps = {
  kicker: string;
  title: string;
  description?: string;
};

export function PageHeader({ kicker, title, description }: PageHeaderProps) {
  return (
    <header className="space-y-6">
      <span className="text-xs font-mono uppercase tracking-wider text-[#D9F99D]">
        {kicker}
      </span>
      <div className="space-y-4">
        <h1 className="text-4xl font-semibold tracking-tight text-foreground sm:text-5xl sm:leading-[1.15]">
          {title}
        </h1>
        {description && (
          <p className="max-w-3xl text-xl leading-relaxed text-muted-foreground sm:text-2xl font-light">
            {description}
          </p>
        )}
      </div>
    </header>
  );
}
