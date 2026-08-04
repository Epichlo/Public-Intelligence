import Link from "next/link";
import { PageShell } from "@/components/page-shell";
import { Logo } from "@/components/logo";
import { SystemDiagram } from "@/components/system-diagram";
import { TwitterTimeline } from "@/components/twitter-timeline";

export default function Home() {
  return (
    <PageShell>
      <div className="max-w-4xl mx-auto space-y-24">
        {/* HERO SECTION */}
        <section className="space-y-6">
          <Logo className="w-8 h-8 text-foreground/80" />
          <div className="space-y-4">
            <h1 className="text-4xl font-semibold tracking-tight text-foreground sm:text-5xl md:text-6xl sm:leading-[1.15] max-w-3xl">
              Public Intelligence
            </h1>
            <p className="max-w-2xl text-xl leading-normal text-muted-foreground sm:text-2xl font-light">
              Building a globally distributed, community-owned AI infrastructure.
            </p>
          </div>
          <p className="max-w-2xl text-base leading-relaxed text-muted-foreground/80">
            Public Intelligence is an open engineering initiative researching
            and building decentralized AI infrastructure that enables
            communities to collectively host frontier open-source AI models.
          </p>
          
          <div className="flex flex-wrap items-center gap-4 pt-2">
            <Link
              href="/architecture"
              className="inline-flex h-9 items-center justify-center rounded-md bg-foreground px-4 text-xs font-medium text-background transition-colors hover:bg-foreground/90"
            >
              Explore the Architecture
            </Link>
            <Link
              href="/status"
              className="inline-flex h-9 items-center justify-center border border-[#86EFAC]/50 px-4 text-xs font-medium text-[#86EFAC] transition-colors hover:border-[#86EFAC]"
            >
              Check System Status
            </Link>
            <Link
              href="https://x.com/PublicIntelTech"
              target="_blank"
              rel="noreferrer"
              className="inline-flex h-9 items-center justify-center rounded-md border border-border/60 bg-transparent px-4 text-xs font-medium text-foreground transition-colors hover:bg-muted/30"
            >
              X (Twitter)
            </Link>
            <Link
              href="https://github.com/Public-Intelligence-Revolution"
              target="_blank"
              rel="noreferrer"
              className="inline-flex h-9 items-center justify-center rounded-md border border-border/60 bg-transparent px-4 text-xs font-medium text-foreground transition-colors hover:bg-muted/30"
            >
              GitHub
            </Link>
          </div>
        </section>

        {/* MEMORABLE VISUAL MOMENT: SYSTEM DIAGRAM */}
        <section aria-labelledby="topology-heading" className="space-y-6 pt-6 border-t border-border/40">
          <div className="space-y-2">
            <span className="text-xs font-mono uppercase tracking-wider text-[#D9F99D]">01 // ARCHITECTURAL TOPOLOGY</span>
            <h2 id="topology-heading" className="text-2xl font-semibold tracking-tight text-foreground">
              Distributed Inference Coordination
            </h2>
            <p className="max-w-2xl text-sm leading-relaxed text-muted-foreground">
              A conceptual schematic showing how workloads are routed from client interfaces to geographic nodes. The active path highlights the coordinated execution of an inference query.
            </p>
          </div>
          <SystemDiagram />
        </section>

        {/* CORE PRINCIPLES */}
        <section aria-labelledby="principles-heading" className="space-y-8 pt-6 border-t border-border/40">
          <div className="space-y-2">
            <span className="text-xs font-mono uppercase tracking-wider text-[#D9F99D]">02 // FOUNDATIONAL PRINCIPLES</span>
            <h2 id="principles-heading" className="text-2xl font-semibold tracking-tight text-foreground">
              System Values
            </h2>
            <p className="max-w-2xl text-sm leading-relaxed text-muted-foreground">
              Architectural decisions are guided by long-term durability and decentralized accessibility.
            </p>
          </div>
          
          <div className="grid gap-x-12 gap-y-10 md:grid-cols-2 pt-4">
            <div className="space-y-3">
              <div className="flex items-center gap-3 text-foreground">
                <span className="text-xs font-mono text-[#D9F99D]">01</span>
                <h3 className="text-base font-semibold">Community Owned</h3>
              </div>
              <p className="text-sm leading-relaxed text-muted-foreground">
                Infrastructure owned and operated by the community. Participants collectively contribute compute resources—GPUs, CPUs, storage, and bandwidth—to host frontier models without centralized control.
              </p>
            </div>

            <div className="space-y-3">
              <div className="flex items-center gap-3 text-foreground">
                <span className="text-xs font-mono text-[#D9F99D]">02</span>
                <h3 className="text-base font-semibold">Open Source & Transparent</h3>
              </div>
              <p className="text-sm leading-relaxed text-muted-foreground">
                The entire platform is openly developed, inspectable, and modular. We prioritize architectural transparency so that individual modules can be audited, modified, or replaced by anyone.
              </p>
            </div>

            <div className="space-y-3">
              <div className="flex items-center gap-3 text-foreground">
                <span className="text-xs font-mono text-[#D9F99D]">03</span>
                <h3 className="text-base font-semibold">Documentation First</h3>
              </div>
              <p className="text-sm leading-relaxed text-muted-foreground">
                We document our designs and reasoning before implementation. High-quality engineering specs serve as our primary source of truth, aligning contributors across repositories.
              </p>
            </div>

            <div className="space-y-3">
              <div className="flex items-center gap-3 text-foreground">
                <span className="text-xs font-mono text-[#D9F99D]">04</span>
                <h3 className="text-base font-semibold">Durable Simplicity</h3>
              </div>
              <p className="text-sm leading-relaxed text-muted-foreground">
                Preferring simple, modular components over monolithic and complex systems. We construct systems that remain maintainable and operational over years, resisting engineering bloat.
              </p>
            </div>
          </div>
        </section>

        {/* DEMO SECTION */}
        <section aria-labelledby="demo-heading" className="space-y-6 pt-6 border-t border-border/40">
          <div className="space-y-2">
            <span className="text-xs font-mono uppercase tracking-wider text-[#D9F99D]">03 // DEMO</span>
            <h2 id="demo-heading" className="text-2xl font-semibold tracking-tight text-foreground">
              Public Intelligence v1 Demo
            </h2>
            <p className="max-w-2xl text-sm leading-relaxed text-muted-foreground">
              A walkthrough of the first working prototype demonstrating the Website, Scheduler, Node, registration, heartbeats, and local inference.
            </p>
          </div>
          <div className="relative w-full aspect-video overflow-hidden rounded-lg border border-border/40 bg-muted/20">
            <iframe
              src="https://www.youtube.com/embed/cGDWpOArB5I"
              title="Public Intelligence v1 Demo"
              allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share"
              allowFullScreen
              className="absolute top-0 left-0 w-full h-full border-0"
            />
          </div>
        </section>

        {/* TWITTER / X TIMELINE */}
        <section aria-labelledby="updates-heading" className="space-y-6 pt-6 border-t border-border/40">
          <div className="space-y-2">
            <span className="text-xs font-mono uppercase tracking-wider text-[#D9F99D]">04 // LATEST UPDATES</span>
            <h2 id="updates-heading" className="text-2xl font-semibold tracking-tight text-foreground">
              Live Feed
            </h2>
            <p className="max-w-2xl text-sm leading-relaxed text-muted-foreground">
              Follow our project updates and community announcements.
            </p>
          </div>
          <div className="w-full max-w-3xl mx-auto min-h-[600px] overflow-hidden rounded-lg border border-border/40 bg-muted/10 p-4 flex justify-center">
            <TwitterTimeline />
          </div>
        </section>

        {/* CURRENT MILESTONE */}
        <section aria-labelledby="milestone-heading" className="space-y-6 pt-6 border-t border-border/40">
          <div className="flex items-center gap-3">
            <span className="h-1.5 w-1.5 rounded-full bg-[#D9F99D]" />
            <span className="text-xs font-mono uppercase tracking-wider text-muted-foreground">05 // ACTIVE ROADMAP</span>
          </div>
          <div className="grid gap-6 md:grid-cols-3 pt-2">
            <div className="md:col-span-1">
              <p className="text-xs font-mono uppercase tracking-wider text-muted-foreground/60 mb-1">Current Milestone</p>
              <h2 id="milestone-heading" className="text-lg font-semibold text-foreground">
                Phase 4 — WAN Networking & Pipeline Parallelism
              </h2>
            </div>
            <div className="md:col-span-2">
              <p className="text-sm leading-relaxed text-muted-foreground">
                The core distributed infrastructure is realized. The next focus
                is a visual control plane that makes node onboarding, network
                health, and inference execution observable.
              </p>
            </div>
          </div>
        </section>
      </div>
    </PageShell>
  );
}
