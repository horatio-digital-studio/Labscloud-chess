import assert from "node:assert/strict";
import { test } from "node:test";

import {
  CONNECT_TIMEOUT_MS,
  GameSocket,
  HEARTBEAT_GRACE_MS,
  HEARTBEAT_MS,
} from "../../public/js/socket.js";

class Clock {
  constructor() {
    this.now = 0;
    this.timers = new Map();
    this.next = 1;
  }
  setTimeout = (fn, ms) => {
    const id = this.next++;
    this.timers.set(id, { at: this.now + ms, fn });
    return id;
  };
  clearTimeout = (id) => {
    this.timers.delete(id);
  };
  advance(ms) {
    const until = this.now + ms;
    for (;;) {
      const due = [...this.timers.entries()].filter(([, t]) => t.at <= until).sort((a, b) => a[1].at - b[1].at)[0];
      if (!due) break;
      this.timers.delete(due[0]);
      this.now = due[1].at;
      due[1].fn();
    }
    this.now = until;
  }
}

function harness() {
  const sockets = [];
  class FakeWS {
    constructor(url) {
      this.url = url;
      this.readyState = 0;
      this.sent = [];
      this.closed = null;
      sockets.push(this);
    }
    send(text) {
      this.sent.push(JSON.parse(text));
    }
    close(code) {
      this.closed = code;
      this.readyState = 3;
    }
    open() {
      this.readyState = 1;
      this.onopen?.();
    }
    receive(message) {
      this.onmessage?.({ data: JSON.stringify(message) });
    }
    drop(code = 1006) {
      this.readyState = 3;
      this.onclose?.({ code });
    }
  }
  const clock = new Clock();
  const statuses = [];
  const messages = [];
  let failures = 0;
  const socket = new GameSocket({
    url: "wss://example/ws/games/x",
    WebSocketImpl: FakeWS,
    setTimeout: clock.setTimeout,
    clearTimeout: clock.clearTimeout,
    random: () => 0.5,
    onMessage: (m) => messages.push(m),
    onStatus: (s, attempts) => statuses.push([s, attempts]),
    onRepeatedFailure: () => {
      failures += 1;
    },
  });
  return { socket, sockets, clock, statuses, messages, failures: () => failures };
}

test("sends hello on every connect and goes live on the first state", () => {
  const h = harness();
  h.socket.start();
  h.sockets[0].open();
  assert.deepEqual(h.sockets[0].sent, [{ type: "hello" }]);
  assert.equal(h.socket.status, "connecting");
  h.sockets[0].receive({ type: "presence", online: {} });
  assert.equal(h.socket.status, "connecting"); // only a state means "synced"
  h.sockets[0].receive({ type: "state", ply: 0 });
  assert.equal(h.socket.status, "live");
  assert.equal(h.messages.length, 2);
});

test("reconnects with back-off and says hello again (REQ-UI-07)", () => {
  const h = harness();
  h.socket.start();
  h.sockets[0].open();
  h.sockets[0].receive({ type: "state" });
  h.sockets[0].drop();
  assert.equal(h.socket.status, "reconnecting");
  h.clock.advance(499);
  assert.equal(h.sockets.length, 1);
  h.clock.advance(1);
  assert.equal(h.sockets.length, 2);
  h.sockets[1].drop();
  h.clock.advance(999);
  assert.equal(h.sockets.length, 2);
  h.clock.advance(1);
  assert.equal(h.sockets.length, 3);
  h.sockets[2].open();
  assert.deepEqual(h.sockets[2].sent, [{ type: "hello" }]);
  h.sockets[2].receive({ type: "state" });
  assert.equal(h.socket.status, "live");
  assert.equal(h.socket.attempts, 0);
});

test("delays cap at 8 s and repeated failures are reported", () => {
  const h = harness();
  h.socket.start();
  const delays = [];
  for (let i = 0; i < 7; i += 1) {
    const before = h.clock.now;
    h.sockets[h.sockets.length - 1].drop();
    const count = h.sockets.length;
    while (h.sockets.length === count) h.clock.advance(100);
    delays.push(h.clock.now - before);
  }
  assert.deepEqual(delays, [500, 1000, 2000, 4000, 8000, 8000, 8000]);
  assert.ok(h.failures() >= 1);
});

test("close code 1008 means signed out: no more retries", () => {
  const h = harness();
  h.socket.start();
  h.sockets[0].open();
  h.sockets[0].drop(1008);
  assert.equal(h.socket.status, "signedout");
  h.clock.advance(60_000);
  assert.equal(h.sockets.length, 1);
  h.socket.wake();
  assert.equal(h.sockets.length, 1);
});

test("a silent connection is replaced after a missed heartbeat", () => {
  const h = harness();
  h.socket.start();
  h.sockets[0].open();
  h.sockets[0].receive({ type: "state" });
  h.clock.advance(HEARTBEAT_MS);
  assert.deepEqual(h.sockets[0].sent.at(-1), { type: "ping" });
  h.clock.advance(HEARTBEAT_GRACE_MS - 1);
  assert.equal(h.sockets.length, 1);
  h.clock.advance(1);
  assert.equal(h.sockets.length, 2);
  assert.equal(h.sockets[0].closed, 1000);
});

test("a pong keeps the connection", () => {
  const h = harness();
  h.socket.start();
  h.sockets[0].open();
  h.sockets[0].receive({ type: "state" });
  h.clock.advance(HEARTBEAT_MS);
  h.sockets[0].receive({ type: "pong", t: 1 });
  h.clock.advance(HEARTBEAT_GRACE_MS * 2);
  assert.equal(h.sockets.length, 1);
});

test("wake reconnects at once when not live, pings when live", () => {
  const h = harness();
  h.socket.start();
  h.sockets[0].drop();
  h.socket.wake();
  assert.equal(h.sockets.length, 2);
  h.sockets[1].open();
  h.sockets[1].receive({ type: "state" });
  h.socket.wake();
  assert.equal(h.sockets.length, 2);
  assert.deepEqual(h.sockets[1].sent.at(-1), { type: "ping" });
});

test("send reports failure when not open, and stale sockets are ignored", () => {
  const h = harness();
  h.socket.start();
  assert.equal(h.socket.send({ type: "resign" }), false);
  h.sockets[0].open();
  assert.equal(h.socket.send({ type: "resign" }), true);
  const old = h.sockets[0];
  h.socket.reconnectNow();
  old.receive({ type: "state" }); // a late message from the replaced socket
  assert.equal(h.messages.length, 0);
});

test("a connection stuck in CONNECTING is abandoned and retried", () => {
  const h = harness();
  h.socket.start();
  h.clock.advance(CONNECT_TIMEOUT_MS - 1);
  assert.equal(h.sockets.length, 1);
  h.clock.advance(1);
  assert.equal(h.sockets[0].closed, 1000);
  h.clock.advance(500);
  assert.equal(h.sockets.length, 2);
  h.sockets[1].open();
  h.clock.advance(CONNECT_TIMEOUT_MS * 2); // an open socket is not timed out
  assert.equal(h.sockets.length, 2);
});
