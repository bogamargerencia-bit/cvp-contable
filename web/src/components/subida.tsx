"use client";

import { useRouter } from "next/navigation";
import { useRef, useState } from "react";
import { crearClienteNavegador } from "@/lib/supabase/client";

const MAX_MB = 50;
const EXT = [".pdf", ".xls", ".xlsx"];

async function sha256(f: File): Promise<string> {
  const h = await crypto.subtle.digest("SHA-256", await f.arrayBuffer());
  return Array.from(new Uint8Array(h)).map((b) => b.toString(16).padStart(2, "0")).join("");
}

function nombreSeguro(n: string): string {
  return n.normalize("NFKD").replace(/[^\x20-\x7e]/g, "").replace(/[^A-Za-z0-9._-]+/g, "_").slice(-120) || "archivo";
}

/**
 * Sube un archivo del período directo del navegador a Storage (ruta {cliente}/{periodo}/…, protegida por RLS),
 * registra la fila en `archivos` y deja como no vigente la versión anterior del mismo tipo y cuenta.
 */
export function Subida(props: {
  clienteId: string;
  periodoId: string;
  cuentaId: string | null;
  tipo: string;
  usuarioId: string;
  deshabilitado?: boolean;
  reemplaza?: boolean;
}) {
  const router = useRouter();
  const input = useRef<HTMLInputElement>(null);
  const [estado, setEstado] = useState<"" | "subiendo" | "error">("");
  const [msg, setMsg] = useState("");

  async function subir(f: File) {
    setMsg("");
    const ext = f.name.slice(f.name.lastIndexOf(".")).toLowerCase();
    if (!EXT.includes(ext)) {
      setEstado("error");
      setMsg("Solo PDF o Excel (.pdf, .xls, .xlsx)");
      return;
    }
    if (f.size > MAX_MB * 1024 * 1024) {
      setEstado("error");
      setMsg(`Máximo ${MAX_MB} MB`);
      return;
    }
    setEstado("subiendo");
    try {
      const sb = crearClienteNavegador();
      const huella = await sha256(f);
      const ruta = `${props.clienteId}/${props.periodoId}/${crypto.randomUUID()}-${nombreSeguro(f.name)}`;
      const up = await sb.storage.from("archivos").upload(ruta, f, { contentType: f.type || undefined, upsert: false });
      if (up.error) throw new Error("No se pudo subir el archivo");
      const { data, error } = await sb
        .from("archivos")
        .insert({
          periodo_id: props.periodoId,
          cuenta_id: props.cuentaId,
          tipo: props.tipo,
          storage_path: ruta,
          nombre_original: f.name,
          sha256: huella,
          tamano: f.size,
          subido_por: props.usuarioId,
        })
        .select("id")
        .single();
      if (error || !data) throw new Error("El archivo se subió, pero no se pudo registrar");
      // La versión anterior deja de ser vigente (no se borra: queda para auditoría).
      let q = sb.from("archivos").update({ vigente: false })
        .eq("periodo_id", props.periodoId).eq("tipo", props.tipo).eq("vigente", true).neq("id", data.id);
      q = props.cuentaId ? q.eq("cuenta_id", props.cuentaId) : q.is("cuenta_id", null);
      await q;
      setEstado("");
      router.refresh();
    } catch (e) {
      setEstado("error");
      setMsg(e instanceof Error ? e.message : "Error al subir");
    } finally {
      if (input.current) input.current.value = "";
    }
  }

  return (
    <span className="inline-flex items-center gap-2">
      <input
        ref={input}
        type="file"
        accept={EXT.join(",")}
        className="hidden"
        onChange={(e) => e.target.files?.[0] && subir(e.target.files[0])}
      />
      <button
        type="button"
        className="boton-sec"
        disabled={props.deshabilitado || estado === "subiendo"}
        onClick={() => input.current?.click()}
      >
        {estado === "subiendo" ? "Subiendo…" : props.reemplaza ? "Reemplazar" : "Subir"}
      </button>
      {msg && <span className="text-xs text-alerta">{msg}</span>}
    </span>
  );
}
