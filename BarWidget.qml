import QtQuick
import qs.Commons
import qs.Ui

BarWidget {
  id: root

  moduleName: "io.github.jcarcinogen.gaming-console"

  readonly property var consoleService: root.bar && root.bar.shell
    ? root.bar.shell.serviceFor(root.moduleName) : null
  readonly property string consoleState: consoleService ? consoleService.statusState : "unsupported"
  readonly property bool ready: consoleState === "ready"
  readonly property color themedForeground: root.bar ? root.bar.barForeground : Color.foreground
  readonly property string nextAction: {
    if (ready) return "Switch to Console"
    if (consoleState === "unsafe") return "Unsafe setup"
    if (consoleState === "unsupported") return "Unsupported"
    return "Setup required"
  }

  function toggleOverlay() {
    if (root.bar && root.bar.shell)
      root.bar.shell.toggle(root.moduleName, "{}")
  }

  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight

  BarIconButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    text: "\uf11b"
    slotSize: Style.bar.statusSlot
    fontSize: Style.font.body
    foreground: root.ready
      ? root.themedForeground
      : Qt.rgba(root.themedForeground.r, root.themedForeground.g, root.themedForeground.b, 0.45)
    tooltipText: "Omarchy Gaming Console — " + root.nextAction
    onPressed: root.toggleOverlay()
  }
}
