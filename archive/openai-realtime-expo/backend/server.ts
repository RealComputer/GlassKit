import http from "node:http";
import { text } from "node:stream/consumers";
import WebSocket from "ws";

const OPENAI_API_KEY =
  process.env.OPENAI_API_KEY ||
  (() => {
    throw new Error("Set OPENAI_API_KEY in env");
  })();
const PORT = Number(process.env.PORT ?? 3000);
const SESSION_INSTRUCTIONS = "You are a helpful and friendly voice assistant.";

http
  .createServer(async (req, res) => {
    try {
      const pathname = req.url ?? "/";

      if (req.method === "GET" && pathname === "/health") {
        res.writeHead(200, { "Content-Type": "text/plain" });
        res.end("ok");
        return;
      }

      if (req.method === "POST" && pathname === "/session") {
        await handleSessionRequest(req, res);
        return;
      }

      res.statusCode = 404;
      res.end("not found");
    } catch (err) {
      console.error(err);
      res.statusCode = 500;
      res.setHeader("Content-Type", "application/json");
      res.end(JSON.stringify({ error: "internal_error" }));
    }
  })
  .listen(PORT, () => {
    console.log(`server on :${PORT}`);
  });

const sessionConfig = {
  type: "realtime",
  model: "gpt-realtime",
  audio: {
    input: {
      noise_reduction: { type: "near_field" },
      transcription: { language: "en", model: "gpt-4o-mini-transcribe" },
      turn_detection: { type: "semantic_vad" },
    },
    output: { voice: "marin" },
  },
  instructions: SESSION_INSTRUCTIONS,
  tools: [
    {
      type: "function",
      name: "fetch_city_forecast",
      description: "Retrieve weather for a given city.",
      parameters: {
        type: "object",
        properties: {
          city: { type: "string", description: "Name of the city." },
        },
        required: ["city"],
      },
    },
  ],
} as const;

async function handleSessionRequest(
  req: http.IncomingMessage,
  res: http.ServerResponse<http.IncomingMessage>,
) {
  const sdp = await text(req);

  const fd = new FormData();
  fd.set("sdp", sdp);
  fd.set("session", JSON.stringify(sessionConfig));

  const upstream = await fetch("https://api.openai.com/v1/realtime/calls", {
    method: "POST",
    headers: { Authorization: `Bearer ${OPENAI_API_KEY}` },
    body: fd,
    signal: AbortSignal.timeout(10_000),
  });

  const callId = upstream.headers.get("location")?.split("/").pop();
  if (upstream.ok && callId) {
    startSideband(callId);
  }

  const body = await upstream.text();
  res.statusCode = upstream.status;
  res.setHeader(
    "Content-Type",
    upstream.headers.get("content-type") ?? "text/plain",
  );
  res.end(body);
}

function startSideband(callId: string) {
  const url = `wss://api.openai.com/v1/realtime?call_id=${callId}`;
  const ws = new WebSocket(url, {
    headers: { Authorization: `Bearer ${OPENAI_API_KEY}` },
  });

  ws.on("open", () => {
    console.log("sideband: connected", callId);
  });

  ws.on("message", async (raw) => {
    let msg: any;
    try {
      msg = JSON.parse(raw.toString());
    } catch {
      console.log("sideband: message parse error", raw.toString());
      return;
    }

    if (
      msg.type === "response.done" &&
      msg.response.status === "completed" &&
      msg.response.output[0].type === "function_call" &&
      msg.response.output[0].status === "completed"
    ) {
      const call = msg.response.output[0];
      console.log("response.done, tool call: ", call);

      const args = JSON.parse(call.arguments);

      try {
        const output = await runTool(call.name, args);
        ws.send(
          JSON.stringify({
            type: "conversation.item.create",
            item: {
              type: "function_call_output",
              call_id: call.call_id,
              output: JSON.stringify(output),
            },
          }),
        );
      } catch (error) {
        ws.send(
          JSON.stringify({
            type: "conversation.item.create",
            item: {
              type: "function_call_output",
              call_id: call.call_id,
              output: JSON.stringify({
                error: error instanceof Error ? error.message : String(error),
              }),
            },
          }),
        );
      }

      ws.send(JSON.stringify({ type: "response.create" }));
      return;
    }

    console.error("sideband: unhandled type", msg.type);
  });

  ws.on("close", (code, reason) => {
    console.log("sideband: closed", callId, code, reason.toString());
  });
  ws.on("error", (error) => console.error("sideband error: error", error));
}

async function runTool(
  name: string,
  args: Record<string, unknown>,
): Promise<Record<string, unknown>> {
  switch (name) {
    case "fetch_city_forecast":
      return fetchCityForecast(args);
    default:
      return { error: `unknown tool: ${name}` };
  }
}

async function fetchCityForecast(args: Record<string, unknown>) {
  const city = args.city;
  const normalizedCity =
    typeof city === "string" ? city.trim() : String(city ?? "").trim();
  if (!normalizedCity) {
    throw new Error("city is required");
  }
  await new Promise((resolve) => setTimeout(resolve, 1000));
  return { city: normalizedCity, forecast: "Sunny" };
}
