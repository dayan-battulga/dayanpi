import { parseDayPage, type PageBlock } from "@/lib/markdown";

function renderBlock(block: PageBlock, index: number) {
  const element =
    block.kind === "list" ? (
      <ul key={index} className="flex flex-col gap-0.5">
        {block.items.map((item, itemIndex) => (
          <li key={itemIndex}>{item}</li>
        ))}
      </ul>
    ) : block.kind === "paragraph" ? (
      <p key={index} className="text-muted-foreground">
        {block.text}
      </p>
    ) : block.level === 1 ? (
      <h3 key={index} className="text-base font-semibold">
        {block.text}
      </h3>
    ) : (
      <h4 key={index} className="label mt-2.5">
        {block.text}
      </h4>
    );
  return element;
}

interface DayPageProps {
  markdown: string;
}

export function DayPage({ markdown }: DayPageProps) {
  return <article className="flex flex-col gap-1.5 text-sm">{parseDayPage(markdown).map(renderBlock)}</article>;
}
