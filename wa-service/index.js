/**
 * WhatsApp Web.js sidecar — HTTP API consumed by the Python FastAPI backend.
 *
 * Each user gets their own wwebjs Client with LocalAuth for session persistence.
 * Endpoints mirror the existing Python bot.py interface so the FastAPI router
 * and scheduler need zero changes.
 */

const express = require("express");
const { Client, LocalAuth } = require("whatsapp-web.js");
const QRCode = require("qrcode");
const puppeteer = require("puppeteer");

const app = express();
app.use(express.json());

// Log incoming HTTP requests from the Python backend
app.use((req, res, next) => {
  console.log(`[HTTP] ${req.method} ${req.url}`);
  next();
});

const PORT = process.env.WA_SERVICE_PORT || 3001;
const AUTH_DIR = process.env.WA_AUTH_DIR || "./.wwebjs_auth";

// ── In-memory session registry ──────────────────────────────────────────────

/** @type {Map<string, {client: Client, qr: string|null, ready: boolean, lastError: string|null, initializing: boolean}>} */
const sessions = new Map();

/**
 * Build Puppeteer launch args optimised for free-tier containers (512 MB RAM).
 */
function puppeteerArgs() {
  const args = [
    "--no-sandbox",
    "--disable-setuid-sandbox",
    "--disable-dev-shm-usage",
    "--disable-gpu",
    "--disable-software-rasterizer",
    "--disable-extensions",
    "--disable-background-networking",
    "--disable-sync",
    "--disable-default-apps",
    "--mute-audio",
    "--no-first-run",
    "--disable-accelerated-2d-canvas",
  ];

  // --single-process and --no-zygote crash Chromium on Windows.
  // Only apply them on Linux (i.e. production containers like Render).
  if (process.platform !== "win32") {
    args.push("--no-zygote", "--single-process");
  }

  return args;
}

/**
 * Create (or return existing) wwebjs client for a user.
 */
function getOrCreateSession(userId) {
  if (sessions.has(userId)) return sessions.get(userId);

  const session = {
    client: null,
    qr: null,
    ready: false,
    lastError: null,
    initializing: false,
  };
  sessions.set(userId, session);
  return session;
}

/**
 * Initialise a wwebjs Client for a given userId.
 */
async function initClient(userId) {
  const session = getOrCreateSession(userId);

  // Already running or being initialised
  if (session.ready || session.initializing) return session;

  session.initializing = true;
  session.lastError = null;
  session.qr = null;

  try {
    const client = new Client({
      authStrategy: new LocalAuth({
        clientId: userId,
        dataPath: AUTH_DIR,
      }),
      puppeteer: {
        headless: true,
        args: puppeteerArgs(),
        executablePath: puppeteer.executablePath(),
      },
    });

    // ── Events ────────────────────────────────────────────────────────────

    client.on("qr", async (qr) => {
      console.log(`[${userId}] QR received`);
      try {
        // Convert the QR string to a base64 PNG image
        session.qr = await QRCode.toDataURL(qr, { width: 256, margin: 2 });
        // Strip the data:image/png;base64, prefix so Python gets raw base64
        session.qr = session.qr.replace(/^data:image\/png;base64,/, "");
      } catch (err) {
        console.error(`[${userId}] QR encode error:`, err);
        session.qr = null;
      }
    });

    client.on("ready", () => {
      console.log(`[${userId}] Client ready — session authenticated`);
      session.ready = true;
      session.qr = null;
      session.lastError = null;
    });

    client.on("authenticated", () => {
      console.log(`[${userId}] Authenticated`);
    });

    client.on("auth_failure", (msg) => {
      console.error(`[${userId}] Auth failure:`, msg);
      session.lastError = `Auth failure: ${msg}`;
      session.ready = false;
    });

    client.on("disconnected", (reason) => {
      console.log(`[${userId}] Disconnected:`, reason);
      session.ready = false;
      session.lastError = `Disconnected: ${reason}`;
      // Clean up
      sessions.delete(userId);
    });

    session.client = client;
    await client.initialize();
    console.log(`[${userId}] Client initializing…`);
  } catch (err) {
    console.error(`[${userId}] Init error:`, err);
    session.lastError = err.message || String(err);
    session.ready = false;
    session.client = null;
  } finally {
    session.initializing = false;
  }

  return session;
}

// ── REST API ────────────────────────────────────────────────────────────────

// Health check
app.get("/health", (_req, res) => {
  res.json({ status: "ok", sessions: sessions.size });
});

// Initialise a session (starts Puppeteer + emits QR)
app.post("/session/init", async (req, res) => {
  const { userId } = req.body;
  if (!userId) return res.status(400).json({ error: "userId required" });

  try {
    const session = await initClient(userId);
    res.json({
      ready: session.ready,
      hasQr: session.qr !== null,
      error: session.lastError,
    });
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

// Get QR code as base64 PNG
app.get("/session/:userId/qr", (req, res) => {
  const session = sessions.get(req.params.userId);
  if (!session) return res.json({ qr: null, ready: false, error: "Session not initialised" });
  res.json({ qr: session.qr, ready: session.ready, error: session.lastError });
});

// Get session status
app.get("/session/:userId/status", (req, res) => {
  const session = sessions.get(req.params.userId);
  if (!session) return res.json({ ready: false, initializing: false, error: null });
  res.json({
    ready: session.ready,
    initializing: session.initializing,
    error: session.lastError,
  });
});

// Send a message to a group (by group name)
app.post("/session/:userId/send", async (req, res) => {
  const session = sessions.get(req.params.userId);
  if (!session || !session.client || !session.ready) {
    return res.status(400).json({ success: false, error: "Session not ready" });
  }

  const { groupName, message } = req.body;
  if (!groupName || !message) {
    return res.status(400).json({ success: false, error: "groupName and message required" });
  }

  try {
    // Get all chats and find the group
    const chats = await session.client.getChats();
    let targetChat = null;

    // Exact match first
    targetChat = chats.find(
      (c) => c.isGroup && c.name.trim() === groupName.trim()
    );

    // Partial match fallback
    if (!targetChat) {
      targetChat = chats.find(
        (c) =>
          c.isGroup &&
          c.name.toLowerCase().includes(groupName.toLowerCase())
      );
    }

    if (!targetChat) {
      return res.status(404).json({ success: false, error: `Group '${groupName}' not found` });
    }

    await targetChat.sendMessage(message);
    console.log(`[${req.params.userId}] Message sent to '${groupName}'`);
    res.json({ success: true });
  } catch (err) {
    console.error(`[${req.params.userId}] Send error:`, err);
    res.status(500).json({ success: false, error: err.message });
  }
});

// Destroy (unlink) a session
app.post("/session/:userId/destroy", async (req, res) => {
  const session = sessions.get(req.params.userId);
  if (session && session.client) {
    try {
      await session.client.destroy();
    } catch (err) {
      console.error(`[${req.params.userId}] Destroy error:`, err);
    }
  }
  sessions.delete(req.params.userId);
  console.log(`[${req.params.userId}] Session destroyed`);
  res.json({ success: true });
});

// ── Start ───────────────────────────────────────────────────────────────────

app.listen(PORT, () => {
  console.log(`WhatsApp sidecar running on port ${PORT}`);
});
