import { useId, type ComponentProps } from "react";
import { Input } from "@/components/ui/input";

interface FieldProps extends Omit<ComponentProps<"input">, "id"> {
  label: string;
  hint?: string;
}

// A labeled text box in the to-do input's shape, with an optional line under it that's read with it.
export function Field({ label, hint, ...input }: FieldProps) {
  const id = useId();
  const hintId = hint == null ? undefined : `${id}-hint`;
  return (
    <div className="flex flex-col gap-1.5">
      <label htmlFor={id} className="label">
        {label}
      </label>
      <Input id={id} aria-describedby={hintId} className="h-11 rounded-full bg-secondary px-4" {...input} />
      {hint != null && (
        <span id={hintId} className="muted small">
          {hint}
        </span>
      )}
    </div>
  );
}
