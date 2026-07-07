import { apiFetch } from "./api";

export type Credits = { balance: number; monthly_quota: number; plan: string };

export const creditsKey = ["credits"] as const;

export async function fetchCredits(): Promise<Credits> {
  const res = await apiFetch("/api/credits");
  if (!res.ok) throw new Error("failed to load credits");
  return res.json();
}
