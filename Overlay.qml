pragma ComponentBehavior: Bound

import QtQuick
import Quickshell
import Quickshell.Wayland
import qs.Commons
import qs.Ui

Item {
  id: root

  property string omarchyPath: ""
  property var shell: null
  property var manifest: null
  property var service: null
  property bool opened: false
  property bool showChanges: false
  property bool confirmingSwitch: false

  readonly property string pluginId: "io.github.jcarcinogen.gaming-console"
  readonly property string statusState: service ? service.statusState : "unsupported"
  readonly property bool ready: statusState === "ready"
  readonly property bool helperRequired: statusState === "not_installed"
    && service && service.statusPayload.checks
    && service.statusPayload.checks.engine_helper === false
  readonly property var statusReasons: service && service.statusPayload.reasons ? service.statusPayload.reasons : []
  readonly property string redundantReadyReason: "The complete system engine is installed and safe."
  readonly property bool hasOnlyRedundantReadyReason:
    ready && statusReasons.length === 1 && statusReasons[0] === redundantReadyReason
  readonly property color backgroundColor: Color.menu.background
  readonly property color foregroundColor: Color.menu.text
  readonly property color mutedColor: Qt.rgba(foregroundColor.r, foregroundColor.g, foregroundColor.b, 0.62)
  readonly property color borderColor: Color.menu.border
  readonly property color scrimColor: Color.menu.scrim
  readonly property var borderSpec: Border.surfaceSpec("menu", "border", borderColor, Math.max(1, Style.space(2)))

  function open(payloadJson) {
    root.opened = true
    root.showChanges = false
    root.confirmingSwitch = false
    if (root.service) root.service.refresh()
    Qt.callLater(function() { keyCatcher.forceActiveFocus() })
  }

  function close() {
    root.opened = false
    root.showChanges = false
    root.confirmingSwitch = false
  }

  function dismiss() {
    root.close()
    if (root.shell) root.shell.hide(root.pluginId)
  }

  function run(action) {
    if (!root.service || !root.service.runAction(action)) return
    root.dismiss()
  }

  component ActionButton: Rectangle {
    id: actionButton
    property string label: ""
    property bool emphasized: false
    property bool actionEnabled: true
    signal triggered()

    LayoutMirroring.enabled: false
    width: parent ? parent.width : Style.space(320)
    height: Style.space(42)
    radius: Style.cornerRadius
    color: emphasized
      ? Color.accent
      : Qt.rgba(root.foregroundColor.r, root.foregroundColor.g, root.foregroundColor.b, actionMouse.containsMouse ? 0.14 : 0.08)
    opacity: actionEnabled ? 1 : 0.45

    Text {
      anchors.centerIn: parent
      text: actionButton.label
      textFormat: Text.PlainText
      color: actionButton.emphasized ? Color.background : root.foregroundColor
      font.family: Style.font.family
      font.pixelSize: Style.font.body
      font.weight: Font.DemiBold
    }

    MouseArea {
      id: actionMouse
      anchors.fill: parent
      enabled: actionButton.actionEnabled
      hoverEnabled: true
      cursorShape: Qt.PointingHandCursor
      onClicked: actionButton.triggered()
    }
  }

  PanelWindow {
    id: panel
    visible: root.opened
    anchors { top: true; bottom: true; left: true; right: true }
    color: "transparent"
    WlrLayershell.namespace: "omarchy-gaming-console"
    WlrLayershell.layer: WlrLayer.Overlay
    WlrLayershell.keyboardFocus: root.opened ? WlrKeyboardFocus.Exclusive : WlrKeyboardFocus.None
    exclusionMode: ExclusionMode.Ignore

    Shortcut {
      sequence: "Escape"
      enabled: root.opened
      onActivated: root.dismiss()
    }

    Rectangle {
      anchors.fill: parent
      color: root.scrimColor
    }

    MouseArea {
      anchors.fill: parent
      onClicked: root.dismiss()
    }

    BorderSurface {
      id: card
      width: Math.min(Style.space(440), panel.width - Style.gapsOut * 2)
      height: Math.min(contentColumn.implicitHeight + Style.spacing.panelPadding * 2, panel.height - Style.gapsOut * 2)
      anchors.centerIn: parent
      color: root.backgroundColor
      radius: Style.cornerRadius
      borderSpec: root.borderSpec
      padding: Style.spacing.panelPadding

      MouseArea { anchors.fill: parent; onClicked: function(mouse) { mouse.accepted = true } }

      PanelKeyCatcher {
        id: keyCatcher
        anchors.fill: parent
        onCloseRequested: root.dismiss()

        Column {
          id: contentColumn
          anchors {
            left: parent.left
            right: parent.right
            top: parent.top
            leftMargin: card.contentLeftInset
            rightMargin: card.contentRightInset
            topMargin: card.contentTopInset
          }
          spacing: Style.space(10)

          Text {
            width: parent.width
            text: root.helperRequired ? "Engine Helper Required" : "Omarchy Gaming Console"
            textFormat: Text.PlainText
            color: root.foregroundColor
            font.family: Style.font.family
            font.pixelSize: Style.font.title
            font.weight: Font.Bold
          }

          Text {
            width: parent.width
            text: root.service && root.service.lastError
              ? root.service.lastError
              : (root.helperRequired
                  ? "One signed prerequisite must be installed before Game Mode setup can begin."
                  : (root.ready ? "The system engine is installed and safe." : "Setup status: " + root.statusState.replace(/_/g, " ")))
            textFormat: Text.PlainText
            wrapMode: Text.WordWrap
            color: root.mutedColor
            font.family: Style.font.family
            font.pixelSize: Style.font.body
          }

          Text {
            width: parent.width
            visible: !root.helperRequired && root.statusReasons.length > 0 && !root.hasOnlyRedundantReadyReason
            text: visible ? root.statusReasons.join("\n") : ""
            textFormat: Text.PlainText
            wrapMode: Text.WordWrap
            color: root.mutedColor
            font.family: Style.font.family
            font.pixelSize: Style.font.caption
          }

          Column {
            width: parent.width
            spacing: Style.space(8)
            visible: root.helperRequired

            Text {
              width: parent.width
              text: "The marketplace installs only the unprivileged plugin. The signed engine helper is installed separately so this plugin folder is never trusted as root. The next window gives you the README link and tells you which single block to copy and paste."
              textFormat: Text.PlainText
              wrapMode: Text.WordWrap
              color: root.foregroundColor
              font.family: Style.font.family
              font.pixelSize: Style.font.body
            }
            ActionButton {
              label: "Open installation instructions"
              emphasized: true
              onTriggered: root.run("helperInstructions")
            }
            ActionButton {
              label: "Cancel"
              onTriggered: root.dismiss()
            }
          }

          Column {
            width: parent.width
            spacing: Style.space(8)
            visible: root.statusState === "not_installed" && !root.helperRequired && !root.showChanges

            ActionButton {
              label: "Install Game Mode"
              emphasized: true
              onTriggered: root.run("setup")
            }
            ActionButton {
              label: "View what will change"
              onTriggered: root.showChanges = true
            }
            ActionButton {
              label: "Cancel"
              onTriggered: root.dismiss()
            }
          }

          Column {
            width: parent.width
            spacing: Style.space(8)
            visible: root.statusState === "not_installed" && !root.helperRequired && root.showChanges

            Text {
              width: parent.width
              text: "Setup adds one Console session, fixed Steam return helpers, one narrow polkit action, and an inert SDDM route whose request exists only under /run. Stock omarchy.desktop and autologin.conf remain unchanged."
              textFormat: Text.PlainText
              wrapMode: Text.WordWrap
              color: root.foregroundColor
              font.family: Style.font.family
              font.pixelSize: Style.font.body
            }
            ActionButton {
              label: "Install Game Mode"
              emphasized: true
              onTriggered: root.run("setup")
            }
            ActionButton {
              label: "Cancel"
              onTriggered: root.dismiss()
            }
          }

          Column {
            width: parent.width
            spacing: Style.space(8)
            visible: root.ready && !root.confirmingSwitch

            ActionButton {
              label: "Switch to Console"
              emphasized: true
              onTriggered: root.confirmingSwitch = true
            }
            ActionButton {
              label: "Check setup"
              actionEnabled: root.service && !root.service.actionRunning
              onTriggered: root.service.refresh()
            }
            ActionButton {
              label: "Repair setup"
              onTriggered: root.run("repair")
            }
            ActionButton {
              label: "Uninstall Game Mode"
              onTriggered: root.run("uninstall")
            }
          }

          Column {
            width: parent.width
            spacing: Style.space(8)
            visible: root.ready && root.confirmingSwitch

            Text {
              width: parent.width
              text: "This will close the Omarchy desktop and any open applications. Save your work first."
              textFormat: Text.PlainText
              wrapMode: Text.WordWrap
              color: root.foregroundColor
              font.family: Style.font.family
              font.pixelSize: Style.font.heading
              font.weight: Font.DemiBold
            }
            ActionButton {
              label: "Switch to Console"
              emphasized: true
              onTriggered: root.run("switch")
            }
            ActionButton {
              label: "Cancel"
              onTriggered: root.confirmingSwitch = false
            }
          }

          Column {
            width: parent.width
            spacing: Style.space(8)
            visible: !root.ready && root.statusState !== "not_installed"

            ActionButton {
              label: "Check setup"
              actionEnabled: root.service && !root.service.actionRunning
              onTriggered: root.service.refresh()
            }
            ActionButton {
              visible: root.statusState === "incomplete" || root.statusState === "update_required"
              label: "Repair setup"
              onTriggered: root.run("repair")
            }
            ActionButton {
              label: "Cancel"
              onTriggered: root.dismiss()
            }
          }
        }
      }
    }
  }
}
