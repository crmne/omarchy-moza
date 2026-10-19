import QtQuick
import qs.Commons
import qs.Commons as Commons
import qs.Ui as UI

Column {
  id: root
  required property var service
  spacing: Style.space(16)
  readonly property var rev: service.rev
  readonly property var config: service.config
  readonly property var colors: config.colors || ["#00ff00", "#ffff00", "#ff0000"]
  readonly property var colorOptions: [
    {label: "Green", value: "#00ff00"}, {label: "Yellow", value: "#ffff00"},
    {label: "Red", value: "#ff0000"}, {label: "Blue", value: "#0000ff"},
    {label: "Purple", value: "#8000ff"}, {label: "White", value: "#ffffff"}
  ]
  Card {
    Label { width: parent.width; text: root.rev.game || (root.rev.connected ? "Ready for telemetry" : "Connect your MOZA wheelbase"); color: Commons.Color.accent; font.pixelSize: Style.font.bodySmall }
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
          color: root.colors[index * 10 < root.config.leds * 5 ? 0 : index * 10 < root.config.leds * 8 ? 1 : 2]
          opacity: ((root.rev.mask || 0) & Math.pow(2, index)) ? (root.config.brightness === undefined ? 1 : root.config.brightness / 100) : 0.17
        }
      }
    }
    Label { text: root.rev.redline ? "Redline  " + root.rev.redline + " RPM" : "Start a driving session to see live RPM."; font.pixelSize: Style.font.bodySmall; opacity: 0.55 }
  }
  Card {
    Label { text: "SHIFT LIGHTS"; color: Commons.Color.accent; font.pixelSize: Style.font.caption; font.bold: true; font.letterSpacing: 1.1 }
    UI.Toggle { width: parent.width; label: "Rev lights"; description: "Respond to live game telemetry"; checked: root.config.enabled; foreground: Commons.Color.popups.text; onClicked: root.service.setRev("enabled", !checked) }
    Row {
      width: parent.width; spacing: Style.space(24)
      NumberKeyField {
        label: "First light (%)"; from: 0; to: root.config.full - 1; value: root.config.start
        foreground: Commons.Color.popups.text; fieldWidth: Style.space(120)
        onModified: value => root.service.setRev("start", value)
      }
      NumberKeyField {
        label: "Full lights (%)"; from: root.config.start + 1; to: 100; value: root.config.full
        foreground: Commons.Color.popups.text; fieldWidth: Style.space(120)
        onModified: value => root.service.setRev("full", value)
      }
    }
    Label { width: parent.width; text: "Percent of the car’s redline. Lights fill progressively between these points."; font.pixelSize: Style.font.bodySmall; opacity: 0.55 }
    Row {
      width: parent.width; spacing: Style.space(24)
      NumberKeyField {
        label: "Flash at (%)"; from: 1; to: 100
        value: root.config.flash === undefined ? 95 : root.config.flash
        foreground: Commons.Color.popups.text; fieldWidth: Style.space(120)
        onModified: value => root.service.setRev("flash", value)
      }
      NumberKeyField {
        label: "Flashes per second"; from: 1; to: 20
        value: root.config.flash_hz === undefined ? 10 : root.config.flash_hz
        foreground: Commons.Color.popups.text; fieldWidth: Style.space(120)
        onModified: value => root.service.setRev("flash_hz", value)
      }
    }
    Label {
      width: parent.width
      text: (root.rev.redline ? "Whole-strip flash at " + Math.ceil(root.rev.redline * (root.config.flash === undefined ? 95 : root.config.flash) / 100) + " RPM. " : "Flash the whole strip at this percentage of redline. ") + "Lower the percentage for an earlier cue."
      font.pixelSize: Style.font.bodySmall; opacity: 0.55
    }
    Row {
      spacing: Style.space(8)
      UI.Button { text: "GT3 · 80–97%"; bordered: true; focusable: true; onClicked: root.service.send({op: "rev", config: Object.assign({}, root.config, {start: 80, full: 97})}) }
      UI.Button { text: root.rev.test ? "Testing…" : "Test lights"; enabled: !!root.rev.connected && !root.rev.test; bordered: true; focusable: true; onClicked: root.service.send({op: "test"}) }
    }
  }
  Card {
    Label { text: "COLORS"; color: Commons.Color.accent; font.pixelSize: Style.font.caption; font.bold: true; font.letterSpacing: 1.1 }
    Label {
      width: parent.width
      visible: !!root.rev.connected && root.rev.customColors === false
      text: "Custom colors and brightness are unavailable on this wheel."
      font.pixelSize: Style.font.bodySmall; opacity: 0.55
    }
    Row {
      width: parent.width; spacing: Style.space(10)
      enabled: !root.rev.connected || root.rev.customColors !== false
      Repeater {
        model: 3
        Column {
          required property int index
          readonly property string selectedColor: root.colors[index].toLowerCase()
          width: (parent.width - parent.spacing * 2) / 3
          spacing: Style.space(6)
          Label { text: ["First", "Middle", "Last"][parent.index]; font.pixelSize: Style.font.bodySmall }
          Rectangle { width: parent.width; height: Style.space(10); radius: Style.space(3); color: parent.selectedColor }
          UI.Dropdown {
            width: parent.width
            value: parent.selectedColor
            options: root.colorOptions.concat(root.colorOptions.some(option => option.value === parent.selectedColor) ? [] : [{label: "Custom", value: parent.selectedColor}])
            onChanged: value => root.service.setRevColor(parent.index, value)
          }
          KeyField {
            width: parent.width
            value: parent.selectedColor
            maximumLength: 7
            allowedCharacters: /[#0-9a-fA-F]/
            font.pixelSize: Style.font.caption
            onEditingFinished: {
              if (text === value) return
              if (/^#[0-9a-fA-F]{6}$/.test(text)) root.service.setRevColor(parent.index, text.toLowerCase())
              else text = value
            }
          }
        }
      }
    }
    Flow {
      width: parent.width; spacing: Style.space(12)
      enabled: !root.rev.connected || root.rev.customColors !== false
      NumberKeyField {
        label: "Brightness (%)"; from: 0; to: 100
        value: root.config.brightness === undefined ? 100 : root.config.brightness
        foreground: Commons.Color.popups.text; fieldWidth: Style.space(120)
        onModified: value => root.service.setRev("brightness", value)
      }
      UI.Button {
        text: "Green / yellow / red"; bordered: true; focusable: true
        onClicked: root.service.setRev("colors", ["#00ff00", "#ffff00", "#ff0000"])
      }
    }
  }
  Card {
    NumberKeyField { label: "LED count"; from: 1; to: 32; value: root.config.leds; foreground: Commons.Color.popups.text; onModified: value => root.service.setRev("leds", value) }
    Label { width: parent.width; text: "Automobilista 2: UDP protocol Project CARS 2, frequency 1. Other supported games are detected automatically."; font.pixelSize: Style.font.bodySmall; opacity: 0.55 }
    Label { width: parent.width; visible: (root.rev.unavailableListeners || []).length > 0; text: "Telemetry ports in use: " + (root.rev.unavailableListeners || []).join(", "); color: Commons.Color.urgent }
  }
}
