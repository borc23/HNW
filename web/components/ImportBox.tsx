"use client";

import { CircleAlert, CircleCheck, LoaderCircle } from "lucide-react";
import { useRouter } from "next/navigation";
import { useActionState, useEffect, useState, type ReactNode } from "react";
import { checkJob, startImport, type ImportState } from "@/app/actions";
import styles from "./ImportBox.module.css";

const POLL_MS = 2500;
const DONE_VISIBLE_MS = 6000; // the bar floats over the feed, so success clears itself

type Progress =
  | { kind: "idle" }
  | { kind: "working" }
  | { kind: "done" }
  | { kind: "error"; message: string };

/** Paste a listing link, then follow its import job until the listing is in the feed. */
export function ImportBox() {
  const [state, submit, submitting] = useActionState(startImport, { kind: "idle" } as ImportState);
  const progress = useJobProgress(state);
  const busy = submitting || progress.kind === "working";

  return (
    <div className={styles.box}>
      <form action={submit} className={styles.form} aria-label="Add a listing">
        <label htmlFor="listing-url" className="visually-hidden">
          Listing link
        </label>
        <input
          id="listing-url"
          name="url"
          type="url"
          required
          inputMode="url"
          autoComplete="off"
          placeholder="Found a place? Paste its link"
          className={styles.input}
        />
        <button type="submit" className={styles.button} disabled={busy}>
          {busy ? "Adding…" : "Add it"}
        </button>
      </form>
      <div aria-live="polite" className={styles.live}>
        {statusLine(submitting ? { kind: "working" } : progress)}
      </div>
    </div>
  );
}

function useJobProgress(state: ImportState): Progress {
  const router = useRouter();
  const [progress, setProgress] = useState<Progress>({ kind: "idle" });

  useEffect(() => {
    if (state.kind === "error") return setProgress(state);
    if (state.kind !== "queued") return;

    let stopped = false;
    let timer: ReturnType<typeof setTimeout>;
    setProgress({ kind: "working" });

    const poll = async () => {
      const check = await checkJob(state.jobId);
      if (stopped) return;
      if (!check.ok) return setProgress({ kind: "error", message: check.message });
      const { job } = check;
      if (job.status === "succeeded") {
        setProgress({ kind: "done" });
        timer = setTimeout(() => setProgress({ kind: "idle" }), DONE_VISIBLE_MS);
        return router.refresh();
      }
      if (job.status === "failed") {
        return setProgress({ kind: "error", message: job.error ?? "The import failed." });
      }
      timer = setTimeout(poll, POLL_MS);
    };
    poll();
    return () => {
      stopped = true;
      clearTimeout(timer);
    };
  }, [state, router]);

  return progress;
}

function statusLine(progress: Progress): ReactNode {
  switch (progress.kind) {
    case "idle":
      return null;
    case "working":
      return (
        <Status tone="working" icon={<LoaderCircle size={18} className={styles.spin} />}>
          We're reading it now. This usually takes about a minute.
        </Status>
      );
    case "done":
      return (
        <Status tone="ok" icon={<CircleCheck size={18} />}>
          Added. It's at the top of your homes below.
        </Status>
      );
    case "error":
      return (
        <Status tone="problem" icon={<CircleAlert size={18} />}>
          {progress.message}
        </Status>
      );
  }
}

function Status({ tone, icon, children }: { tone: string; icon: ReactNode; children: ReactNode }) {
  return (
    <p className={`${styles.status} ${styles[tone]}`}>
      <span aria-hidden="true">{icon}</span>
      {children}
    </p>
  );
}
