/* The few lines every Node test here shares: check(label, got, want) prints
   ok or FAIL, done() prints the count and sets the exit status. */
let checks = 0;
const failures = [];

function check(label, got, want = true) {
  checks++;
  const ok = JSON.stringify(got) === JSON.stringify(want);
  console.log(`${ok ? 'ok  ' : 'FAIL'}  ${label}${ok ? '' : `: ${JSON.stringify(got)} (expected ${JSON.stringify(want)})`}`);
  if (!ok) failures.push(label);
}

function done() {
  console.log(`\n${checks - failures.length} of ${checks} checks passed`);
  if (failures.length) {
    console.log(`FAILED:\n  ${failures.join('\n  ')}`);
    process.exit(1);
  }
}

module.exports = { check, done };
