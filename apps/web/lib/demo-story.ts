export type StoryPhase = 0 | 1 | 2 | 3;
export type DeskSource = { source: string; id: string; text: string; mark: string };
export type DeskView = {
  phase: StoryPhase;
  reader: string;
  role: string;
  multi: boolean;
  round: number;
  facts: string[];
  claim?: string;
  sentFacts: string[];
  sentClaim?: string;
  citations: number;
  blocked: boolean;
  restricted: string;
};
export const MOTION_SECONDS = [3.7, 2.7, 3.6, 2.4] as const;
export function answerParts(text = "") {
  const lines = text.split("\n").filter((line) => line.trim() && !line.startsWith("以下只列出")).map((line) => line.replace(/^- \[\w+\] /, ""));
  return { facts: lines.filter((line) => !line.startsWith("综合判断")), claim: lines.find((line) => line.startsWith("综合判断"))?.replace(/^综合判断[：:]\s*/, "") };
}
// The desk shows an excerpt; the complete API response remains available below it.
export function deskFacts(facts: string[]) {
  const relevant = facts.filter((fact) => /预算|供应商|全员会/.test(fact));
  return (relevant.length ? relevant : facts).slice(0, 3);
}
