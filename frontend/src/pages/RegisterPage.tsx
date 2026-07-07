import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { register, requestCode } from "@/lib/auth";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

export default function RegisterPage() {
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [code, setCode] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [countdown, setCountdown] = useState(0);
  const [sending, setSending] = useState(false);

  useEffect(() => {
    if (countdown <= 0) return;
    const t = setTimeout(() => setCountdown((c) => c - 1), 1000);
    return () => clearTimeout(t);
  }, [countdown]);

  async function onRequestCode() {
    setError("");
    if (!email) {
      setError("请先输入邮箱");
      return;
    }
    setSending(true);
    try {
      await requestCode(email);
      setCountdown(60);
    } catch (err) {
      setError(err instanceof Error ? err.message : "发送失败");
    } finally {
      setSending(false);
    }
  }

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      await register(email, code, password);
      navigate("/");
    } catch (err) {
      setError(err instanceof Error ? err.message : "注册失败");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="flex min-h-svh items-center justify-center bg-background p-4">
      <Card className="w-full max-w-sm">
        <CardHeader>
          <CardTitle>注册 D-sight</CardTitle>
          <CardDescription>使用邮箱验证码创建账号</CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={onSubmit} className="flex flex-col gap-4">
            <div className="flex flex-col gap-2">
              <Label htmlFor="email">邮箱</Label>
              <Input
                id="email"
                type="email"
                autoComplete="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
              />
            </div>
            <div className="flex flex-col gap-2">
              <Label htmlFor="code">验证码</Label>
              <div className="flex gap-2">
                <Input
                  id="code"
                  inputMode="numeric"
                  maxLength={6}
                  value={code}
                  onChange={(e) => setCode(e.target.value)}
                  required
                />
                <Button
                  type="button"
                  variant="outline"
                  onClick={onRequestCode}
                  disabled={countdown > 0 || sending}
                  className="shrink-0"
                >
                  {countdown > 0 ? `${countdown}s` : sending ? "发送中…" : "获取验证码"}
                </Button>
              </div>
            </div>
            <div className="flex flex-col gap-2">
              <Label htmlFor="password">密码</Label>
              <Input
                id="password"
                type="password"
                autoComplete="new-password"
                minLength={8}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
              />
            </div>
            {error && <p className="text-sm text-red-500">{error}</p>}
            <Button type="submit" disabled={loading}>
              {loading ? "注册中…" : "注册"}
            </Button>
            <p className="text-center text-sm text-muted-foreground">
              已有账号？{" "}
              <Link to="/login" className="text-foreground underline">
                登录
              </Link>
            </p>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}
