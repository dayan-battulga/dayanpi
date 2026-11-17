import { useId, type ComponentProps } from "react";

interface FieldProps extends Omit<ComponentProps<"input">, "id" | "className"> {
  label: string;
}

// A label over a 48 px rounded box, the mockups' fields. aria-invalid gives it the wrong-password ring.
export function Field({ label, ...input }: FieldProps) {
  const id = useId();
  return (
    <div>
      <label htmlFor={id} className="field-label">
        {label}
      </label>
      <input id={id} className="field-input" {...input} />
    </div>
  );
}
