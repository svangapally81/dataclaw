type AnyError = {
  status?: number | string;
  originalStatus?: number;
  data?: unknown;
  error?: string;
};

function detailFromData(data: unknown): string | null {
  if (typeof data === "string") {
    if (!data.trim() || /^internal server error$/i.test(data.trim())) return null;
    return data;
  }
  if (data && typeof data === "object") {
    const d = data as Record<string, unknown>;
    if (typeof d.detail === "string") return d.detail;
    if (d.detail && typeof d.detail === "object") {
      const nested = d.detail as Record<string, unknown>;
      if (typeof nested.detail === "string") return nested.detail;
      if (typeof nested.message === "string") return nested.message;
    }
    if (typeof d.message === "string") return d.message;
  }
  return null;
}

export function errorMessage(error: unknown): string {
  if (error instanceof Error) return error.message;
  if (typeof error === "string") return error;

  if (error && typeof error === "object" && "status" in error) {
    const err = error as AnyError;
    const status = err.status;
    const effective = typeof status === "number" ? status : err.originalStatus;
    const detail = detailFromData(err.data);

    if (status === "FETCH_ERROR") {
      return "Could not reach the DataClaw API. Make sure the backend is running, then try again.";
    }

    if (effective === 401 || effective === 403) {
      return "The admin credentials were not accepted. Check the email and password, then try again.";
    }
    if (effective === 404) {
      return "The DataClaw API route was not found.";
    }
    if (effective === 503) {
      return detail ?? "DataClaw isn't ready yet. Check Observability for the failing dependency and try again.";
    }
    if (effective !== undefined && effective >= 500) {
      if (detail) return detail;
      return `The DataClaw API returned HTTP ${effective}. Check the backend logs for details.`;
    }
    if (effective !== undefined && effective >= 400) {
      return detail ?? `The DataClaw API returned HTTP ${effective}.`;
    }

    if (detail) return detail;
  }

  return "Something went wrong. Please try again.";
}
