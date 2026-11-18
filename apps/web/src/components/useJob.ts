"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api, type Job } from "@/lib/api";

// Acompanha uma tarefa longa da API (gerar lote / disparar e-mail).
// Ao abrir a página, retoma a tarefa em andamento — recarregar não perde o progresso.
export function useJob(kind: "discover" | "email", onFinish: (job: Job) => void) {
  const [job, setJob] = useState<Job | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const fim = useRef(onFinish);
  useEffect(() => {
    fim.current = onFinish;
  }, [onFinish]);

  const poll = useCallback((id: string) => {
    const tick = async () => {
      try {
        const j = await api<Job>(`/jobs/${id}`);
        setJob(j);
        if (j.status === "done" || j.status === "error") {
          fim.current(j);
          return;
        }
      } catch {
        // rede instável: tenta de novo no próximo ciclo
      }
      timer.current = setTimeout(tick, 3000);
    };
    tick();
  }, []);

  useEffect(() => {
    api<Job | null>(`/jobs/active?kind=${kind}`)
      .then((j) => {
        if (j) {
          setJob(j);
          poll(j.id);
        }
      })
      .catch(() => undefined);
    return () => {
      if (timer.current) clearTimeout(timer.current);
    };
  }, [kind, poll]);

  const start = useCallback(
    (j: Job) => {
      setJob(j);
      poll(j.id);
    },
    [poll],
  );

  const running = !!job && (job.status === "queued" || job.status === "running");
  return { job, running, start, clear: () => setJob(null) };
}
