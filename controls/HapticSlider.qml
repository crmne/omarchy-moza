import QtQuick
import qs.Commons
import qs.Commons as Commons
import qs.Ui as UI

// A labelled slider with an exact number field, like Boxflat's slider rows.
Column {
  id: root
  property string label: ""
  property int from: 0
  property int to: 100
  property int value: 0
  signal modified(int value)
  width: parent.width
  spacing: Style.space(4)
  Label { text: root.label; font.pixelSize: Style.font.bodySmall }
  Row {
    width: parent.width
    spacing: Style.space(12)
    UI.PanelSlider {
      width: parent.width - number.width - parent.spacing
      anchors.verticalCenter: parent.verticalCenter
      minimum: root.from; maximum: root.to
      value: root.value; integer: true
      trackColor: Util.alpha(Commons.Color.popups.text, 0.12)
      fillColor: Commons.Color.accent; knobColor: Commons.Color.popups.text
      onReleased: value => root.modified(Math.round(value))
    }
    NumberKeyField {
      id: number
      fieldWidth: Style.space(84)
      from: root.from; to: root.to
      value: root.value
      foreground: Commons.Color.popups.text
      onModified: value => root.modified(value)
    }
  }
}
