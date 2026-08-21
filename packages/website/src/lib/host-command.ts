/**
 * The command that puts a machine into a fleet (specs/host-a-node-on-the-website.md).
 *
 * This is a string module rather than part of the component because the website suite
 * runs under `environment: "node"` with no jsdom, so a value here can be tested and a
 * value inside a `.tsx` cannot. `host-command.test.ts` holds it byte-identical to the
 * block under `## Host a node` in the repository README -- editing one without the
 * other fails the gate, which is the only thing keeping a website and a doc that give
 * the same instruction from giving two different instructions.
 *
 * The placeholders are load-bearing and are asserted by that test. There is no
 * operated Scheduler to point at (D6); a copyable command carrying a real host would
 * enrol a stranger's machine into a fleet they did not pick, and would look like it
 * had worked.
 */
export const HOST_NODE_COMMAND = `curl -fsSL https://raw.githubusercontent.com/Epichlo/Public-Intelligence/main/scripts/bootstrap.sh \\
  | bash -s -- --scheduler-url https://your-scheduler --fleet-token TOKEN --invite-code CODE`;

/**
 * What the command does not do for you. Kept next to the command because every one of
 * these was a real failure on a real machine during the two-machine test: a node with
 * no Ollama, and a node whose credentials the Scheduler never accepted (W2, W5).
 */
export const HOST_NODE_PREREQUISITES = [
  "Ollama running locally with at least one model pulled.",
  "A Scheduler you or someone you trust runs — this is not a network to join.",
  "Its fleet token and an invite code, if that Scheduler sets them.",
] as const;
