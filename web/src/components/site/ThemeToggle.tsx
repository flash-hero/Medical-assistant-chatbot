"use client";

import { DesktopIcon, MoonIcon, SunIcon } from "@/components/ui/icons";
import { useCallback, useSyncExternalStore } from "react";

type ThemeChoice = "system" | "light" | "dark";
const STORAGE_KEY = "ausculta-theme";
const NEXT: Readonly<Record<ThemeChoice, ThemeChoice>> = { system: "light", light: "dark", dark: "system" };
const listeners = new Set<() => void>();

function readChoice(): ThemeChoice {
  const value = document.documentElement.getAttribute("data-theme");
  return value === "light" || value === "dark" ? value : "system";
}

function writeChoice(choice: ThemeChoice): void {
  const root = document.documentElement;
  if (choice === "system") root.removeAttribute("data-theme");
  else root.setAttribute("data-theme", choice);
  try {
    if (choice === "system") window.localStorage.removeItem(STORAGE_KEY);
    else window.localStorage.setItem(STORAGE_KEY, choice);
  } catch {
    // Storage unavailable: the choice still applies for this page view.
  }
  listeners.forEach((listener) => listener());
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

interface ThemeToggleProps {
  readonly labels: Readonly<Record<ThemeChoice, string>>;
}

/** Cycles automatic -> light -> dark. The label always says the current state and the next action. */
export function ThemeToggle({ labels }: ThemeToggleProps) {
  const choice = useSyncExternalStore(subscribe, readChoice, () => "system" as const);
  const cycle = useCallback(() => writeChoice(NEXT[readChoice()]), []);
  const Icon = choice === "light" ? SunIcon : choice === "dark" ? MoonIcon : DesktopIcon;
  return (
    <button type="button" className="btn btn-ghost btn-icon" onClick={cycle} aria-label={labels[choice]} title={labels[choice]}>
      <Icon size={22} aria-hidden="true" />
    </button>
  );
}
