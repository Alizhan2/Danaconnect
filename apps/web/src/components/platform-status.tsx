"use client";
import {
  createContext,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";
import { api } from "@/lib/api";
export type PlatformHealth = {
  status: string;
  environment: string;
  demo_mode: boolean;
};
const PlatformContext = createContext<{
  health: PlatformHealth | null;
  loading: boolean;
}>({ health: null, loading: true });
export function PlatformProvider({ children }: { children: ReactNode }) {
  const [health, setHealth] = useState<PlatformHealth | null>(null);
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    let alive = true;
    api<PlatformHealth>("/health")
      .then((value) => {
        if (alive) setHealth(value);
      })
      .catch(() => {})
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, []);
  return (
    <PlatformContext.Provider value={{ health, loading }}>
      {children}
    </PlatformContext.Provider>
  );
}
export const usePlatformStatus = () => useContext(PlatformContext);
