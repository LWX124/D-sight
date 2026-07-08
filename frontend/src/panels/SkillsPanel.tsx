import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { fetchSkills, installSkill, uninstallSkill, type SkillItem } from "@/lib/skills";
import { Button } from "@/components/ui/button";

const skillsKey = ["skills"] as const;

function Badge({ children }: { children: React.ReactNode }) {
  return (
    <span className="inline-flex items-center rounded-md bg-muted px-1.5 py-0.5 text-[11px] font-medium text-muted-foreground">
      {children}
    </span>
  );
}

function SkillCard({ skill }: { skill: SkillItem }) {
  const qc = useQueryClient();

  const install = useMutation({
    mutationFn: () => installSkill(skill.slug),
    onSuccess: () => qc.invalidateQueries({ queryKey: skillsKey }),
  });
  const uninstall = useMutation({
    mutationFn: () => uninstallSkill(skill.slug),
    onSuccess: () => qc.invalidateQueries({ queryKey: skillsKey }),
  });

  const pending = install.isPending || uninstall.isPending;

  return (
    <div className="group flex flex-col rounded-xl border border-border bg-card p-4 transition-colors hover:bg-accent/30">
      <h3 className="text-sm font-medium text-foreground">{skill.name}</h3>
      <p className="mt-1 line-clamp-2 text-[13px] leading-relaxed text-muted-foreground">
        {skill.description}
      </p>
      <div className="mt-3 flex flex-wrap gap-1.5">
        <Badge>{skill.price > 0 ? `${skill.price} 积分/次` : "免费"}</Badge>
        {skill.model_weight === "pro" && <Badge>Pro</Badge>}
      </div>
      <div className="mt-auto flex justify-end pt-4">
        {skill.installed ? (
          <Button
            variant="outline"
            size="sm"
            data-testid={`skill-install-${skill.slug}`}
            disabled={pending}
            onClick={() => uninstall.mutate()}
          >
            卸载
          </Button>
        ) : (
          <Button
            size="sm"
            data-testid={`skill-install-${skill.slug}`}
            disabled={pending}
            onClick={() => install.mutate()}
          >
            安装
          </Button>
        )}
      </div>
    </div>
  );
}

export default function SkillsPanel() {
  const { data: skills = [], isLoading, isError } = useQuery({
    queryKey: skillsKey,
    queryFn: fetchSkills,
  });

  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto max-w-5xl p-5">
        {isLoading && <p className="text-sm text-muted-foreground">加载中…</p>}
        {isError && <p className="text-sm text-destructive">加载技能失败</p>}
        {!isLoading && !isError && (
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {skills.map((skill) => (
              <SkillCard key={skill.slug} skill={skill} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
