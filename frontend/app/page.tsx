"use client";

import { FormEvent, useMemo, useState } from "react";
import { downloadResultsExcel, getResultColumns, parseResultDate } from "../lib/exportExcel";

type QueryMode = "preview" | "execute";

type ResolvedLookupValue = {
  source_table?: string;
  source_column?: string;
  lookup_table?: string;
  canonical_value?: string;
  matched_synonym?: string;
  fixed_filter_value?: string;
};

type QueryResponse = {
  conversation_id?: string | null;
  sql?: string | null;
  rows?: Record<string, unknown>[];
  row_count?: number;
  question?: string | null;
  detected_domain?: string | null;
  retrieved_tables?: string[];
  generated_sql?: string | null;
  validated_sql?: string | null;
  validation_status?: string | null;
  warnings?: string[];
  execution_skipped?: boolean;
  execution_skip_reason?: string | null;
  enhanced_question?: string | null;
  clarification_questions?: string[];
  clarification_question?: string | null;
  resolved_lookup_values?: ResolvedLookupValue[];
  detected_query_pattern?: string | null;
  requires_user_confirmation?: boolean;
};

type ChatMessage = {
  id: string;
  role: "user" | "assistant";
  text: string;
  mode?: QueryMode;
  response?: QueryResponse;
  error?: string;
};

const USER_ID = "web_mvp_user";
let messageSequence = 0;

// Local React keys only; works on HTTP LAN addresses as well as localhost.
function createMessageId() {
  messageSequence += 1;
  return `message-${Date.now()}-${messageSequence}`;
}

