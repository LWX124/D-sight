import { apiFetch } from "./api";

export type SkillItem = {
  slug: string; name: string; description: string; category: string;
  price: number; model_weight: string; is_default: boolean; installed: boolean;
};

export async function fetchSkills(): Promise<SkillItem[]> {
  const res = await apiFetch("/api/skills");
  if (!res.ok) throw new Error("failed to load skills");
  return res.json();
}

export async function installSkill(slug: string): Promise<void> {
  const res = await apiFetch(`/api/skills/${slug}/install`, { method: "POST" });
  if (!res.ok) throw new Error("install failed");
}

export async function uninstallSkill(slug: string): Promise<void> {
  const res = await apiFetch(`/api/skills/${slug}/install`, { method: "DELETE" });
  if (!res.ok) throw new Error("uninstall failed");
}
