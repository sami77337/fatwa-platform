import {permitted as upstream} from "../fast8_browser_conformance/policy.mjs";

export function permitted(request,origin,catalog = false) {
  try {
    const url = new URL(request.url);
    return upstream(request,origin,catalog) ||
      ["GET","HEAD"].includes(request.method) && url.origin === origin &&
      !url.username && !url.password && !/%|\\/.test(url.pathname) &&
      /^\/dev\/operator-navigation(?:\/(?:[a-z0-9-]+|style\.css))?$/.test(url.pathname);
  } catch { return false; }
}
