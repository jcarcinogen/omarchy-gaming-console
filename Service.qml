import QtQuick
import Quickshell.Io

Item {
  id: root

  property string omarchyPath: ""
  property var shell: null
  property var manifest: null
  property var pluginRegistry: null

  readonly property string pluginId: "io.github.jcarcinogen.gaming-console"
  readonly property string cliPath: decodeURIComponent(String(Qt.resolvedUrl("bin/omarchy-gaming-console")).replace(/^file:\/\//, ""))
  readonly property var allowedStates: ["not_installed", "incomplete", "ready", "update_required", "unsafe", "unsupported"]

  property var statusPayload: ({
    schema: 1,
    state: "unsupported",
    omarchy: "unknown",
    hostname: "unknown",
    reasons: ["Status has not been checked yet."],
    owned: [],
    checks: ({})
  })
  readonly property string statusState: String(statusPayload.state || "unsupported")
  property string lastError: ""
  property int generation: 0
  property int activeGeneration: 0
  property int appliedGeneration: 0
  property bool pendingRefresh: false
  property bool actionRunning: actionProcess.running

  signal statusUpdated()

  function refresh() {
    root.generation += 1
    if (statusProcess.running) {
      root.pendingRefresh = true
      return
    }
    root.startStatus(root.generation)
  }

  function startStatus(requestGeneration) {
    root.activeGeneration = requestGeneration
    root.lastError = ""
    statusProcess.running = true
  }

  function finishStatus(exitCode) {
    var completedGeneration = root.activeGeneration
    var stale = completedGeneration !== root.generation
    if (!stale) {
      if (exitCode !== 0) {
        root.lastError = "Status command failed with exit " + exitCode
      } else {
        try {
          var parsed = JSON.parse(String(statusStdout.text || ""))
          if (parsed.schema !== 1 || root.allowedStates.indexOf(String(parsed.state || "")) === -1
              || !Array.isArray(parsed.reasons) || !Array.isArray(parsed.owned)
              || typeof parsed.checks !== "object" || parsed.checks === null) {
            root.lastError = "Status command returned an unsupported schema."
          } else {
            root.statusPayload = parsed
            root.appliedGeneration = completedGeneration
            root.lastError = ""
            root.statusUpdated()
          }
        } catch (error) {
          root.lastError = "Status command returned invalid JSON."
        }
      }
    }
    if (root.pendingRefresh || stale) {
      root.pendingRefresh = false
      Qt.callLater(function() { root.startStatus(root.generation) })
    }
  }

  function runAction(action) {
    if (actionProcess.running) return false
    var fixed = {
      "setup": [root.cliPath, "setup"],
      "switch": [root.cliPath, "switch"],
      "repair": [root.cliPath, "repair"],
      "uninstall": [root.cliPath, "uninstall"]
    }
    if (!fixed[action]) return false
    actionProcess.command = fixed[action]
    actionProcess.running = true
    return true
  }

  Process {
    id: statusProcess
    command: [root.cliPath, "status", "--json"]
    stdout: StdioCollector {
      id: statusStdout
      waitForEnd: true
    }
    stderr: StdioCollector {
      id: statusStderr
      waitForEnd: true
    }
    onExited: function(exitCode) { root.finishStatus(exitCode) }
  }

  Process {
    id: actionProcess
    command: [root.cliPath, "status"]
    onExited: function(exitCode) {
      if (exitCode !== 0) root.lastError = "Action failed with exit " + exitCode
      statusRefreshDelay.restart()
    }
  }

  Timer {
    id: statusRefreshDelay
    interval: 750
    repeat: false
    onTriggered: root.refresh()
  }

  Timer {
    interval: 30000
    repeat: true
    running: true
    triggeredOnStart: true
    onTriggered: root.refresh()
  }

  IpcHandler {
    target: "io.github.jcarcinogen.gaming-console"

    function status(): string { return JSON.stringify(root.statusPayload) }
    function refresh(): string { root.refresh(); return "ok" }
    function open(): string {
      return root.shell && root.shell.summon(root.pluginId, "{}") ? "ok" : "unavailable"
    }
    function close(): string {
      return root.shell && root.shell.hide(root.pluginId) ? "ok" : "unavailable"
    }
    function setup(): string { return root.runAction("setup") ? "ok" : "busy" }
    function switchToConsole(): string { return root.runAction("switch") ? "ok" : "busy" }
    function repair(): string { return root.runAction("repair") ? "ok" : "busy" }
    function uninstall(): string { return root.runAction("uninstall") ? "ok" : "busy" }
  }
}
