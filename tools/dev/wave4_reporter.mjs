import { resolve } from 'node:path';
/** Count registered tests; Node's implicit file success is not collection. */
const socketProbe = /^C6_SOCKET_HANG rejection=(?:matched|wrong-code|wrong-stage|none) stage=(?:profile|port-file|target-discovery|websocket|ready) cleanup=(?:PASS|FAIL|pending) elapsed_ms=\d{1,8} profile=(?:unchecked|checking|removed)$/;

export default async function* reporter(events) {
  let count = 0;
  for await (const event of events) {
    const data = event.data;
    // Forward only the fixed probe values. Node error messages may contain paths/URLs.
    if (event.type === 'test:diagnostic' && socketProbe.test(data.message))
      yield `${data.message}\n`;
    if (event.type === 'test:pass' || event.type === 'test:fail') {
      // Node emits implicit file successes; exclude their path-based names.
      if (data.file && resolve(data.name) !== resolve(data.file) && data.details?.type !== 'suite' && !data.skip && !data.todo) count++;
      yield `${event.type}: ${String(data.name).slice(0, 500)}\n`;
    }
    if (event.type === 'test:summary' && data.file === undefined) {
      yield `D6_REGISTERED_TESTS=${count}\n`;
    }
  }
}

