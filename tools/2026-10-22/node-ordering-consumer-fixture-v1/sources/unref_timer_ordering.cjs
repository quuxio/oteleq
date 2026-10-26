'use strict';

const fs = require('node:fs');
const { performance } = require('node:perf_hooks');

function selected(n) {
  return n + 1;
}

fs.writeSync(1, 'main:' + selected(7) + '\n');
setTimeout(() => fs.writeSync(1, 'TIMER\n'), 0).unref();

// Let the timer become due before the first event-loop turn.
const deadlineMs = performance.now() + 20;
while (performance.now() < deadlineMs) {
  // Deliberate synchronous application work; no handles are introduced.
}

setImmediate(() => fs.writeSync(1, 'IMMEDIATE\n'));
