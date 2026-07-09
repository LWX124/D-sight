import { useNewsSelection } from "@/hooks/useNewsSelection";
import NewsTimeline from "./NewsTimeline";
import NewsAssistant from "./NewsAssistant";

export default function NewsPanel() {
  const { selectedIds, selectedItems, toggle, isFull } = useNewsSelection();

  return (
    <div className="flex h-full">
      <div className="w-[70%] min-w-0">
        <NewsTimeline
          selectedIds={selectedIds}
          onToggle={toggle}
          isFull={isFull}
        />
      </div>
      <div className="w-[30%] border-l border-border">
        <NewsAssistant selectedItems={selectedItems} />
      </div>
    </div>
  );
}
