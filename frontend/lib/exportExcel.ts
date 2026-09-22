type ResultRow = Record<string, unknown>;

export function getResultColumns(rows: ResultRow[]): string[] {
  return Array.from(new Set(rows.flatMap((row) => Object.keys(row))));
}

// Preserve Oracle's displayed clock time: Excel dates have no time zone.
export function parseResultDate(value: unknown): Date | null {
  if (value instanceof Date) return Number.isNaN(value.getTime()) ? null : value;
  if (typeof value !== "string") return null;
  const match = /^(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2}):(\d{2})(?:\.(\d{1,9}))?(?:Z|[+-]\d{2}:\d{2})?)?$/.exec(value);
  if (!match) return null;
  const [, year, month, day, hour = "0", minute = "0", second = "0", fraction = ""] = match;
  const date = new Date(0);
  date.setUTCFullYear(Number(year), Number(month) - 1, Number(day));
  date.setUTCHours(Number(hour), Number(minute), Number(second), Number(fraction.padEnd(3, "0").slice(0, 3)));
  if (Number(year) < 1900 || date.getUTCFullYear() !== Number(year) ||
      date.getUTCMonth() !== Number(month) - 1 || date.getUTCDate() !== Number(day) ||
      date.getUTCHours() !== Number(hour) || date.getUTCMinutes() !== Number(minute) ||
      date.getUTCSeconds() !== Number(second)) return null;
  return date;
}

function excelValue(value: unknown): string | number | boolean | Date | null {
  if (value === null || value === undefined) return null;
  const date = parseResultDate(value);
  if (date) return date;
  if (typeof value === "string" || typeof value === "boolean") return value;
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

export async function buildResultsExcel(rows: ResultRow[]): Promise<Uint8Array<ArrayBuffer>> {
  if (rows.length === 0) throw new Error("No hay resultados para descargar.");

  const { default: ExcelJS } = await import("exceljs");
  const workbook = new ExcelJS.Workbook();
  const sheet = workbook.addWorksheet("Resultados");
  const columns = getResultColumns(rows);
  sheet.addRow(columns);
  for (const row of rows) {
    // Strings remain literal text, including codes with leading zeros and '='.
    const excelRow = sheet.addRow(columns.map((column) => excelValue(row[column])));
    excelRow.eachCell((cell, index) => {
      if (cell.value instanceof Date) {
        const original = row[columns[index - 1]];
        cell.numFmt = typeof original === "string" && original.length === 10
          ? "dd/mm/yyyy" : "dd/mm/yyyy hh:mm:ss";
      }
    });
  }
  sheet.getRow(1).font = { bold: true, color: { argb: "FFFFFFFF" } };
  sheet.getRow(1).fill = {
    type: "pattern", pattern: "solid", fgColor: { argb: "FF176B63" }
  };
  sheet.views = [{ state: "frozen", ySplit: 1 }];
  sheet.autoFilter = { from: { row: 1, column: 1 }, to: { row: 1, column: columns.length } };
  columns.forEach((name, index) => {
    sheet.getColumn(index + 1).width = Math.min(45, Math.max(22, name.length + 2));
  });
  const buffer = await workbook.xlsx.writeBuffer();
  return new Uint8Array(buffer);
}

export async function downloadResultsExcel(rows: ResultRow[]): Promise<void> {
  const bytes = await buildResultsExcel(rows);
  const blob = new Blob([bytes], {
    type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
  });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `resultados_consulta_${new Date().toISOString().replace(/[:.]/g, "-")}.xlsx`;
  document.body.appendChild(link);
  try {
    link.click();
  } finally {
    link.remove();
    window.setTimeout(() => URL.revokeObjectURL(url), 60_000);
  }
}
