import * as React from "react";
import { PageShell } from "@/components/page-shell";
import { PageHeader } from "@/components/page-header";
import {
  OverallSystemDiagram,
  RequestFlowDiagram,
  GeographicSchedulingDiagram,
  DistributedInferenceDiagram,
  PlatformStackDiagram,
} from "@/components/architecture-diagrams";

export default function ArchitecturePage() {
  return (
    <PageShell>
      <article className="max-w-4xl mx-auto space-y-24">
        <PageHeader
          kicker="System Architecture"
          title="Architecture"
          description="The technical model and system boundaries for distributed AI infrastructure."
        />

        <section className="space-y-16">
          <header className="space-y-4">
            <h2 className="text-2xl font-semibold tracking-tight text-foreground">
              Overall System Topology
            </h2>
            <p className="text-muted-foreground max-w-3xl">
              High-level view of the three-plane architecture: the website portal for user onboarding,
              the scheduler core as the control plane, and the contributed node network as the execution plane.
            </p>
          </header>
          <OverallSystemDiagram />
        </section>

        <section className="space-y-16">
          <header className="space-y-4">
            <h2 className="text-2xl font-semibold tracking-tight text-foreground">
              Request Flow
            </h2>
            <p className="text-muted-foreground max-w-3xl">
              End-to-end request lifecycle from client submission through scheduler routing to node execution.
              The active path shows successful routing with direct result return bypassing the scheduler for verification.
            </p>
          </header>
          <RequestFlowDiagram />
        </section>

        <section className="space-y-16">
          <header className="space-y-4">
            <h2 className="text-2xl font-semibold tracking-tight text-foreground">
              Geographic Scheduling
            </h2>
            <p className="text-muted-foreground max-w-3xl">
              Latency-based node selection across global regions. The scheduler evaluates candidate nodes
              and routes to the minimum-latency target (EU-West at 12ms in this example).
            </p>
          </header>
          <GeographicSchedulingDiagram />
        </section>

        <section className="space-y-16">
          <header className="space-y-4">
            <h2 className="text-2xl font-semibold tracking-tight text-foreground">
              Distributed Inference
            </h2>
            <p className="text-muted-foreground max-w-3xl">
              Model layer partitioning across multiple compute shards for large-scale inference.
              Each shard processes a contiguous layer range with pipelined tensor passing.
            </p>
          </header>
          <DistributedInferenceDiagram />
        </section>

        <section className="space-y-16">
          <header className="space-y-4">
            <h2 className="text-2xl font-semibold tracking-tight text-foreground">
              Future Platform Stack
            </h2>
            <p className="text-muted-foreground max-w-3xl">
              Four-layer architecture vision: application APIs, orchestration coordination,
              decentralized transport, and local hardware runtime. The coordination layer is the
              active development focus.
            </p>
          </header>
          <PlatformStackDiagram />
        </section>
      </article>
    </PageShell>
  );
}
