import QtQuick
import qs.Commons
import qs.Commons as Commons
import qs.Ui

// The kit NumberField's look and the parts of its API this plugin uses,
// built from key events. The kit field is a SpinBox whose content is a Qt
// text input, and on Qt 6.12 every editable Qt text input reads another
// application's clipboard offer whenever the clipboard changes, with no size
// limit, even while hidden. This field never touches the clipboard.
//
// Focus selects the number, so typing replaces it. Digits, minus (when `from`
// is negative), Backspace, Up and Down, and the step arrows edit it. Return or
// losing focus clamps the typed number to from..to and emits modified(value);
// Escape restores the current value. The wheel is left to the enclosing
// scroll view, so scrolling past a field never changes a setting.
Column {
  id: root

  property string label: ""
  property int value: 0
  property int from: 0
  property int to: 100
  property int stepSize: 1
  property color foreground: Commons.Color.foreground
  property color accent: Commons.Color.accent
  property string fontFamily: Style.font.family
  property real fontSize: Style.font.body
  property real fieldWidth: Style.spacing.numberFieldWidth
  property bool hasCursor: false
  readonly property int displayValue: clamp(_current)

  signal modified(int value)
  signal hovered(bool on)

  // The shown number. It follows `value` and keeps a user's change until the
  // model reports a new value, as the kit field does.
  property int _current: 0
  property string _draft: ""
  property bool _editing: false
  property bool _selected: false

  function clamp(number) { return Math.max(root.from, Math.min(root.to, number)) }

  function commit(number) {
    var next = clamp(number)
    root._editing = false
    root._draft = ""
    if (next === root.displayValue && next === root._current) return
    root._current = next
    root.modified(next)
  }

  function finish() {
    if (!root._editing) return
    var number = parseInt(root._draft, 10)
    if (isNaN(number)) cancel()
    else commit(number)
  }

  function cancel() {
    root._editing = false
    root._draft = ""
  }

  function step(direction) {
    var base = root._editing && !isNaN(parseInt(root._draft, 10)) ? parseInt(root._draft, 10) : root.displayValue
    var next = clamp(base + direction * Math.max(1, root.stepSize))
    root._editing = false
    root._draft = ""
    if (next !== root.displayValue) {
      root._current = next
      root.modified(next)
    }
  }

  function type(character) {
    var draft = root._editing && !root._selected ? root._draft : ""
    if (character === "-" && (root.from >= 0 || draft !== "")) return
    if (character !== "-" && (draft === "0" || draft === "-0")) draft = draft.slice(0, -1)
    // Room for the longest number in range; nothing longer can be valid.
    if (draft.length >= Math.max(String(root.from).length, String(root.to).length)) return
    root._draft = draft + character
    root._editing = true
    root._selected = false
  }

  Component.onCompleted: _current = value
  onValueChanged: _current = value

  spacing: Style.spacing.md

  Text {
    textFormat: Text.PlainText
    visible: root.label !== ""
    text: root.label
    color: Qt.darker(root.foreground, 1.4)
    font.family: root.fontFamily
    font.pixelSize: Style.font.bodySmall
  }

  Item {
    id: box
    width: root.fieldWidth
    height: Math.max(Style.spacing.controlHeight, root.fontSize + Style.spacing.controlPaddingY * 2)
    activeFocusOnTab: true

    readonly property bool _hot: mouse.containsMouse || root.hasCursor
    readonly property var _borderSpec: Border.controlSpec(activeFocus ? "focus" : (_hot ? "hover-cursor" : "normal"), root.foreground, root.accent)

    onActiveFocusChanged: {
      if (activeFocus) {
        root._selected = true
      } else {
        root._selected = false
        root.finish()
      }
    }

    Keys.onPressed: function(event) {
      var plain = !(event.modifiers & (Qt.ControlModifier | Qt.AltModifier | Qt.MetaModifier))
      if (event.key === Qt.Key_Up || event.key === Qt.Key_Down) {
        root.step(event.key === Qt.Key_Up ? 1 : -1)
        root._selected = true
        event.accepted = true
      } else if (event.key === Qt.Key_Return || event.key === Qt.Key_Enter) {
        root.finish()
        root._selected = true
        event.accepted = true
      } else if (event.key === Qt.Key_Escape && root._editing) {
        root.cancel()
        root._selected = true
        event.accepted = true
      } else if (event.key === Qt.Key_Backspace || event.key === Qt.Key_Delete) {
        if (root._selected || !root._editing || (event.modifiers & Qt.ControlModifier)) root._draft = ""
        else root._draft = root._draft.slice(0, -1)
        root._selected = false
        root._editing = true
        event.accepted = true
      } else if (plain && /^[0-9-]$/.test(event.text || "")) {
        root.type(event.text)
        event.accepted = true
      }
    }

    BorderSurface {
      anchors.fill: parent
      color: Style.controlFill(box.activeFocus, box._hot, root.foreground, root.accent)
      borderSpec: box._borderSpec
      radius: Style.cornerRadius
    }

    Rectangle {
      visible: box.activeFocus && root._selected
      anchors.centerIn: number
      width: number.implicitWidth + Style.space(4)
      height: number.font.pixelSize * 1.3
      radius: Style.space(2)
      color: Style.selectionFillFor(root.foreground, root.accent)
    }

    Text {
      id: number
      anchors.centerIn: parent
      textFormat: Text.PlainText
      text: root._editing ? root._draft : String(root.displayValue)
      color: root.foreground
      font.family: root.fontFamily
      font.pixelSize: root.fontSize
    }

    Rectangle {
      visible: box.activeFocus && !root._selected && caretBlink.on
      x: number.x + number.implicitWidth + (root._draft === "" ? 0 : 1)
      anchors.verticalCenter: parent.verticalCenter
      width: Math.max(1, Style.spaceReal(1))
      height: number.font.pixelSize * 1.2
      color: root.foreground
    }

    Timer {
      id: caretBlink
      property bool on: true
      interval: 530
      repeat: true
      running: box.activeFocus && !root._selected
      onRunningChanged: on = true
      onTriggered: on = !on
    }

    MouseArea {
      id: mouse
      anchors.fill: parent
      hoverEnabled: true
      cursorShape: Qt.IBeamCursor
      onClicked: box.forceActiveFocus()
      onContainsMouseChanged: root.hovered(containsMouse)
    }

    Column {
      id: arrows
      anchors.right: parent.right
      anchors.rightMargin: Border.right(box._borderSpec) + Style.space(6)
      anchors.verticalCenter: parent.verticalCenter
      Repeater {
        model: [1, -1]
        Item {
          id: arrow
          required property int modelData
          readonly property bool available: modelData > 0 ? root.displayValue < root.to : root.displayValue > root.from
          width: Style.space(14)
          height: Style.space(10)
          opacity: available ? (press.pressed ? 1 : 0.8) : 0.3

          Canvas {
            id: glyph
            anchors.centerIn: parent
            width: Style.space(8)
            height: Style.space(4)
            property color tint: root.foreground
            onTintChanged: requestPaint()
            onPaint: {
              var context = getContext("2d")
              context.reset()
              context.fillStyle = tint
              context.beginPath()
              if (arrow.modelData > 0) {
                context.moveTo(0, height); context.lineTo(width / 2, 0); context.lineTo(width, height)
              } else {
                context.moveTo(0, 0); context.lineTo(width / 2, height); context.lineTo(width, 0)
              }
              context.closePath()
              context.fill()
            }
          }

          MouseArea {
            id: press
            anchors.fill: parent
            enabled: arrow.available
            cursorShape: Qt.ArrowCursor
            onPressed: { root.step(arrow.modelData); repeat.interval = 400; repeat.start() }
            onReleased: repeat.stop()
            onCanceled: repeat.stop()
          }

          Timer {
            id: repeat
            repeat: true
            onTriggered: {
              interval = 60
              if (arrow.available) root.step(arrow.modelData)
              else stop()
            }
          }
        }
      }
    }
  }
}
