import type { NextApiRequest, NextApiResponse } from "next";
import { postToBackend } from "../../lib/backendApi";

export default async function handler(req: NextApiRequest, res: NextApiResponse) {
  if (req.method !== "POST") {
    res.status(405).json({ detail: "Method not allowed" });
    return;
  }

  try {
    const response = await postToBackend("/query", req.body);

    const contentType = response.headers.get("content-type") || "";
    const data = contentType.includes("application/json")
      ? await response.json()
      : { detail: await response.text() };

    res.status(response.status).json(data);
  } catch (error) {
    const message = error instanceof Error ? error.message : "Error desconocido";
    res.status(502).json({
      detail: `No se pudo contactar el backend FastAPI: ${message}`
    });
  }
}
