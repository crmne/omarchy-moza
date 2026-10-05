import QtQuick
import qs.Commons
import qs.Ui as UI

Column {
  id: root
  required property var service
  spacing: Style.space(16)
  readonly property var rev: service.rev
  readonly property var config: service.config
  Card {
    Label { width: parent.width; text: root.rev.game || (root.rev.connected ? "Ready for telemetry" : "Connect your MOZA wheelbase"); color: Color.accent; font.pixelSize: Style.font.bodySmall }
    Row {
      spacing: Style.space(8)
      Label { text: String(root.rev.rpm || 0); font.pixelSize: Style.space(46); font.bold: true }
      Label { text: "RPM"; anchors.bottom: parent.bottom; anchors.bottomMargin: Style.space(9); opacity: 0.5 }
    }
    Row {
      width: parent.width
      spacing: Style.space(5)
      Repeater {
        model: root.config.leds || 10
        Rectangle {
          required property int index
          width: (parent.width - parent.spacing * ((root.config.leds || 10) - 1)) / (root.config.leds || 10)
          height: Style.space(14); radius: Style.space(3)
          color: index < Math.ceil((root.config.leds || 10) * 0.5) ? "#71bd80" : (index < Math.ceil((root.config.leds || 10) * 0.8) ? "#e9c46a" : "#e06c75")
          opacity: ((root.rev.mask || 0) & Math.pow(2, index)) ? 1 : 0.17
        }
      }
    }
    Label { text: root.rev.redline ? "Redline  " + root.rev.redline + " RPM" : "Start a driving session to see live RPM."; font.pixelSize: Style.font.bodySmall; opacity: 0.55 }
  }
  Card {
    Label { text: "SHIFT LIGHTS"; color: Color.accent; font.pixelSize: Style.font.caption; font.bold: true; font.letterSpacing: 1.1 }
    UI.Toggle { width: parent.width; label: "Rev lights"; description: "Respond to live game telemetry"; checked: root.config.enabled; foreground: Color.popups.text; onClicked: root.service.setRev("enabled", !checked) }
    Row {
      width: parent.width; spacing: Style.space(24)
      UI.NumberField {
        label: "First light (%)"; from: 0; to: root.config.full - 1; value: root.config.start
        foreground: Color.popups.text; fieldWidth: Style.space(120); field.wheelEnabled: false
        onModified: value => root.service.setRev("start", value)
      }
      UI.NumberField {
        label: "Full lights (%)"; from: root.config.start + 1; to: 100; value: root.config.full
        foreground: Color.popups.text; fieldWidth: Style.space(120); field.wheelEnabled: false
        onModified: value => root.service.setRev("full", value)
      }
    }
    Label { width: parent.width; text: "Percent of the car’s redline. Lights fill progressively between these points."; font.pixelSize: Style.font.bodySmall; opacity: 0.55 }
    Row {
      spacing: Style.space(8)
      UI.Button { text: "GT3 · 80–97%"; bordered: true; focusable: true; onClicked: root.service.send({op: "rev", config: Object.assign({}, root.config, {start: 80, full: 97})}) }
      UI.Button { text: root.rev.test ? "Testing…" : "Test lights"; enabled: !!root.rev.connected && !root.rev.test; bordered: true; focusable: true; onClicked: root.service.send({op: "test"}) }
    }
  }
  Card {
    UI.NumberField { label: "LED count"; from: 1; to: 32; value: root.config.leds; foreground: Color.popups.text; field.wheelEnabled: false; onModified: value => root.service.setRev("leds", value) }
    Label { width: parent.width; text: "Automobilista 2: UDP protocol Project CARS 2, frequency 1. Other supported games are detected automatically."; font.pixelSize: Style.font.bodySmall; opacity: 0.55 }
    Label { width: parent.width; visible: (root.rev.unavailableListeners || []).length > 0; text: "Telemetry ports in use: " + (root.rev.unavailableListeners || []).join(", "); color: Color.urgent }
  }
}
