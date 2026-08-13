import React from "react";
import "@testing-library/jest-dom/vitest";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import ContentDetailDrawer from "./ContentDetailDrawer";

const item = {
  id: "item-1",
  platform: "wechat",
  external_id: "article-1",
  content_type: "article",
  title: "测试文章",
  digest: "摘要",
  cover_url: null,
  url: "https://mp.weixin.qq.com/s/article-1",
  published_at: "2026-08-12T00:00:00Z",
  publisher: {
    id: "publisher-1",
    name: "测试公众号",
    avatar: null,
    platform: "wechat",
  },
};

describe("ContentDetailDrawer", () => {
  it("将正文语义段落渲染为分隔的文本块", async () => {
    render(
      <ContentDetailDrawer
        item={item}
        loadDetail={vi.fn().mockResolvedValue({
          ...item,
          body_text: "第一段。\n\n第二段第一行。\n第二段第二行。\n\n第三段。",
          transcript_text: null,
          media: [],
          bookmarked: false,
        })}
        bookmarked={false}
        onClose={vi.fn()}
        onToggleBookmark={vi.fn().mockResolvedValue(undefined)}
      />,
    );

    const body = await screen.findByRole("article", { name: "正文" });
    const paragraphs = Array.from(body.querySelectorAll("p"));
    expect(paragraphs).toHaveLength(3);
    expect(paragraphs.map((paragraph) => paragraph.textContent)).toEqual([
      "第一段。",
      "第二段第一行。\n第二段第二行。",
      "第三段。",
    ]);
  });
});
