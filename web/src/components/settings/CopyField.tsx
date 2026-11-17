import { useState } from "react";

// Something shown once (a token, an invite link): selectable by hand, or one click to copy.
export function CopyField({ label, value, meta }: { label: string; value: string; meta: string }) {
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
    <div className="copy-box">
      <input readOnly className="copy-value" value={value} aria-label={label} onFocus={(event) => event.currentTarget.select()} />
      <span className="copy-meta">{meta}</span>
      <button type="button" className="button button-ink button-small" onClick={copyValue}>
        {copied ? "Copied" : "Copy"}
      </button>
    </div>
  );
}
