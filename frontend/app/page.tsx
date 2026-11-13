import { ResearchForm } from "@/components/ResearchForm";
import { RunHistory } from "@/components/RunHistory";

export default function Home() {
  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-2xl font-semibold tracking-tight">Research Agent</h1>
        <p className="mt-1 max-w-3xl text-zinc-600 dark:text-zinc-400">
          Plans a research task, retrieves public sources, and writes a cited report. Every
          finding quotes stored evidence; anything unverified is marked unknown, and conflicts
          between sources are flagged.
        </p>
      </header>
      <div className="grid gap-6 lg:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
        <ResearchForm />
        <RunHistory />
      </div>
    </div>
  );
}
