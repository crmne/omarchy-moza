import QtQuick
import QtQuick.Controls as Controls
import qs.Commons
import qs.Ui as UI

Column {
  id: root
  property var service: null
  property var layout: ({id: "", children: []})
  readonly property var rowState: service ? service.rows[layout.id] || ({}) : ({})
  readonly property string kind: rowState.kind || "label"
  property bool expanded: false
  width: parent.width
  visible: rowState.visible !== false
  enabled: rowState.enabled !== false
  opacity: enabled ? 1 : 0.4
  spacing: Style.space(8)

  function act(action, value, index) { service.act(layout.id, action, value, index) }
  Row {
    width: parent.width
    spacing: Style.space(12)
    Column {
      width: parent.width - (switchControl.visible ? switchControl.width + parent.spacing : 0)
      spacing: Style.space(3)
      Label { width: parent.width; text: root.rowState.title || ""; font.bold: true; visible: text !== "" }
      Label { width: parent.width; text: root.rowState.subtitle || ""; font.pixelSize: Style.font.bodySmall; opacity: 0.55; visible: text !== "" }
    }
    UI.ToggleSwitch {
      id: switchControl
      visible: root.kind === "switch"
      checked: !!root.rowState.value
      onToggled: root.act("set", !checked)
    }
  }
  Row {
    visible: root.kind === "slider"
    width: parent.width
    spacing: Style.space(12)
    UI.PanelSlider {
      width: parent.width - number.width - parent.spacing
      anchors.verticalCenter: parent.verticalCenter
      minimum: root.rowState.min || 0; maximum: root.rowState.max || 100
      value: Number(root.rowState.value) || 0; integer: true
      trackColor: Util.alpha(Color.popups.text, 0.12)
      fillColor: Color.accent; knobColor: Color.popups.text
      onReleased: value => root.act("set", value)
    }
    UI.NumberField {
      id: number
      fieldWidth: Style.space(84)
      from: root.rowState.min || 0; to: root.rowState.max || 100
      value: Number(root.rowState.value) || 0
      stepSize: root.rowState.step || 1
      foreground: Color.popups.text
      field.wheelEnabled: false
      onModified: value => root.act("set", value)
    }
  }
  UI.Dropdown {
    visible: root.kind === "choice" || (root.kind === "equalizer" && (root.rowState.options || []).length > 0)
    width: parent.width
    value: String(root.rowState.value === undefined ? -1 : root.rowState.value)
    options: (root.rowState.options || []).map((text, index) => ({label: text, value: String(index)}))
    onChanged: value => root.act("set", Number(value))
  }
  UI.TextField {
    id: entry
    visible: root.kind === "entry"
    width: parent.width
    text: root.rowState.value || ""
    onTextEdited: root.act("set", text)
  }
  Repeater {
    model: root.kind === "equalizer" ? (root.rowState.sliders || []).length : 0
    Row {
      required property int index
      readonly property var datum: root.rowState.sliders[index] || ({})
      width: root.width
      spacing: Style.space(10)
      enabled: datum.enabled !== false
      Label { width: Style.space(48); anchors.verticalCenter: parent.verticalCenter; text: parent.datum.label || String(parent.index + 1); font.pixelSize: Style.font.caption }
      UI.PanelSlider {
        width: parent.width - Style.space(128)
        minimum: parent.datum.min || 0; maximum: parent.datum.max || 100
        value: parent.datum.value || 0; integer: true
        trackColor: Util.alpha(Color.popups.text, 0.12); fillColor: Color.accent; knobColor: Color.popups.text
        onReleased: value => root.act("slider", value, parent.index)
      }
      Label { width: Style.space(55); text: String(Math.round(parent.datum.value || 0)); horizontalAlignment: Text.AlignRight }
    }
  }
  Flow {
    visible: root.kind === "colors"
    width: parent.width
    spacing: Style.space(8)
    Repeater {
      model: root.kind === "colors" ? (root.rowState.colors || []).length : 0
      Column {
        required property int index
        width: Style.space(88)
        spacing: Style.space(4)
        Rectangle { width: parent.width; height: Style.space(14); radius: Style.cornerRadius; color: root.rowState.colors[parent.index] || "#000000" }
        UI.TextField {
          width: parent.width
          text: root.rowState.colors[parent.index] || "#000000"
          font.pixelSize: Style.font.caption
          maximumLength: 7
          validator: RegularExpressionValidator { regularExpression: /#[0-9a-fA-F]{6}/ }
          onEditingFinished: if (acceptableInput) root.act("color", text, parent.index)
        }
      }
    }
  }
  Rectangle {
    visible: root.kind === "level"
    width: parent.width; height: Style.space(6); radius: height / 2
    color: Util.alpha(Color.popups.text, 0.1)
    Rectangle { width: parent.width * Math.max(0, Math.min(1, (root.rowState.value || 0) / (root.rowState.max || 1))); height: parent.height; radius: parent.radius; color: Color.accent }
  }
  Label { visible: root.kind === "label"; width: parent.width; text: String(root.rowState.value || ""); color: Color.accent }
  Flow {
    width: parent.width
    spacing: Style.space(6)
    visible: (root.rowState.buttons || []).length > 0
    Repeater {
      model: (root.rowState.buttons || []).length
      UI.Button {
        required property int index
        readonly property var button: root.rowState.buttons[index] || ({})
        text: button.label || ""; enabled: button.enabled !== false; bordered: true; focusable: true
        onClicked: root.service.act(button.id, "click")
      }
    }
  }
  UI.Button {
    visible: root.kind === "action" || root.kind === "group"
    text: root.kind === "group" ? (root.expanded ? "Hide options" : "Show options") : (root.rowState.title || "Open")
    bordered: true; focusable: true
    onClicked: { if (root.kind === "group") root.expanded = !root.expanded; else root.act("click") }
  }
  Loader {
    width: parent.width
    active: root.kind === "group" && root.expanded
    sourceComponent: Column {
      spacing: Style.space(16)
      Repeater {
        model: root.layout.children || []
        Loader {
          required property var modelData
          width: parent.width
          source: Qt.resolvedUrl("SettingRow.qml")
          onLoaded: { item.layout = modelData; item.service = root.service }
        }
      }
    }
  }
}
