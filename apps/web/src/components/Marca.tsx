"use client";

import { useEffect } from "react";
import type { Marca } from "@/lib/api";

// Aplica a cor da EMPRESA logada no tema (a variável --brand do CSS).
// Só aceita #RRGGBB — a API valida, e a tela confere de novo antes de usar.
export function AplicaMarca({ marca }: { marca: Marca }) {
  useEffect(() => {
    const root = document.documentElement;
    if (/^#[0-9a-fA-F]{6}$/.test(marca.cor || "")) root.style.setProperty("--brand", marca.cor);
    else root.style.removeProperty("--brand");
    return () => {
      root.style.removeProperty("--brand");
    };
  }, [marca.cor]);
  return null;
}

// Logo da empresa (data URI PNG/JPEG/WEBP validado na API) ou as iniciais.
export function Selo({ marca, nome, grande = false }: { marca: Marca; nome: string; grande?: boolean }) {
  const tam = grande ? 46 : 36;
  if (/^data:image\/(png|jpeg|webp);base64,/.test(marca.logo || "")) {
    // eslint-disable-next-line @next/next/no-img-element
    return <img className="mark-img" src={marca.logo} alt={nome} width={tam} height={tam} style={{ width: tam, height: tam }} />;
  }
  const ini = nome.replace(/[^\p{L}\p{N} ]/gu, "").split(/\s+/).filter(Boolean).slice(0, 2).map((p) => p[0]).join("").toUpperCase() || "P";
  return <div className="mark" style={grande ? { width: 46, height: 46, fontSize: 18 } : undefined}>{ini}</div>;
}
