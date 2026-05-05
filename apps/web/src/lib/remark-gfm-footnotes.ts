/**
 * remark plugin that enables GFM footnote syntax ([^N] / [^N]: definition)
 * support in react-markdown / remark pipelines.
 *
 * remark-gfm@4 implements the core GFM spec (tables, task lists, strikethrough,
 * autolinks) but NOT footnotes. GitHub did add footnote support to github.com
 * ("GFM footnotes"), and the low-level building blocks
 * (`micromark-extension-gfm-footnote`, `mdast-util-gfm-footnote`) are available
 * as separate packages. This plugin wires them together so that [^1] inline
 * markers and [^1]: definitions render as clickable superscripts.
 */
import { gfmFootnote } from "micromark-extension-gfm-footnote";
import {
  gfmFootnoteFromMarkdown,
  gfmFootnoteToMarkdown,
} from "mdast-util-gfm-footnote";

export default function remarkGfmFootnotes(this: {
  data: (key?: string) => Record<string, unknown[]>;
}): void {
  const data = this.data();

  function add(field: string, value: unknown) {
    const list = data[field] || (data[field] = []);
    (list as unknown[]).push(value);
  }

  add("micromarkExtensions", gfmFootnote());
  add("fromMarkdownExtensions", gfmFootnoteFromMarkdown());
  add("toMarkdownExtensions", gfmFootnoteToMarkdown());
}
