import { forwardRef, type ButtonHTMLAttributes } from "react";
import { cn } from "../../lib/utils";

type Variant = "default" | "outline" | "danger" | "ghost";

const variants: Record<Variant, string> = {
  default: "bg-slate-900 text-white hover:bg-slate-700",
  outline: "border border-slate-400 bg-white text-slate-900 hover:bg-slate-100",
  danger: "bg-red-700 text-white hover:bg-red-800",
  ghost: "text-slate-700 hover:bg-slate-100",
};

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { className, variant = "default", type = "button", ...props },
  ref,
) {
  return (
    <button
      ref={ref}
      type={type}
      className={cn(
        "inline-flex items-center justify-center rounded-md px-3 py-1.5 text-sm font-medium",
        "focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-700",
        "disabled:cursor-not-allowed disabled:opacity-50 aria-disabled:cursor-not-allowed aria-disabled:opacity-50",
        variants[variant],
        className,
      )}
      {...props}
    />
  );
});
