import { Suspense } from "react";

import { RunView } from "@/components/run/RunView";

// The run id is only known at request time, so RunView (which reads it with useParams)
// sits inside Suspense, as Cache Components requires.
export default function RunPage() {
  return (
    <Suspense fallback={<p role="status" className="text-sm text-zinc-600">Loading run…</p>}>
      <RunView />
    </Suspense>
  );
}
