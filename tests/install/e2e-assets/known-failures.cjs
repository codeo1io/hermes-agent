const fs = require('node:fs')
const path = require('node:path')
const rules = require('./known-failures.json')

function matchKnownFailure({ platform, phase, commit, installMethod, updateMethod, error, logs }) {
  if (!/^[0-9a-f]{40}$/.test(commit || '')) return null
  return rules.find(rule => {
    // Platform and phase are opt-in dimensions: legacy rules (no field) keep
    // their historical windows/update-only semantics so old receipts stay
    // reproducible; new rules declare exactly where they apply.
    const platforms = rule.platforms || ['windows']
    const phases = rule.phases || ['update']
    if (!platforms.includes(platform) || !phases.includes(phase)) return false
    return rule.commits.includes(commit) &&
      rule.cases.some(([install, update]) => install === installMethod && update === updateMethod) &&
      rule.errors.some(pattern => new RegExp(pattern).test(error || '')) &&
      rule.signatures.every(pattern => new RegExp(pattern, 'i').test(logs[rule.log] || ''))
  }) || null
}

function readOptional(file) {
  try { return fs.readFileSync(file, 'utf8').replace(/^\uFEFF/, '') } catch (error) {
    if (error.code === 'ENOENT') return ''
    throw error
  }
}

// Log keys the rules may reference: the windows update-phase logs (update,
// desktop) plus the bootstrap/install transcripts every OS driver captures
// (bootstrap = the GUI installer's stage log surfaced through the driver,
// app-update = the Playwright app-driven update transcript on linux/macos).
// <logsDir> is the driver's transcript dir: the drivers honor
// HERMES_E2E_LOG_DIR, which in CI points OUTSIDE the workroot.
function collectLogs(root, logsDir = path.join(root, 'logs')) {
  const bootstrap =
    readOptional(path.join(logsDir, 'bootstrap-install.log')) ||
    readOptional(path.join(root, 'hermes-home', 'logs', 'bootstrap-installer.log')) ||
    readOptional(path.join(logsDir, 'bootstrap-installer.log'))
  return {
    update: readOptional(path.join(logsDir, 'update.log')),
    desktop: readOptional(path.join(root, 'hermes-home', 'logs', 'desktop.log')),
    bootstrap,
    'app-update': readOptional(path.join(logsDir, 'app-update.log')),
  }
}

// CLI contract (unchanged for the legacy windows update-phase call):
//   node known-failures.cjs <workRoot> <installMethod> <updateMethod> <error>
// Extended for install-phase and posix classification:
//   node known-failures.cjs <workRoot> <installMethod> <updateMethod> <error> <platform> <phase> [<oldSha>]
// <oldSha> lets posix drivers (state in shas.env, not shas.json) supply the
// OLD commit without fabricating a shas.json.
function classifyWorkRoot(root, installMethod, updateMethod, error, platform = 'windows', phase = 'update', oldSha = null, logsDir = null) {
  let commit = oldSha
  let current = null
  let oldRef = null
  if (!commit) {
    const state = JSON.parse(fs.readFileSync(path.join(root, 'shas.json'), 'utf8').replace(/^\uFEFF/, ''))
    commit = state.old
    current = state.current
    oldRef = state.old_ref
  }
  const rule = matchKnownFailure({
    platform, phase, commit, installMethod, updateMethod, error,
    logs: collectLogs(root, logsDir || undefined),
  })
  if (!rule) return null
  const receipt = {
    id: rule.id, title: rule.title, explanation: rule.explanation, evidence: rule.evidence,
    commit, installMethod, updateMethod, error,
  }
  if (current !== null) receipt.target = current
  if (oldRef !== null) receipt.installRef = oldRef
  return receipt
}

module.exports = { matchKnownFailure, classifyWorkRoot, rules }

if (require.main === module) {
  const [root, install, update, error, platform, phase, oldSha, logsDir] = process.argv.slice(2)
  try {
    const receipt = classifyWorkRoot(root, install, update, error, platform, phase, oldSha, logsDir)
    if (!receipt) process.exitCode = 1
    else {
      fs.writeFileSync(path.join(root, 'known-failure.json'), JSON.stringify(receipt, null, 2) + '\n')
      console.log(JSON.stringify(receipt))
    }
  } catch (error) {
    console.error(`known-failure classification failed: ${error.message}`)
    process.exitCode = 2
  }
}
