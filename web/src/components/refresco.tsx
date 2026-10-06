"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";

/** Mientras haya una corrida en cola o procesando, recarga los datos cada pocos segundos. */
export function Refresco({ activo, cadaMs = 3000 }: { activo: boolean; cadaMs?: number }) {
  const router = useRouter();
  useEffect(() => {
    if (!activo) return;
    const t = setInterval(() => router.refresh(), cadaMs);
    return () => clearInterval(t);
  }, [activo, cadaMs, router]);
  return null;
}
