import { useNavigate } from "react-router-dom";
import { logout } from "@/lib/auth";
import { Button } from "@/components/ui/button";

export default function ChatPage() {
  const navigate = useNavigate();

  async function onLogout() {
    await logout();
    navigate("/login", { replace: true });
  }

  return (
    <div className="flex min-h-svh flex-col items-center justify-center gap-6 bg-background">
      <p className="text-2xl font-medium text-foreground">聊天界面（Task 7）</p>
      <Button variant="outline" onClick={onLogout}>
        退出登录
      </Button>
    </div>
  );
}
