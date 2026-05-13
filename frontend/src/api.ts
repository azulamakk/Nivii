export interface QueryResponse {
  sql: string;
  columns: string[];
  rows: (string | number | null)[][];
  answer: string;
  row_count: number;
}

export async function runQuery(question: string): Promise<QueryResponse> {
  const res = await fetch("/api/query", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question }),
  });

  const data = await res.json();

  if (!res.ok) {
    throw new Error(data.detail ?? "An unexpected error occurred.");
  }

  return data as QueryResponse;
}
