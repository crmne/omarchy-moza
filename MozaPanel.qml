import QtQuick
import QtQuick.Controls as Controls
import Quickshell
import qs.Commons
import qs.Ui
import "controls" as UI

Panel {
  id: root
  moduleName: "crmne.moza"
  readonly property var service: bar && bar.shell ? bar.shell.serviceFor(moduleName) : null
  property int pageIndex: 0
  readonly property string current: service ? service.current : "Rev lights"
  readonly property var page: service && service.pages.length ? service.pages[Math.min(pageIndex, service.pages.length - 1)] : ({groups: []})
  visible: !!service && !!service.rev.connected
  onVisibleChanged: if (!visible) root.close()
  implicitWidth: icon.implicitWidth
  implicitHeight: icon.implicitHeight
  function register() { if (service && service.instances.indexOf(root) === -1) service.instances = service.instances.concat([root]) }
  onServiceChanged: register()
  Component.onCompleted: register()
  Component.onDestruction: { if (service) service.instances = service.instances.filter(item => item !== root) }
  onOpenedChanged: if (service) service.selectPage(current, opened)
  onCurrentChanged: { pageIndex = 0; if (scroll.contentItem) scroll.contentItem.contentY = 0 }

  BarIconButton {
    id: icon
    bar: root.bar
    anchors.centerIn: parent
    text: "󰓔" // nf-md-steering
    tooltipText: "MOZA · " + (root.service && root.service.rev.connected ? (root.service.rev.game || "Connected") : "Disconnected")
    onPressed: button => { if (button === Qt.LeftButton) root.toggle() }
  }
  KeyboardPanel {
    id: panel
    anchorItem: root; owner: root; bar: root.bar; open: root.opened
    contentWidth: fittedContentWidth(Style.space(730))
    contentHeight: fittedContentHeight(Style.space(650))
    focusTarget: content
    Item {
      id: content
      anchors.fill: parent
      focus: true
      Keys.onEscapePressed: { if (root.service && root.service.dialog) root.service.send({op: "back"}); else root.close() }
      Row {
        id: heading
        width: parent.width
        spacing: Style.space(12)
        UI.Label { text: "MOZA"; font.pixelSize: Style.space(22); font.bold: true }
        UI.Label { anchors.verticalCenter: parent.verticalCenter; text: root.service && root.service.rev.connected ? "●  Connected" : "○  Disconnected"; color: Color.accent; font.pixelSize: Style.font.bodySmall }
      }
      UI.Label { id: subtitle; anchors.top: heading.bottom; anchors.topMargin: Style.space(4); text: "Boxflat settings · moza-rev telemetry"; font.pixelSize: Style.font.caption; opacity: 0.5 }
      Controls.ScrollView {
        id: nav
        anchors.top: subtitle.bottom; anchors.topMargin: Style.space(20)
        anchors.left: parent.left; anchors.bottom: parent.bottom
        width: Style.space(166); clip: true
        Controls.ScrollBar.horizontal.policy: Controls.ScrollBar.AlwaysOff
        Column {
          width: nav.availableWidth
          spacing: Style.space(3)
          Repeater {
            model: [{name: "Rev lights", connected: true}].concat(root.service ? root.service.panels : [])
            Button {
              required property var modelData
              width: parent.width
              text: modelData.name === "Wheel Old" ? "Legacy wheel" : modelData.name
              fontSize: Style.font.bodySmall
              selected: root.current === modelData.name
              opacity: modelData.connected ? 1 : 0.5
              leftAlign: true; focusable: true
              onClicked: if (root.service) root.service.selectPage(modelData.name, true)
            }
          }
        }
      }
      Column {
        id: mainHeader
        anchors.top: nav.top; anchors.left: nav.right; anchors.leftMargin: Style.space(20); anchors.right: parent.right
        spacing: Style.space(10)
        Row {
          spacing: Style.space(8)
          Button { visible: !!root.service && root.service.dialog; text: "Back"; bordered: true; focusable: true; onClicked: root.service.send({op: "back"}) }
          UI.Label { text: root.current; font.pixelSize: Style.font.subtitle; font.bold: true; anchors.verticalCenter: parent.verticalCenter }
        }
        UI.Label {
          width: parent.width
          text: !root.service || !root.service.ready ? (root.service && root.service.error ? root.service.error : "Starting MOZA…") : root.service.error || root.service.message
          visible: text !== ""
          color: root.service && root.service.error ? Color.urgent : Color.accent
          font.pixelSize: Style.font.bodySmall
        }
        Flow {
          width: parent.width; spacing: Style.space(4)
          visible: !!root.service && root.service.pages.length > 1 && root.current !== "Rev lights"
          Repeater {
            model: root.service ? root.service.pages : []
            Button { required property var modelData; required property int index; text: modelData.title; selected: root.pageIndex === index; focusable: true; fontSize: Style.font.bodySmall; onClicked: {root.pageIndex = index; scroll.contentItem.contentY = 0} }
          }
        }
      }
      Controls.ScrollView {
        id: scroll
        anchors.top: mainHeader.bottom; anchors.topMargin: Style.space(14)
        anchors.left: mainHeader.left; anchors.right: parent.right; anchors.bottom: parent.bottom
        clip: true
        Controls.ScrollBar.horizontal.policy: Controls.ScrollBar.AlwaysOff
        Column {
          width: scroll.availableWidth
          spacing: Style.space(14)
          Loader { width: parent.width; visible: active; active: !!root.service && root.current === "Rev lights"; sourceComponent: UI.RevPage { service: root.service } }
          Repeater {
            model: root.current === "Rev lights" ? [] : root.page.groups || []
            UI.Card {
              id: groupCard
              required property var modelData
              readonly property var groupData: root.service ? root.service.groups[modelData.id] || ({}) : ({})
              visible: groupData.visible !== false && (groupData.rows || []).some(row => row.visible !== false)
              spacing: Style.space(18)
              Row {
                width: parent.width
                UI.Label { width: parent.width - addButton.width; text: groupCard.groupData.title || ""; color: Color.accent; font.pixelSize: Style.font.caption; font.bold: true; font.capitalization: Font.AllUppercase; font.letterSpacing: 1 }
                Button { id: addButton; visible: !!groupCard.groupData.add; text: "+"; focusable: true; onClicked: root.service.act(groupCard.groupData.add, "click") }
              }
              UI.Label { visible: text !== ""; width: parent.width; text: groupCard.groupData.description || ""; opacity: 0.55; font.pixelSize: Style.font.bodySmall }
              Repeater {
                model: groupCard.modelData.rows
                UI.SettingRow { required property var modelData; layout: modelData; service: root.service }
              }
            }
          }
        }
      }
    }
  }
}
