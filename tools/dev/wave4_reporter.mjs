import { resolve } from 'node:path';
/** Count registered tests; Node's implicit file success is not collection. */
export default async function* reporter(events) {
  let count = 0;
  for await (const event of events) {
    const data = event.data;
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

