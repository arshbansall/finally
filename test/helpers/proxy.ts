import http from 'node:http';
import type { AddressInfo, Socket } from 'node:net';

/**
 * Minimal HTTP pass-through proxy in front of the app, so a test can drop the live
 * SSE connection at the TCP level (which browser offline emulation does not do for an
 * already-open EventSource) and refuse reconnects until released.
 */
export interface StreamProxy {
  url: string;
  /** Destroy open price-stream sockets and kill reconnect attempts until `restore()`. */
  dropStream(): void;
  restore(): void;
  close(): Promise<void>;
}

export async function startStreamProxy(target: string): Promise<StreamProxy> {
  const upstreamUrl = new URL(target);
  const streamSockets = new Set<Socket>();
  const allSockets = new Set<Socket>();
  let blocked = false;

  const isStream = (path = '') => path.startsWith('/api/stream/');

  const server = http.createServer((req, res) => {
    if (isStream(req.url)) {
      if (blocked) {
        req.socket.destroy();
        return;
      }
      streamSockets.add(req.socket);
      req.socket.once('close', () => streamSockets.delete(req.socket));
    }
    const upstream = http.request(
      {
        hostname: upstreamUrl.hostname,
        port: upstreamUrl.port || 80,
        path: req.url,
        method: req.method,
        headers: { ...req.headers, host: upstreamUrl.host },
      },
      (upRes) => {
        res.writeHead(upRes.statusCode ?? 502, upRes.headers);
        upRes.pipe(res);
        res.once('close', () => upRes.destroy());
      },
    );
    upstream.on('error', () => res.destroy());
    req.pipe(upstream);
  });
  server.on('connection', (socket) => {
    allSockets.add(socket);
    socket.once('close', () => allSockets.delete(socket));
  });

  await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve));
  const { port } = server.address() as AddressInfo;

  return {
    url: `http://127.0.0.1:${port}`,
    dropStream() {
      blocked = true;
      for (const s of streamSockets) s.destroy();
    },
    restore() {
      blocked = false;
    },
    close() {
      for (const s of allSockets) s.destroy();
      return new Promise((resolve) => server.close(() => resolve()));
    },
  };
}
