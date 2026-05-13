import { useState, KeyboardEvent } from "react";
import { runQuery, QueryResponse } from "./api";

const EXAMPLES = [
  "What is the most bought product on Fridays?",
  "Which waiter had the highest revenue?",
  "Top 5 products by total quantity sold?",
  "Average order value per day of week?",
  "How many unique products are sold?",
];

type Status = "idle" | "loading" | "success" | "error";

export default function App() {
  const [question, setQuestion] = useState("");
  const [status, setStatus] = useState<Status>("idle");
  const [result, setResult] = useState<QueryResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit() {
    const q = question.trim();
    if (!q || status === "loading") return;

    setStatus("loading");
    setResult(null);
    setError(null);

    try {
      const data = await runQuery(q);
      setResult(data);
      setStatus("success");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unknown error.");
      setStatus("error");
    }
  }

  function handleKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
    }
  }

  return (
    <div className="page">
      <header className="header">
        <h1>Nivii SQL Query</h1>
        <p>Ask questions about your sales data in plain English.</p>
      </header>

      <main className="card">
        <div className="input-row">
          <textarea
            className="textarea"
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="e.g. What is the most bought product on Fridays?"
            rows={2}
            disabled={status === "loading"}
          />
          <button
            className="btn-primary"
            onClick={handleSubmit}
            disabled={status === "loading" || !question.trim()}
          >
            {status === "loading" ? "..." : "Ask"}
          </button>
        </div>

        <div className="chips">
          {EXAMPLES.map((ex) => (
            <button
              key={ex}
              className="chip"
              onClick={() => setQuestion(ex)}
              disabled={status === "loading"}
            >
              {ex}
            </button>
          ))}
        </div>

        {status === "loading" && (
          <div className="status-row">
            <span className="spinner" />
            <span className="status-text">Generating SQL and querying…</span>
          </div>
        )}

        {status === "error" && error && (
          <div className="error-box">{error}</div>
        )}

        {status === "success" && result && (
          <div className="result">
            {result.answer && (
              <>
                <p className="section-label">Answer</p>
                <div className="answer-box">{result.answer}</div>
              </>
            )}

            <p className="section-label">Generated SQL</p>
            <details className="sql-details">
              <summary>View query</summary>
              <pre className="sql-pre">{result.sql}</pre>
            </details>

            <p className="section-label">Results</p>
            {result.columns.length > 0 ? (
              <>
                <div className="table-wrap">
                  <table>
                    <thead>
                      <tr>
                        {result.columns.map((col) => (
                          <th key={col}>{col}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {result.rows.map((row, i) => (
                        <tr key={i}>
                          {row.map((cell, j) => (
                            <td key={j}>{cell ?? ""}</td>
                          ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <p className="row-count">
                  {result.row_count} row{result.row_count !== 1 ? "s" : ""} returned
                </p>
              </>
            ) : (
              <p className="no-results">No rows returned.</p>
            )}
          </div>
        )}
      </main>
    </div>
  );
}