export default function Home() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [pendingQuestion, setPendingQuestion] = useState<string | null>(null);
  const [queryMode, setQueryMode] = useState<QueryMode>("preview");

  const pendingClarification = useMemo(() => {
    const lastResponse = [...messages].reverse().find((message) => message.response)?.response;
    const questions = lastResponse?.clarification_questions || [];
    return lastResponse?.requires_user_confirmation
      ? lastResponse?.clarification_question || questions[0] || null
      : null;
  }, [messages]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const text = input.trim();
    if (!text || isLoading) {
      return;
    }

    const activeMode = queryMode;
    setInput("");
    setIsLoading(true);
    setMessages((current) => [
      ...current,
      { id: createMessageId(), role: "user", text, mode: activeMode }
    ]);

    const payload: Record<string, unknown> = {
      question: pendingClarification && pendingQuestion ? pendingQuestion : text,
      user_id: USER_ID,
      dry_run: activeMode === "preview"
    };
    if (conversationId) {
      payload.conversation_id = conversationId;
    }
    if (pendingClarification) {
      payload.clarification_answer = text;
    }

    try {
      const endpoint = activeMode === "preview" ? "/api/query-preview" : "/api/query";
      const response = await fetch(endpoint, {
        method: "POST",
        headers: {
          "Content-Type": "application/json"
        },
        body: JSON.stringify(payload)
      });
      const data = await response.json();
      if (!response.ok) {
        throw new Error(readError(data));
      }

      const queryResponse = data as QueryResponse;
      if (queryResponse.conversation_id) {
        setConversationId(queryResponse.conversation_id);
      }
      if (queryResponse.requires_user_confirmation) {
        setPendingQuestion(payload.question as string);
      } else {
        setPendingQuestion(null);
      }

      setMessages((current) => [
        ...current,
        {
          id: createMessageId(),
          role: "assistant",
          text: buildAssistantText(queryResponse),
          mode: activeMode,
          response: queryResponse
        }
      ]);
    } catch (error) {
      const message = error instanceof Error ? error.message : "Error desconocido";
      setMessages((current) => [
        ...current,
        {
          id: createMessageId(),
          role: "assistant",
          text: message,
          mode: activeMode,
          error: message
        }
      ]);
    } finally {
      setIsLoading(false);
    }
  }

  return (
    <main className="app-shell">
      <section className="workspace" aria-label="Text-to-SQL Oracle SAC">
        <header className="topbar">
          <div>
            <p className="eyebrow">Text-to-SQL Oracle SAC</p>
            <h1>Consulta gobernada</h1>
          </div>
          <div className="status-pill">
            <span className="status-dot" />
            {queryMode === "preview" ? "Vista previa" : "Ejecucion solicitada"}
          </div>
        </header>

        <div className="chat-layout">
          <section className="thread" aria-label="Conversacion">
            {messages.length === 0 ? (
              <div className="empty-state">
                <h2>Escribe una peticion de negocio</h2>
                <p>El backend conserva la decision final de ejecucion y siempre valida el SQL.</p>
              </div>
            ) : (
              messages.map((message) => (
                <article className={`message ${message.role}`} key={message.id}>
                  <p className="message-role">{message.role === "user" ? "Usuario" : "Sistema"}</p>
                  {message.mode ? (
                    <p className="message-mode">
                      {message.mode === "preview" ? "Vista previa" : "Ejecutar consulta"}
                    </p>
                  ) : null}
                  <p>{message.text}</p>
                  {message.response ? <TracePanel response={message.response} /> : null}
                  {message.error ? <p className="error-text">{message.error}</p> : null}
                </article>
              ))
            )}
          </section>

          <form className="composer" onSubmit={submit}>
            {pendingClarification ? (
              <div className="clarification">
                <span>Aclaracion requerida</span>
                <p>{pendingClarification}</p>
              </div>
            ) : null}

            <fieldset className="mode-selector">
              <legend>Modo</legend>
              <label className={queryMode === "preview" ? "selected" : ""}>
                <input
                  checked={queryMode === "preview"}
                  name="query-mode"
                  onChange={() => setQueryMode("preview")}
                  type="radio"
                  value="preview"
                />
                Vista previa
              </label>
              <label className={queryMode === "execute" ? "selected" : ""}>
                <input
                  checked={queryMode === "execute"}
                  name="query-mode"
                  onChange={() => setQueryMode("execute")}
                  type="radio"
                  value="execute"
                />
                Ejecutar consulta
              </label>
            </fieldset>

            <label className="sr-only" htmlFor="question">
              Pregunta
            </label>
            <textarea
              id="question"
              name="question"
              value={input}
              onChange={(event) => setInput(event.target.value)}
              placeholder={pendingClarification ? "Responde la aclaracion" : "Ej: cantidad de clientes activos por municipio"}
              rows={3}
            />
            <div className="composer-actions">
              <span>
                {isLoading
                  ? "Consultando..."
                  : queryMode === "preview"
                    ? "POST /query/preview"
                    : "POST /query"}
              </span>
              <button disabled={isLoading || !input.trim()} type="submit">
                Enviar
              </button>
            </div>
          </form>
        </div>
      </section>
    </main>
  );
}

