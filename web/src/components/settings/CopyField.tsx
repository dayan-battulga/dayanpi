import { Check, Copy } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

// Something shown once (a token, an invite link): selectable by hand, or one click to copy.
export function CopyField({ label, value }: { label: string; value: string }) {
  const [copied, setCopied] = useState(false);
  const copyValue = async () => {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
    } catch {
      // No clipboard (an old browser, or no permission): the box is still there to select.
      setCopied(false);
    }
  };
  return (
    <div className="flex gap-2">
      <Input readOnly value={value} aria-label={label} onFocus={(event) => event.currentTarget.select()} className="mono h-11 min-w-0 flex-1 rounded-full bg-secondary px-4 text-xs" />
      <Button type="button" variant="outline" onClick={copyValue} className="h-11 rounded-full border-input bg-transparent px-4 font-semibold">
        {copied ? <Check aria-hidden="true" /> : <Copy aria-hidden="true" />}
        {copied ? "Copied" : "Copy"}
      </Button>
    </div>
  );
}
