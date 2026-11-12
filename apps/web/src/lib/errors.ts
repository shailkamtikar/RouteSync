import { ApiError } from "@/lib/api";

type ValidationItem = { loc?: unknown[]; msg?: string };

/** Turns an API failure into one sentence that is safe to show an operator. */
export function describeError(error: unknown): string {
  if (error instanceof ApiError) {
    if (typeof error.detail === "string") return error.detail;
    if (Array.isArray(error.detail)) {
      return (error.detail as ValidationItem[])
        .map((item) => {
          const field = Array.isArray(item.loc) ? String(item.loc[item.loc.length - 1]) : "";
          return field && field !== "body" ? `${field}: ${item.msg}` : String(item.msg);
        })
        .join("; ");
    }
    if (error.status === 401) return "Your session has expired. Please sign in again.";
    if (error.status === 403) return "You do not have permission to do that.";
  }
  return "Something went wrong. Please try again.";
}
