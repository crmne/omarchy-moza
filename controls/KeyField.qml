import QtQuick
import qs.Commons
import qs.Commons as Commons
import qs.Ui

// A single-line text field built from key events instead of Qt's text input
// types. On Qt 6.12 every editable Qt text input reads another application's
// clipboard offer whenever the clipboard changes, with no size limit, even
// while hidden. This field never touches the clipboard: it takes typed
// characters, Backspace and Return, and draws its text with a plain Text.
// There is no paste, selection or caret movement, which the preset name and
// LED colour fields do not need.
//
// `value` is the model's current text. The field follows it while it is not
// being edited; `text` holds what the user typed. Typing emits textEdited(),
// Return or losing focus emits editingFinished().
Item {
  id: root

  property string value: ""
  property string text: ""
  property string placeholderText: ""
  property int maximumLength: 32767
  // When set, each typed character must match this expression.
  property var allowedCharacters: null
  property int horizontalAlignment: Text.AlignLeft
  property color foreground: Commons.Color.popups.text
  property color accent: Commons.Color.accent
  property real horizontalPadding: Style.spacing.controlPaddingX
  property real verticalPadding: Style.spacing.inputPaddingY
  property alias font: label.font

  signal textEdited()
  signal accepted()
  signal editingFinished()

  readonly property bool _hot: mouse.containsMouse
  readonly property var _borderSpec: Border.controlSpec(activeFocus ? "focus" : (_hot ? "hover-cursor" : "normal"), root.foreground, root.accent)

  // Typed text from a key event, or "" for anything that is not plain input.
  function typed(event) {
    if (event.modifiers & (Qt.ControlModifier | Qt.AltModifier | Qt.MetaModifier)) return ""
    var value = String(event.text || "")
    for (var i = 0; i < value.length; i++) {
      var code = value.charCodeAt(i)
      if (code < 32 || code === 127) return ""
      if (root.allowedCharacters && !root.allowedCharacters.test(value[i])) return ""
    }
    return value
  }

  function edit(next) {
    if (next === root.text) return
    root.text = next
    root.textEdited()
  }

  activeFocusOnTab: true
  implicitWidth: Style.space(160)
  implicitHeight: label.implicitHeight + 2 * verticalPadding + Border.top(_borderSpec) + Border.bottom(_borderSpec)

  Component.onCompleted: text = value
  onValueChanged: if (!activeFocus) text = value
  onActiveFocusChanged: if (!activeFocus) editingFinished()

  Keys.onPressed: function(event) {
    if (event.key === Qt.Key_Backspace) {
      // Ctrl+Backspace clears, as there is no selection to delete.
      root.edit(event.modifiers & Qt.ControlModifier ? "" : root.text.slice(0, -1))
      event.accepted = true
    } else if (event.key === Qt.Key_U && (event.modifiers & Qt.ControlModifier)) {
      root.edit("")
      event.accepted = true
    } else if (event.key === Qt.Key_Return || event.key === Qt.Key_Enter) {
      root.accepted()
      root.editingFinished()
      event.accepted = true
    } else {
      var value = root.typed(event)
      if (value === "") return
      if (root.text.length < root.maximumLength) root.edit((root.text + value).slice(0, root.maximumLength))
      event.accepted = true
    }
  }

  BorderSurface {
    anchors.fill: parent
    color: Style.controlFill(root.activeFocus, root._hot, root.foreground, root.accent)
    borderSpec: root._borderSpec
    radius: Style.cornerRadius
  }

  Item {
    id: inner
    anchors.fill: parent
    anchors.leftMargin: root.horizontalPadding + Border.left(root._borderSpec)
    anchors.rightMargin: root.horizontalPadding + Border.right(root._borderSpec)
    clip: true

    Text {
      id: label
      textFormat: Text.PlainText
      anchors.verticalCenter: parent.verticalCenter
      // Long text keeps its end, where typing happens, in view.
      x: implicitWidth > inner.width ? inner.width - implicitWidth - caret.width
        : (root.horizontalAlignment === Text.AlignRight ? inner.width - implicitWidth - caret.width
          : (root.horizontalAlignment === Text.AlignHCenter ? (inner.width - implicitWidth) / 2 : 0))
      text: root.text !== "" ? root.text : root.placeholderText
      color: root.text !== "" ? root.foreground : Qt.darker(root.foreground, 1.6)
      font.family: Style.font.family
      font.pixelSize: Style.font.body
    }

    Rectangle {
      id: caret
      visible: root.activeFocus && blink.on
      x: root.text !== "" ? label.x + label.implicitWidth : label.x
      anchors.verticalCenter: parent.verticalCenter
      width: Math.max(1, Style.spaceReal(1))
      height: label.font.pixelSize * 1.2
      color: root.foreground
    }
  }

  Timer {
    id: blink
    property bool on: true
    interval: 530
    repeat: true
    running: root.activeFocus
    onRunningChanged: on = true
    onTriggered: on = !on
  }

  MouseArea {
    id: mouse
    anchors.fill: parent
    hoverEnabled: true
    cursorShape: Qt.IBeamCursor
    onClicked: root.forceActiveFocus()
  }
}
