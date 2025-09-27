// tunnel.js
// Запускает LocalTunnel к http://localhost:8080, фиксированный сабдомен (если свободен),
// авто-ребут при обрыве, печатает URL и пингует для keep-alive.

const lt = require('localtunnel');

const PORT = 8080;
const SUB  = process.env.LT_SUBDOMAIN || 'mito-premium'; // можно поменять
const RETRY_MS = 5000;

async function start() {
  try {
    const tunnel = await lt({ port: PORT, subdomain: SUB });
    console.log(`[LT] tunnel up: ${tunnel.url}`);
    console.log(`[LT] webhook: ${tunnel.url}/tribute/webhook`);

    // лог обрыва
    tunnel.on('close', () => {
      console.log('[LT] tunnel closed, retrying…');
      setTimeout(start, RETRY_MS);
    });

    // пингуем раз в 60с (иногда полезно)
    setInterval(() => {
      fetch(`${tunnel.url}/`).catch(() => {});
    }, 60_000);

  } catch (e) {
    console.error('[LT] fail:', e?.message || e);
    setTimeout(start, RETRY_MS);
  }
}

start();
