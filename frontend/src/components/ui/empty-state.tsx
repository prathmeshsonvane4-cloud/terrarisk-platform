import type { LucideIcon } from "lucide-react";
import Link from "next/link";
import type { ReactNode } from "react";

import { buttonVariants } from "@/components/ui/button";
import { cn } from "@/lib/utils";

interface EmptyStateAction {
  label: string;
  href: string;
}

interface EmptyStateProps {
  icon?: LucideIcon;
  title: string;
  /** One orientation sentence: what happened, in plain language (P10
   * requirement 6 — every empty state explains what happened and what to
   * do next). */
  description: string;
  action?: EmptyStateAction;
  className?: string;
  children?: ReactNode;
}

/** Shared empty-state shell used across Farms / Reports / Assessments /
 * Overview and any other "nothing here yet" surface — one sentence plus
 * one action, no illustration-of-emptiness filler (Product Design v2
 * §7.1). */
export function EmptyState({ icon: Icon, title, description, action, className, children }: EmptyStateProps) {
  return (
    <div
      className={cn(
        "flex flex-col items-start gap-2 rounded-lg border border-dashed p-6 text-sm",
        className,
      )}
    >
      {Icon && <Icon aria-hidden className="mb-1 size-5 text-muted-foreground" />}
      <p className="font-medium">{title}</p>
      <p className="text-muted-foreground">{description}</p>
      {action && (
        <Link href={action.href} className={cn(buttonVariants({ size: "sm" }), "mt-1")}>
          {action.label}
        </Link>
      )}
      {children}
    </div>
  );
}
