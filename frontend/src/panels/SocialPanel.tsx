import UnifiedFeed from "./social/UnifiedFeed";
import type { ChatContentAction } from "./social/ContentDetailDrawer";

type SocialPanelProps = {
  onSendToChat?: ChatContentAction;
  onDeepAnalysis?: ChatContentAction;
};

export default function SocialPanel({ onSendToChat, onDeepAnalysis }: SocialPanelProps) {
  return (
    <UnifiedFeed
      onSendToChat={onSendToChat}
      onDeepAnalysis={onDeepAnalysis}
    />
  );
}