function TracePanel({ response }: { response: QueryResponse }) {
  const [isExporting, setIsExporting] = useState(false);
  const [exportError, setExportError] = useState("");
  const rows = response.rows || [];
  const visibleRows = rows.slice(0, 10);
  const sql = response.validated_sql || response.sql || response.generated_sql || "";
  const columns = getResultColumns(rows);
  const warnings = response.warnings || [];
  const lookupValues = response.resolved_lookup_values || [];

  async function exportResults() {
    if (isExporting || rows.length === 0 || response.execution_skipped) return;
    setIsExporting(true);
    setExportError("");
    try {
      await downloadResultsExcel(rows);
    } catch {
      setExportError("No se pudo descargar el Excel. Intenta nuevamente.");
    } finally {
      setIsExporting(false);
    }
  }

  return (
    <div className="trace">
      <div className="metrics">
        <Metric label="Filas" value={String(response.row_count ?? rows.length)} />
        <Metric
          label="Ejecucion omitida"
          value={response.execution_skipped ? "Si" : "No"}
        />
        <Metric
          label="Estado"
          value={response.validation_status === "valid" ? "Válida" : response.validation_status || response.execution_skip_reason || "Ejecutada"}
        />
      </div>

      {response.execution_skipped ? (
        <div className="skip-warning">
          El backend no ejecuto la consulta. Motivo:{" "}
          <strong>{response.execution_skip_reason || "no informado"}</strong>
        </div>
      ) : (
        <div className="execution-ok">El backend ejecuto la consulta validada.</div>
      )}

      {sql ? (
        <details open>
          <summary>SQL validado</summary>
          <pre>{sql}</pre>
        </details>
      ) : null}

      {!response.execution_skipped && rows.length > 0 ? (
        <div className="result-actions">
          <span>
            Mostrando {visibleRows.length} de {rows.length} filas. El Excel incluye las {rows.length} filas.
          </span>
          <button type="button" onClick={exportResults} disabled={isExporting}>
            {isExporting ? "Preparando Excel..." : "Descargar Excel"}
          </button>
        </div>
      ) : null}
      {exportError ? <p className="error-text" role="alert">{exportError}</p> : null}

      {rows.length > 0 ? (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                {columns.map((column) => (
                  <th key={column}>{column}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {visibleRows.map((row, index) => (
                <tr key={index}>
                  {columns.map((column) => (
                    <td key={column}>{formatCell(row[column])}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}

      <div className="trace-grid">
        <InfoBlock title="Tablas recuperadas" items={response.retrieved_tables || []} />
        <InfoBlock
          title="Advertencias"
          items={warnings.length > 0 ? warnings : ["Sin advertencias"]}
        />
        <InfoBlock
          title="Trazabilidad"
          items={[
            `Dominio: ${response.detected_domain || "no definido"}`,
            `Patron: ${response.detected_query_pattern || "no detectado"}`,
            `Ejecucion: ${
              response.execution_skipped
                ? response.execution_skip_reason || "dry-run"
                : "ejecutada"
            }`
          ]}
        />
        <InfoBlock
          title="Mappings"
          items={
            lookupValues.length > 0
              ? lookupValues.map((item) =>
                  [
                    item.source_table,
                    item.source_column,
                    item.fixed_filter_value,
                    item.canonical_value || item.matched_synonym
                  ]
                    .filter(Boolean)
                    .join(" / ")
                )
              : ["Sin mappings resueltos"]
          }
        />
      </div>
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="metric">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function InfoBlock({ title, items }: { title: string; items: string[] }) {
  return (
    <div className="info-block">
      <h3>{title}</h3>
      <ul>
        {items.map((item, index) => (
          <li key={`${item}-${index}`}>{item}</li>
        ))}
      </ul>
    </div>
  );
}

function buildAssistantText(response: QueryResponse) {
  const questions = response.clarification_questions || [];
  if (response.requires_user_confirmation) {
    return response.clarification_question || questions[0] || "Se requiere aclaracion.";
  }
  if (response.execution_skipped) {
    return `Consulta validada sin ejecucion. Motivo: ${response.execution_skip_reason || "no informado"}.`;
  }
  return "Consulta ejecutada.";
}

function readError(data: unknown) {
  if (typeof data === "object" && data !== null && "detail" in data) {
    const detail = (data as { detail?: unknown }).detail;
    return typeof detail === "string" ? detail : JSON.stringify(detail);
  }
  return "No se pudo procesar la consulta.";
}

function formatCell(value: unknown) {
  if (value === null || value === undefined) {
    return "";
  }
  const date = parseResultDate(value);
  if (date) {
    return new Intl.DateTimeFormat("es-CO", {
      timeZone: "UTC", day: "2-digit", month: "2-digit", year: "numeric",
      ...(typeof value === "string" && value.length === 10 ? {} : {
        hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false
      })
    }).format(date);
  }
  if (typeof value === "object") {
    return JSON.stringify(value);
  }
  return String(value);
}
