const { Client, LocalAuth } = require("whatsapp-web.js");
const client = new Client({ puppeteer: { headless: true } });
client.on("qr", () => console.log("QR received"));
client.on("ready", () => console.log("Client ready"));
client.initialize().then(() => console.log("Initialize block resolved!"));
console.log("Called client.initialize()");
