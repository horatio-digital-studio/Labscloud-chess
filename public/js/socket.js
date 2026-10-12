// One WebSocket per open game page, with reconnect, heartbeat and status reporting
// (REQ-UI-06, REQ-UI-07). Dependencies are injectable so node:test can drive it with fakes.

import { backoffDelay } from "./format.js";

export const HEARTBEAT_MS = 25_000;
export const HEARTBEAT_GRACE_MS = 10_000;
export const SIGNED_OUT_CLOSE = 1008;
export const CONNECT_TIMEOUT_MS = 10_000;

/**
 * Status values passed to onStatus(status, attempts):
 *   "connecting"   first connection, nothing received yet
 *   "live"         open and a `state` has arrived since opening
 *   "reconnecting" closed unexpectedly; retrying with back-off
 *   "signedout"    server closed with 1008, or the caller decided the session has gone
 */
export class GameSocket {
  constructor(options) {
    this.url = options.url;
    this.WebSocketImpl = options.WebSocketImpl || globalThis.WebSocket;
    this.setTimer = options.setTimeout || globalThis.setTimeout.bind(globalThis);
    this.clearTimer = options.clearTimeout || globalThis.clearTimeout.bind(globalThis);
    this.random = options.random || Math.random;
    this.onMessage = options.onMessage || (() => {});
    this.onStatus = options.onStatus || (() => {});
    this.onRepeatedFailure = options.onRepeatedFailure || (() => {});
    this.ws = null;
    this.status = "connecting";
    this.attempts = 0;
    this.stopped = false;
    this.retryTimer = null;
    this.heartbeatTimer = null;
    this.graceTimer = null;
    this.connectTimer = null;
    this.everLive = false;
  }

  start() {
    this.stopped = false;
    this._open();
  }

  stop() {
    this.stopped = true;
    this._clearTimers();
    this._detach(true);
  }

  /** Send a client message; returns false if the socket isn't open. */
  send(message) {
    const ws = this.ws;
    if (!ws || ws.readyState !== 1) return false;
    try {
      ws.send(JSON.stringify(message));
      return true;
    } catch (error) {
      this.reconnectNow();
      return false;
    }
  }

  /** Drop the current connection (if any) and connect again straight away. */
  reconnectNow() {
    if (this.stopped || this.status === "signedout") return;
    this._clearTimers();
    this._detach(true);
    this._setStatus(this.everLive ? "reconnecting" : "connecting");
    this._open();
  }

  /** Called on visibilitychange → visible and on `online`: retry now if not live. */
  wake() {
    if (this.stopped || this.status === "signedout") return;
    if (this.status === "live" && this.ws && this.ws.readyState === 1) {
      this._ping();
      return;
    }
    this.reconnectNow();
  }

  signedOut() {
    this.stopped = true;
    this._clearTimers();
    this._detach(true);
    this._setStatus("signedout");
  }

  // ---------------------------------------------------------------- internals

  _setStatus(status) {
    this.status = status;
    this.onStatus(status, this.attempts);
  }

  _open() {
    let ws;
    try {
      ws = new this.WebSocketImpl(this.url);
    } catch (error) {
      this._scheduleRetry();
      return;
    }
    this.ws = ws;
    // A half-open mobile connection can sit in CONNECTING for minutes; give up and retry.
    this.connectTimer = this.setTimer(() => {
      this.connectTimer = null;
      if (ws !== this.ws || ws.readyState === 1) return;
      this._detach(true);
      this._scheduleRetry();
    }, CONNECT_TIMEOUT_MS);
    ws.onopen = () => {
      if (ws !== this.ws) return;
      this._clearConnect();
      this.send({ type: "hello" });
      this._armHeartbeat();
    };
    ws.onmessage = (event) => {
      if (ws !== this.ws) return;
      this._clearGrace();
      let message;
      try {
        message = JSON.parse(event.data);
      } catch (error) {
        return;
      }
      if (message && message.type === "state" && this.status !== "live") {
        this.attempts = 0;
        this.everLive = true;
        this._setStatus("live");
      }
      this.onMessage(message);
    };
    ws.onclose = (event) => {
      if (ws !== this.ws) return;
      this._clearConnect();
      this._detach(false);
      if (event && event.code === SIGNED_OUT_CLOSE) {
        this.signedOut();
        return;
      }
      this._scheduleRetry();
    };
    ws.onerror = () => {
      // onclose always follows; reconnection is handled there.
    };
  }

  _scheduleRetry() {
    if (this.stopped) return;
    this._clearTimers();
    const delay = backoffDelay(this.attempts, this.random);
    this.attempts += 1;
    this._setStatus(this.everLive ? "reconnecting" : "connecting");
    if (this.attempts >= 3) this.onRepeatedFailure(this.attempts);
    this.retryTimer = this.setTimer(() => {
      this.retryTimer = null;
      if (!this.stopped) this._open();
    }, delay);
  }

  _armHeartbeat() {
    if (this.heartbeatTimer) this.clearTimer(this.heartbeatTimer);
    this.heartbeatTimer = this.setTimer(() => {
      this.heartbeatTimer = null;
      this._ping();
    }, HEARTBEAT_MS);
  }

  _ping() {
    if (!this.send({ type: "ping" })) return;
    this._clearGrace();
    this.graceTimer = this.setTimer(() => {
      this.graceTimer = null;
      this.reconnectNow(); // nothing came back: the connection is dead
    }, HEARTBEAT_GRACE_MS);
    this._armHeartbeat();
  }

  _clearConnect() {
    if (this.connectTimer) {
      this.clearTimer(this.connectTimer);
      this.connectTimer = null;
    }
  }

  _clearGrace() {
    if (this.graceTimer) {
      this.clearTimer(this.graceTimer);
      this.graceTimer = null;
    }
  }

  _clearTimers() {
    for (const name of ["retryTimer", "heartbeatTimer", "graceTimer", "connectTimer"]) {
      if (this[name]) {
        this.clearTimer(this[name]);
        this[name] = null;
      }
    }
  }

  _detach(close) {
    const ws = this.ws;
    this.ws = null;
    if (!ws) return;
    ws.onopen = null;
    ws.onmessage = null;
    ws.onclose = null;
    ws.onerror = null;
    if (close) {
      try {
        ws.close(1000, "client reconnecting");
      } catch (error) {
        // already closed
      }
    }
  }
}
