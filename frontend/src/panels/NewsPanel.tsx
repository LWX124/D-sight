import NewsTimeline from "./NewsTimeline";
import ChatStub from "./ChatStub";

export default function NewsPanel() {
  return (
    <div className="flex h-full">
      <div className="w-[70%] min-w-0">
        <NewsTimeline />
      </div>
      <div className="w-[30%] border-l border-border">
        <ChatStub />
      </div>
    </div>
  );
}
