import http from "node:http";
import { readdir, readFile } from "node:fs/promises";
import { text } from "node:stream/consumers";
import WebSocket from "ws";

const OPENAI_API_KEY =
  process.env.OPENAI_API_KEY ||
  (() => {
    throw new Error("Set OPENAI_API_KEY in env");
  })();
const PORT = Number(process.env.PORT ?? 3000);
const SESSION_INSTRUCTIONS = `
# Role
- You are a helpful and cheerful expert assembly assistant.
- Your goal is to guide the user through completing an assembly project by giving step-by-step, interactive instructions.

# Personality
- Your responses should be clear, concise, and actionable.
- Limit each response to at most 3 sentences.
- Both you and the user communicate only in English.
- Always rely on the latest real-time video frame provided, which shows the current situation, and EXAMINE IT CAREFULLY before responding.
- Vary your responses for variety so they do not sound robotic.

# Rules
## Conversation Flow
### 1) Identify the item & Load instructions
- When the user first asks for help assembling a specific item, call the tools as described in the "Tools" section below.
- Use the user's description and the latest video frame to identify which item from "list_items" is being assembled and select that item for "load_item_instructions".

### 2) Guide the user
- Guide the user step by step, providing the next step, answering questions, and correcting errors based on the instructions loaded.
- Each step from the "Assembly Instructions" in the loaded instructions can be used in your response as is. Do not include multiple steps in one response; give only one step at a time.
- Always describe the appearance of each part (e.g., size, shape) to avoid confusion.
- PAY EXTRA ATTENTION to the user selecting the correct parts. After the user corrects a mistake, guide them back to the defined steps.
- Continue until all steps are completed or the user confirms completion.

### 3) End
- When the assembly is complete, congratulate the user.

## Audio
- Only respond to clear voice audio.
- Do not include any sound effects or onomatopoeic expressions in your responses.

## Clarification
- If the user's voice audio is heard but unclear (e.g., ambiguous input/unintelligible) or if you did not understand the user, ask for clarification, e.g., "I didn't hear that clearly—could you say it again?"
- If the video frame is unclear or unframed, ask for clarification, e.g., "I didn't get a clear look—could you show it again?"

# Tools
- When the user first asks for help with assembling a specific item, you MUST call the "list_items()" and "load_item_instructions(item_name)" tools sequentially before giving any assembly steps for that item.
- Before these tool calls, in the same turn, say one short line like "I'm looking up the instructions now." Then call these tools immediately.
- After you have successfully loaded instructions for that item, do not call these tools again unless the user wants to switch to a different item or the previous item choice was incorrect.
- When calling tools, do not ask for any user confirmation. Be proactive.
`.trim();
const ITEM_DATA_DIR = new URL("./items/", import.meta.url);

http
  .createServer(async (req, res) => {
    try {
      const pathname = req.url ?? "/";

      console.log(`request: ${req.method} ${pathname}`);

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
      transcription: { language: "en", model: "whisper-1" },
      turn_detection: { type: "semantic_vad" },
    },
    output: { voice: "marin" },
  },
  instructions: SESSION_INSTRUCTIONS,
  tools: [
    {
      type: "function",
      name: "list_items",
      description:
        "List all available item names for which assembly instructions exist. Returns an array of strings; each string is a valid `item_name` that can be passed to `load_item_instructions`.",
    },
    {
      type: "function",
      name: "load_item_instructions",
      description:
        "Load the assembly instructions for the given item name. Returns the full text content for that item.",
      parameters: {
        type: "object",
        properties: {
          item_name: {
            type: "string",
            description:
              "An item name chosen from the array returned by `list_items`; must match one of those strings.",
          },
        },
        required: ["item_name"],
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

    const fnCall = msg.response?.output?.find(
      (o: any) => o.type === "function_call" && o.status === "completed",
    );

    if (
      msg.type === "response.done" &&
      msg.response?.status === "completed" &&
      fnCall
    ) {
      const call = fnCall;
      console.log("tool call: ", JSON.stringify(call));

      const args = JSON.parse(call.arguments);

      try {
        const output = await runTool(call.name, args);
        ws.send(
          JSON.stringify({
            type: "conversation.item.create",
            item: {
              type: "function_call_output",
              call_id: call.call_id,
              output: output,
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

    // console.log("sideband: unhandled type", msg.type);
  });

  ws.on("close", (code, reason) => {
    console.log("sideband: closed", callId, code, reason.toString());
  });
  ws.on("error", (error) => console.error("sideband error: error", error));
}

async function runTool(
  name: string,
  args: Record<string, unknown>,
): Promise<string> {
  switch (name) {
    case "list_items":
      return JSON.stringify(await listItems());
    case "load_item_instructions":
      return await loadItemInstructions(args);
    default:
      return `Error: unknown tool "${name}"`;
  }
}

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

async function listItems() {
  await sleep(1500);
  const items = await listItemNames();
  return items;
}

async function loadItemInstructions(args: Record<string, unknown>) {
  const rawName =
    typeof args.item_name === "string"
      ? args.item_name
      : String(args.item_name ?? "");
  const requestedName = rawName.trim();

  if (!requestedName) {
    throw new Error("item_name is required");
  }

  const available = await listItemNames();
  const match = available.find(
    (name) => name.toLowerCase() === requestedName.toLowerCase(),
  );

  if (!match) {
    if (!available.length) {
      throw new Error(`Unknown item: ${requestedName}. No item files found.`);
    }

    throw new Error(
      `Unknown item: ${requestedName}. Available items: ${available.join(", ")}`,
    );
  }

  const content = await readFile(
    new URL(`${match}.txt`, ITEM_DATA_DIR),
    "utf8",
  );

  return content;
}

async function listItemNames(): Promise<string[]> {
  try {
    const entries = await readdir(ITEM_DATA_DIR, { withFileTypes: true });

    return entries
      .filter(
        (entry) => entry.isFile() && entry.name.toLowerCase().endsWith(".txt"),
      )
      .map((entry) => entry.name.replace(/\.txt$/i, ""))
      .sort((a, b) => a.localeCompare(b));
  } catch (error) {
    const err = error as NodeJS.ErrnoException;
    if (err.code === "ENOENT") {
      return [];
    }

    throw error;
  }
}
