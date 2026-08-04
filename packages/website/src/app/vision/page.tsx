import { PageShell } from "@/components/page-shell";
import { PageHeader } from "@/components/page-header";

export default function VisionPage() {
  return (
    <PageShell>
      <article className="max-w-4xl mx-auto space-y-24">
        <PageHeader
          kicker="Vision & Intent"
          title="Vision"
          description="Public Intelligence is an open engineering initiative building globally distributed, community-owned AI infrastructure."
        />

        {/* MISSION & DEFINITION */}
        <section aria-labelledby="what-is-heading" className="space-y-6 pt-6 border-t border-border/40">
          <div className="grid gap-6 md:grid-cols-3">
            <div className="md:col-span-1">
              <span className="text-xs font-mono uppercase tracking-wider text-[#D9F99D]">01 // MISSION</span>
              <h2 id="what-is-heading" className="text-lg font-semibold text-foreground mt-2">
                What Public Intelligence Is
              </h2>
            </div>
            <div className="md:col-span-2 space-y-4">
              <p className="text-sm leading-relaxed text-muted-foreground sm:text-base">
                Public Intelligence exists to help individuals and organizations
                contribute compute resources to a shared network for hosting,
                serving, and improving frontier open-source AI models.
              </p>
              <p className="text-sm leading-relaxed text-muted-foreground sm:text-base">
                The project is open source, modular, and designed for long-term sustainability, functioning as public infrastructure for AI.
              </p>
            </div>
          </div>
        </section>

        {/* WHY IT EXISTS */}
        <section aria-labelledby="why-heading" className="space-y-6 pt-6 border-t border-border/40">
          <div className="grid gap-6 md:grid-cols-3">
            <div className="md:col-span-1">
              <span className="text-xs font-mono uppercase tracking-wider text-[#D9F99D]">02 // RATIONALE</span>
              <h2 id="why-heading" className="text-lg font-semibold text-foreground mt-2">
                Why It Exists
              </h2>
            </div>
            <div className="md:col-span-2 space-y-4">
              <p className="text-sm leading-relaxed text-muted-foreground sm:text-base">
                Frontier AI currently depends on large amounts of infrastructure
                controlled by a small number of organizations. Open-source models
                are becoming more capable, but serving them at scale remains
                expensive and operationally complex.
              </p>
              <p className="text-sm leading-relaxed text-muted-foreground sm:text-base">
                Public Intelligence is researching and building a distributed alternative that lowers the barrier to hosting powerful systems, keeping computational access open and decentralized.
              </p>
            </div>
          </div>
        </section>

        {/* LONG TERM DIRECTION */}
        <section aria-labelledby="direction-heading" className="space-y-6 pt-6 border-t border-border/40">
          <div className="grid gap-6 md:grid-cols-3">
            <div className="md:col-span-1">
              <span className="text-xs font-mono uppercase tracking-wider text-[#D9F99D]">03 // DIRECTION</span>
              <h2 id="direction-heading" className="text-lg font-semibold text-foreground mt-2">
                Long-Term Direction
              </h2>
            </div>
            <div className="md:col-span-2 space-y-4">
              <p className="text-sm leading-relaxed text-muted-foreground sm:text-base">
                The long-term goal is public infrastructure for AI: a network of
                independently operated systems that can collectively function as one
                global AI platform.
              </p>
              <p className="text-sm leading-relaxed text-muted-foreground sm:text-base">
                No single repository represents the full project. The Website, Scheduler,
                Node runtime, communication protocols, SDKs, monitoring, and developer
                tools are expected to evolve as focused, replaceable components of a larger ecosystem.
              </p>
            </div>
          </div>
        </section>

        {/* ENGINEERING VALUES */}
        <section aria-labelledby="values-heading" className="space-y-8 pt-6 border-t border-border/40">
          <div className="space-y-2">
            <span className="text-xs font-mono uppercase tracking-wider text-[#D9F99D]">04 // METHODOLOGY</span>
            <h2 id="values-heading" className="text-2xl font-semibold tracking-tight text-foreground">
              Engineering Philosophy
            </h2>
            <p className="max-w-2xl text-sm leading-relaxed text-muted-foreground">
              We prioritize durable, long-term decisions over rapid short-term development. Our values guide every design choices.
            </p>
          </div>

          <div className="grid gap-x-12 gap-y-10 md:grid-cols-2 pt-4">
            <div className="space-y-3">
              <div className="flex items-center gap-3 text-foreground">
                <svg className="w-5 h-5 text-[#D9F99D]" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="1.5" aria-hidden="true">
                  <path d="M12 8V12L15 15" stroke="currentColor" />
                  <circle cx="12" cy="12" r="9" stroke="currentColor" strokeOpacity="0.3" />
                </svg>
                <h3 className="text-base font-semibold">Long-Term Thinking</h3>
              </div>
              <p className="text-sm leading-relaxed text-muted-foreground">
                Every design choice optimizes for maintainability and operational resilience over years rather than immediate release speeds.
              </p>
            </div>

            <div className="space-y-3">
              <div className="flex items-center gap-3 text-foreground">
                <svg className="w-5 h-5 text-[#D9F99D]" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="1.5" aria-hidden="true">
                  <circle cx="12" cy="12" r="5" stroke="currentColor" />
                  <path d="M12 2v5" stroke="currentColor" strokeOpacity="0.4" />
                  <path d="M12 17v5" stroke="currentColor" strokeOpacity="0.4" />
                  <path d="M2 12h5" stroke="currentColor" strokeOpacity="0.4" />
                  <path d="M17 12h5" stroke="currentColor" strokeOpacity="0.4" />
                </svg>
                <h3 className="text-base font-semibold">Simplicity & Modularity</h3>
              </div>
              <p className="text-sm leading-relaxed text-muted-foreground">
                Decoupled, loosely coupled architectures. We design components that remain independent, testable, and replaceable.
              </p>
            </div>

            <div className="space-y-3">
              <div className="flex items-center gap-3 text-foreground">
                <svg className="w-5 h-5 text-[#D9F99D]" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="1.5" aria-hidden="true">
                  <path d="M9 12h6" stroke="currentColor" />
                  <path d="M12 9v6" stroke="currentColor" />
                  <rect x="4" y="4" width="16" height="16" rx="2" stroke="currentColor" strokeOpacity="0.4" />
                </svg>
                <h3 className="text-base font-semibold">Documentation First</h3>
              </div>
              <p className="text-sm leading-relaxed text-muted-foreground">
                Specs and reasoning are drafted and peer-reviewed before any implementation work, serving as a unified system spec.
              </p>
            </div>

            <div className="space-y-3">
              <div className="flex items-center gap-3 text-foreground">
                <svg className="w-5 h-5 text-[#D9F99D]" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="1.5" aria-hidden="true">
                  <circle cx="12" cy="12" r="9" stroke="currentColor" strokeOpacity="0.3" />
                  <path d="M12 7v10" stroke="currentColor" />
                  <path d="M7 12h10" stroke="currentColor" />
                </svg>
                <h3 className="text-base font-semibold">Open Engineering</h3>
              </div>
              <p className="text-sm leading-relaxed text-muted-foreground">
                All development happens in the public sphere, treating future contributors and network operators as first-class stakeholders.
              </p>
            </div>
          </div>
        </section>
      </article>
    </PageShell>
  );
}
