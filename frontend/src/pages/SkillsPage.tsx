import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft } from "lucide-react";
import { fetchSkills, installSkill, uninstallSkill, type SkillItem } from "@/lib/skills";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

const skillsKey = ["skills"] as const;

function Badge({ children }: { children: React.ReactNode }) {
  return (
    <span className="inline-flex items-center rounded-md bg-muted px-1.5 py-0.5 text-xs font-medium text-muted-foreground">
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
    <Card className="flex flex-col">
      <CardHeader>
        <CardTitle>{skill.name}</CardTitle>
        <CardDescription className="line-clamp-2">{skill.description}</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-wrap gap-1.5">
        <Badge>{skill.price > 0 ? `${skill.price} 积分/次` : "免费"}</Badge>
        {skill.model_weight === "pro" && <Badge>Pro</Badge>}
      </CardContent>
      <CardFooter className="mt-auto justify-end">
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
      </CardFooter>
    </Card>
  );
}

export default function SkillsPage() {
  const { data: skills = [], isLoading, isError } = useQuery({
    queryKey: skillsKey,
    queryFn: fetchSkills,
  });

  return (
    <div className="min-h-svh bg-background">
      <header className="flex items-center justify-between border-b border-border px-4 py-2">
        <div className="flex items-center gap-3">
          <Button asChild variant="ghost" size="sm" data-testid="skills-back">
            <Link to="/">
              <ArrowLeft className="size-4" />
              返回聊天
            </Link>
          </Button>
          <span className="text-sm font-medium text-foreground">技能市场</span>
        </div>
      </header>
      <main className="mx-auto max-w-5xl p-4">
        {isLoading && <p className="text-sm text-muted-foreground">加载中…</p>}
        {isError && <p className="text-sm text-destructive">加载技能失败</p>}
        {!isLoading && !isError && (
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {skills.map((skill) => (
              <SkillCard key={skill.slug} skill={skill} />
            ))}
          </div>
        )}
      </main>
    </div>
  );
}
