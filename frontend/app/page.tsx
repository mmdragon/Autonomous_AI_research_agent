import { BackendStatus } from "@/components/BackendStatus";

export default function Home() {
  return (
    <main className="mx-auto flex w-full max-w-3xl flex-1 flex-col gap-6 px-4 py-12">
      <header>
        <h1 className="text-2xl font-semibold tracking-tight">Research Agent</h1>
        <p className="mt-2 text-zinc-600 dark:text-zinc-400">
          Plans a research task, retrieves public sources, and writes a cited report. Every
          finding links to stored evidence; anything unverified is marked unknown.
        </p>
      </header>
      <BackendStatus />
    </main>
  );
}
