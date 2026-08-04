import { PageShell } from "@/components/page-shell";
import { PageHeader } from "@/components/page-header";

export default function ContributePage() {
  return (
    <PageShell>
      <article className="max-w-4xl mx-auto space-y-24">
        <PageHeader
          kicker="Get Involved"
          title="Contribute"
          description="Learn how to become a contributor to Public Intelligence."
        />

        <section aria-labelledby="contribute-heading" className="space-y-6 pt-6 border-t border-border/40">
          <div className="space-y-2">
            <span className="text-xs font-mono uppercase tracking-wider text-[#D9F99D]">01 // HOW TO START</span>
            <h2 id="contribute-heading" className="text-2xl font-semibold tracking-tight text-foreground">
              Ways to Contribute
            </h2>
            <p className="max-w-2xl text-sm leading-relaxed text-muted-foreground">
              Contributors can help with research, documentation, scheduler implementation, and node deployment.
            </p>
          </div>
        </section>
      </article>
    </PageShell>
  );
}
