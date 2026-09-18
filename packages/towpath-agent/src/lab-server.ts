import { createServer, type IncomingMessage } from 'node:http';
import { AgentError } from './contracts.js';
import type { LabChat } from './lab-chat.js';

async function readBody(request: IncomingMessage) {
  let size = 0;
  const chunks: Buffer[] = [];
  for await (const chunk of request) {
    size += chunk.length;
    if (size > 8192) throw new Error('payload_limit');
    chunks.push(chunk);
  }
  const body: unknown = JSON.parse(Buffer.concat(chunks).toString('utf8'));
  if (!body || typeof body !== 'object' || Array.isArray(body)) throw new AgentError('invalid_request');
  return body as Record<string, unknown>;
}

export function createLabServer(chat: LabChat, page: string, token: string) {
  return createServer(async (request, response) => {
    response.setHeader('Cache-Control', 'no-store');
    response.setHeader('X-Content-Type-Options', 'nosniff');
    response.setHeader('Content-Security-Policy', "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'self'; frame-ancestors 'none'");
    const host = request.headers.host ?? '';
    const allowedHosts = [`127.0.0.1:${request.socket.localPort}`, `localhost:${request.socket.localPort}`];
    if (!allowedHosts.includes(host)
      || (request.headers.origin && request.headers.origin !== `http://${host}`)) {
      response.writeHead(403).end(); return;
    }
    if (request.method === 'GET' && request.url === '/') {
      response.setHeader('Content-Type', 'text/html; charset=utf-8');
      response.end(page.replace('__LAB_TOKEN__', token)); return;
    }
    if (request.method !== 'POST' || !['/chat', '/reset', '/cancel'].includes(request.url ?? '')) {
      response.writeHead(404).end(); return;
    }
    if (request.headers['x-lab-token'] !== token
      || request.headers['content-type'] !== 'application/json') {
      response.writeHead(403).end(); return;
    }
    const controller = new AbortController();
    response.on('close', () => controller.abort());
    try {
      const body = await readBody(request);
      if (request.url === '/reset') { chat.reset(); response.end('{}'); return; }
      if (request.url === '/cancel') { chat.cancel(); response.end('{}'); return; }
      if (typeof body.message !== 'string' || Object.keys(body).length !== 1) {
        throw new AgentError('invalid_request');
      }
      response.setHeader('Content-Type', 'application/x-ndjson');
      await chat.send(body.message, event => {
        if (controller.signal.aborted) return;
        if (!response.write(JSON.stringify(event) + '\n')) controller.abort();
      }, controller.signal);
      response.end();
    } catch (error) {
      const message = error instanceof Error ? error.message : '';
      const code = error instanceof AgentError ? error.code
        : message.startsWith('context_full') ? 'context_full'
          : message === 'payload_limit' ? 'payload_limit' : 'invalid_request';
      if (!response.headersSent) response.statusCode = code === 'payload_limit' ? 413 : code === 'busy' ? 409 : 400;
      if (!response.destroyed) response.end(JSON.stringify({ type: 'error', data: { code } }) + '\n');
    }
  });
}
