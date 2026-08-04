import { PageShell } from "@/components/page-shell";
import { PageHeader } from "@/components/page-header";

const categories = [
  {
    name: "Distributed Systems",
    description:
      "Research on coordination, reliability, scaling, and the behavior of systems made from independently operated machines.",
    areas: ["Distributed scheduling", "Peer-to-peer networks", "Volunteer computing"],
    icon: (
      <svg className="w-5 h-5 text-[#D9F99D]" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="1.5" aria-hidden="true">
        <circle cx="12" cy="12" r="3" fill="currentColor" />
        <circle cx="6" cy="6" r="1.5" fill="currentColor" fillOpacity="0.4" />
        <circle cx="18" cy="6" r="1.5" fill="currentColor" fillOpacity="0.4" />
        <circle cx="6" cy="18" r="1.5" fill="currentColor" fillOpacity="0.4" />
        <circle cx="18" cy="18" r="1.5" fill="currentColor" fillOpacity="0.4" />
        <path d="M6 6L12 12M18 6L12 12M6 18L12 12M18 18L12 12" stroke="currentColor" strokeWidth="1" strokeOpacity="0.3" />
      </svg>
    ),
  },
  {
    name: "AI Infrastructure",
    description:
      "Research on the systems required to host, serve, and operate frontier open-source AI models across shared infrastructure.",
    areas: ["AI infrastructure fundamentals", "Distributed inference", "Resource utilization"],
    icon: (
      <svg className="w-5 h-5 text-[#D9F99D]" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="1.5" aria-hidden="true">
        <path d="M12 4L4 8L12 12L20 8L12 4Z" stroke="currentColor" />
        <path d="M4 16L12 20L20 16" stroke="currentColor" strokeOpacity="0.5" />
        <path d="M4 8V16" stroke="currentColor" strokeOpacity="0.5" />
        <path d="M20 8V16" stroke="currentColor" strokeOpacity="0.5" />
      </svg>
    ),
  },
  {
    name: "Scheduling",
    description:
      "Research on assigning workloads to suitable nodes based on capability, health, latency, load, and network conditions.",
    areas: ["Kubernetes Scheduler", "Ray", "Load balancing"],
    icon: (
      <svg className="w-5 h-5 text-[#D9F99D]" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="1.5" aria-hidden="true">
        <rect x="4" y="6" width="16" height="4" rx="1" stroke="currentColor" />
        <rect x="4" y="14" width="16" height="4" rx="1" stroke="currentColor" strokeOpacity="0.4" />
        <circle cx="8" cy="8" r="1" fill="currentColor" />
        <circle cx="16" cy="16" r="1" fill="currentColor" />
      </svg>
    ),
  },
  {
    name: "Node Communication",
    description:
      "Research on how nodes advertise resources, report health, send heartbeats, receive assignments, and return results.",
    areas: ["Resource advertisement", "Heartbeat design", "Health checks"],
    icon: (
      <svg className="w-5 h-5 text-[#D9F99D]" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="1.5" aria-hidden="true">
        <path d="M17 17L21 21M3 3L7 7" stroke="currentColor" />
        <circle cx="12" cy="12" r="4" stroke="currentColor" />
        <path d="M12 2v4" stroke="currentColor" strokeOpacity="0.4" />
        <path d="M12 18v4" stroke="currentColor" strokeOpacity="0.4" />
        <path d="M2 12h4" stroke="currentColor" strokeOpacity="0.4" />
        <path d="M18 12h4" stroke="currentColor" strokeOpacity="0.4" />
      </svg>
    ),
  },
  {
    name: "Geographic Scheduling",
    description:
      "Research on location-aware scheduling decisions that account for latency, proximity, regional capacity, and reliability.",
    areas: ["Latency", "Geographic proximity", "Regional availability"],
    icon: (
      <svg className="w-5 h-5 text-[#D9F99D]" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="1.5" aria-hidden="true">
        <circle cx="12" cy="12" r="9" stroke="currentColor" strokeOpacity="0.3" />
        <circle cx="12" cy="12" r="5" stroke="currentColor" />
        <circle cx="12" cy="12" r="1" fill="currentColor" />
      </svg>
    ),
  },
  {
    name: "System Inspirations",
    description:
      "Research into existing projects and patterns that inform the architecture without defining it.",
    areas: ["Petals", "Kubernetes", "Linux"],
    icon: (
      <svg className="w-5 h-5 text-[#D9F99D]" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="1.5" aria-hidden="true">
        <path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20" stroke="currentColor" />
        <path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z" stroke="currentColor" strokeOpacity="0.4" />
      </svg>
    ),
  },
];

export default function ResearchPage() {
  return (
    <PageShell>
      <article className="max-w-4xl mx-auto space-y-24">
        <PageHeader
          kicker="Research Hub"
          title="Research"
          description="Public Intelligence is extending its realized distributed infrastructure. Research focuses on the systems, operations, and interfaces needed for the next stage of the network."
        />

        {/* RESEARCH CATEGORIES */}
        <section aria-labelledby="categories-heading" className="space-y-8 pt-6 border-t border-border/40">
          <div className="space-y-2">
            <span className="text-xs font-mono uppercase tracking-wider text-[#D9F99D]">01 // INVESTIGATIVE CATEGORIES</span>
            <h2 id="categories-heading" className="text-2xl font-semibold tracking-tight text-foreground">
              Research Domains
            </h2>
            <p className="max-w-2xl text-sm leading-relaxed text-muted-foreground">
              Our active investigation tracks mapping the architectural problems of decentralized computing.
            </p>
          </div>

          <div className="grid gap-x-12 gap-y-12 md:grid-cols-2 pt-4">
            {categories.map((category) => (
              <div key={category.name} className="space-y-4">
                <div className="flex items-center gap-3 text-foreground border-b border-border/20 pb-2">
                  {category.icon}
                  <h3 className="text-base font-semibold">{category.name}</h3>
                </div>
                <p className="text-sm leading-relaxed text-muted-foreground">
                  {category.description}
                </p>
                <div className="space-y-1.5 pt-1">
                  <p className="text-[10px] font-mono uppercase tracking-wider text-muted-foreground/50">Investigative Areas</p>
                  <ul className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground/80 font-mono">
                    {category.areas.map((area) => (
                      <li key={area} className="flex items-center gap-1.5">
                        <span className="h-1 w-1 rounded-full bg-[#D9F99D]" />
                        {area}
                      </li>
                    ))}
                  </ul>
                </div>
              </div>
            ))}
          </div>
        </section>
      </article>
    </PageShell>
  );
}
