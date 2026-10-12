// Small fetch wrapper for the REST API (docs/protocol.md §2).

export class ApiError extends Error {
  constructor(status, code, message) {
    super(message || code || `HTTP ${status}`);
    this.status = status;
    this.code = code || "INTERNAL";
  }
}

async function request(method, path, body) {
  const init = {
    method,
    credentials: "same-origin",
    headers: { accept: "application/json" },
    cache: "no-store",
    // An expired Cloudflare Access session answers with a redirect to the login page;
    // don't follow it cross-origin, report it as "signed out" instead.
    redirect: "manual",
  };
  if (body !== undefined) {
    init.headers["content-type"] = "application/json";
    init.body = JSON.stringify(body);
  }
  let response;
  try {
    response = await fetch(path, init);
  } catch (error) {
    throw new ApiError(0, "NETWORK", "You appear to be offline.");
  }
  if (response.type === "opaqueredirect" || (response.status >= 300 && response.status < 400)) {
    throw new ApiError(401, "SIGNED_OUT", "Please sign in again.");
  }
  let payload = null;
  try {
    payload = await response.json();
  } catch (error) {
    payload = null;
  }
  if (!response.ok) {
    const info = payload && payload.error ? payload.error : {};
    throw new ApiError(response.status, info.code, info.message);
  }
  return payload;
}

export const api = {
  me: () => request("GET", "/api/me"),
  updateMe: (body) => request("PATCH", "/api/me", body),
  games: () => request("GET", "/api/games"),
  createGame: (colour) => request("POST", "/api/games", { colour }),
  stats: () => request("GET", "/api/stats"),
  game: (id) => request("GET", `/api/games/${encodeURIComponent(id)}`),
};

/** True when the response means the Access session has gone (sign in again). */
export function isSignedOut(error) {
  return (
    error instanceof ApiError &&
    (error.code === "SIGNED_OUT" || (error.status === 403 && error.code === "UNAUTHORISED"))
  );
}
