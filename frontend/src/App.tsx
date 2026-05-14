import { useState, KeyboardEvent } from "react";
import { runQuery, QueryResponse, HistoryEntry } from "./api";

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
  const [history, setHistory] = useState<HistoryEntry[]>([]);
  const [lastQuestion, setLastQuestion] = useState<string>("");
  const [followUpQuestion, setFollowUpQuestion] = useState<string>("");

  async function submit(q: string) {
    if (!q || status === "loading") return;

    // Push current result into history before fetching next
    const newHistory =
      result && lastQuestion
        ? [...history, { question: lastQuestion, sql: result.sql, answer: result.answer }]
        : history;

    setHistory(newHistory);
    setStatus("loading");
    setResult(null);
    setError(null);
    setLastQuestion(q);

    try {
      const data = await runQuery(q, newHistory.slice(-5));
      setResult(data);
      setStatus("success");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unknown error.");
      setStatus("error");
    }
  }

  function handleSubmit() {
    submit(question.trim());
  }

  function handleFollowUpSubmit() {
    const q = followUpQuestion.trim();
    if (q) {
      setFollowUpQuestion("");
      submit(q);
    }
  }

  function handleNewConversation() {
    setHistory([]);
    setResult(null);
    setError(null);
    setStatus("idle");
    setQuestion("");
    setLastQuestion("");
    setFollowUpQuestion("");
  }

  function handleKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
    }
  }

  const hasActivity = history.length > 0 || result !== null;

  return (
    <div className="page">
      <header className="header">
        <h1>Nivii SQL Query</h1>
        <p>Ask questions about your sales data in plain English.</p>
      </header>

      <main className="card">
        {hasActivity && (
          <div className="chat-header">
            <p className="section-label" style={{ marginTop: 0, marginBottom: 0 }}>
              Conversation
            </p>
            <button className="btn-new-conversation" onClick={handleNewConversation}>
              New conversation
            </button>
          </div>
        )}

        {history.length > 0 && (
          <div className="chat-thread">
            {history.map((entry, i) => (
              <div key={i} className="chat-exchange">
                <p className="chat-question">{entry.question}</p>
                {entry.answer && <p className="chat-answer">{entry.answer}</p>}
                <details className="sql-details">
                  <summary>View query</summary>
                  <pre className="sql-pre">{entry.sql}</pre>
                </details>
              </div>
            ))}
          </div>
        )}

        {hasActivity && <hr className="chat-divider" />}

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

        {!hasActivity && (
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
        )}

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

        {status === "success" && result && (
          <div className="followup-row">
            <textarea
              className="textarea"
              value={followUpQuestion}
              onChange={(e) => setFollowUpQuestion(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  handleFollowUpSubmit();
                }
              }}
              placeholder="Ask a follow-up question…"
              rows={2}
            />
            <button
              className="btn-primary"
              onClick={handleFollowUpSubmit}
              disabled={!followUpQuestion.trim()}
            >
              Ask
            </button>
          </div>
        )}
      </main>
    </div>
  );
}
