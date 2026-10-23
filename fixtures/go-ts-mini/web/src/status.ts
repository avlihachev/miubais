export type JobStatus = "pending" | "in_progress" | "delivered" | "cancelled";

const LABELS: Record<JobStatus, string> = {
  pending: "Pending",
  in_progress: "In progress",
  delivered: "Delivered",
  cancelled: "Cancelled",
};

export function statusLabel(status: JobStatus): string {
  return LABELS[status];
}

export function isTerminal(status: JobStatus): boolean {
  return status === "delivered" || status === "cancelled";
}

export function canCancel(status: JobStatus): boolean {
  return status === "pending";
}
