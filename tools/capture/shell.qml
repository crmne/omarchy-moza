// Isolated screenshot host. Production controls and theme, simulated readings.
import QtQuick
import QtQuick.Effects
import Quickshell
import Quickshell.Io
import qs.Commons

ShellRoot {
  id: host
  property var fixtures: ({})
  Component.onCompleted: Style.cornerRadius = 10
  FileView {
    path: Quickshell.env("MOZA_FIXTURES")
    onLoaded: host.fixtures = JSON.parse(text())
  }
  Loader { id: service; source: "file://" + Quickshell.env("MOZA_PLUGIN") + "/MozaService.qml" }
  QtObject {
    id: bar
    property string position: "top"
    property real barSize: 26
    property bool vertical: false
    property bool foregroundAnimationEnabled: false
    property color urgent: Color.urgent
    property color barForeground: Color.bar.text
    property color foreground: Color.bar.text
    property string fontFamily: Style.font.family
    property var activePopout: null
    property var clickTargets: []
    property var shell: QtObject { function serviceFor(name) { return service.item } }
    function requestPopout(key) { activePopout = key }
    function releasePopout(key) { if (activePopout === key) activePopout = null }
    function targetBelongsToWindow() { return false }
    function hideTooltip(item) {}
  }
  FloatingWindow {
    implicitWidth: 1600; implicitHeight: 30
    color: "transparent"
    Loader {
      id: panel
      x: 500; y: 2
      source: "file://" + Quickshell.env("MOZA_PLUGIN") + "/MozaPanel.qml"
      onLoaded: item.bar = bar
    }
  }
  function card() {
    var data = panel.item.data
    for (var i = 0; i < data.length; i++) {
      if (data[i].captureCard !== undefined) return data[i].captureCard
    }
    return null
  }
  FloatingWindow {
    id: preview
    implicitWidth: 2560; implicitHeight: 1600
    visible: false
    color: "#090503"
    Item {
      id: composition
      width: 2560; height: 1600
      Image {
        id: wallpaper
        anchors.fill: parent
        source: Quickshell.env("MOZA_WALLPAPER")
        fillMode: Image.PreserveAspectCrop
        layer.enabled: true
        layer.effect: MultiEffect { blurEnabled: true; blurMax: 16; blur: 0.7 }
      }
      Rectangle { anchors.fill: parent; color: "#a6000000" }
      Image {
        id: inputs
        x: 90; y: 240; width: 1240; height: 1158
        source: preview.visible ? Quickshell.env("MOZA_OUTPUT") + "/inputs.png" : ""
        fillMode: Image.PreserveAspectFit
        layer.enabled: true
        layer.effect: MultiEffect { shadowEnabled: true; shadowBlur: 0.8; shadowOpacity: 0.6; shadowVerticalOffset: 20 }
      }
      Image {
        x: 1230; y: 95; width: 1240; height: 1158
        source: preview.visible ? Quickshell.env("MOZA_OUTPUT") + "/rev-lights.png" : ""
        fillMode: Image.PreserveAspectFit
        layer.enabled: true
        layer.effect: MultiEffect { shadowEnabled: true; shadowBlur: 0.8; shadowOpacity: 0.6; shadowVerticalOffset: 20 }
      }
    }
  }
  IpcHandler {
    target: "capture"
    function ready(): bool { return !!panel.item && !!service.item && !!host.fixtures.Home }
    function displayPage(page: string): string {
      service.item.current = page
      service.item.ingest(JSON.stringify(host.fixtures[page]))
      panel.item.open()
      return JSON.stringify({visible: panel.item.visible, open: panel.item.opened, rev: service.item.rev})
    }
    function connection(connected: bool): string {
      service.item.rev = Object.assign({}, service.item.rev, {connected: connected})
      return JSON.stringify({visible: panel.item.visible, open: panel.item.opened, ready: service.item.ready})
    }
    function grab(path: string): string {
      var c = host.card()
      if (!c) return "No panel card"
      return c.grabToImage(result => result.saveToFile(path)) ? "ok" : "Capture failed"
    }
    function preparePreview(): void { preview.visible = true }
    function grabPreview(path: string): bool {
      return composition.grabToImage(result => result.saveToFile(path), Qt.size(1280, 800))
    }
  }
}
