import UnifiedFeed from "./social/UnifiedFeed";
import type { ChatContentAction } from "./social/ContentDetailDrawer";

type SocialPanelProps = {
  canManageCredentials?: boolean;
  onSendToChat?: ChatContentAction;
  onDeepAnalysis?: ChatContentAction;
};

export default function SocialPanel({
  canManageCredentials = false,
  onSendToChat,
  onDeepAnalysis,
}: SocialPanelProps) {
  return (
    <UnifiedFeed
      canManageCredentials={canManageCredentials}
      onSendToChat={onSendToChat}
      onDeepAnalysis={onDeepAnalysis}
    />
  );
}
