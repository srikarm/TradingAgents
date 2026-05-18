import clsx, { type ClassValue } from "clsx";

/** Standard tailwind class-merge helper. clsx alone is fine for our scale —
 * we don't have enough utility-conflict churn to justify tailwind-merge. */
export function cn(...inputs: ClassValue[]) {
  return clsx(inputs);
}
